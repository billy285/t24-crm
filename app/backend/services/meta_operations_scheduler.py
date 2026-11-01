"""Opt-in future Meta schedules. Prepared plans and unknown writes never run."""
import asyncio
import contextlib
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import select, update
from models.employees import Employees
from models.meta_operations import MetaOperationsSchedule as Schedule, MetaOperationsAction as Action
from services import meta_operations as service
from services import meta_operations_provider as provider


def activation_from():
    value = os.getenv("T24_META_OPS_SCHEDULER_ACTIVATION_FROM", "").strip()
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if at.tzinfo is None or at.utcoffset() is None: return None
        return at.astimezone(timezone.utc)
    except (ValueError, TypeError): return None


def enabled():
    return os.getenv("T24_META_OPS_SCHEDULER_ENABLED", "false").strip().lower() == "true" and activation_from() is not None and provider.execution_enabled()


def configuration(): return {"enabled": enabled(), "activation_from": service.iso(activation_from())}


def sessions_factory():
    from core.database import db_manager
    return db_manager.async_session_maker


async def _sync(db, schedule_id, action_id):
    async with service.write(db):
        row = await db.get(Schedule, schedule_id, populate_existing=True, with_for_update=True)
        action = await db.get(Action, action_id, populate_existing=True)
        if row is None or action is None: return
        row.action_id = action.id
        row.status = "dispatching" if action.status in {"pending", "processing"} else "blocked" if action.status == "failed" else action.status
        row.message = action.message; row.revision += 1; row.updated_at = service.now()


async def run_tick(*, sessions=None, clock=None):
    if not enabled(): return {"stage": "disabled", "processed": 0}
    sessions = sessions or sessions_factory(); at = (clock or service.now)(); cutoff = activation_from()
    if at < cutoff: return {"stage": "waiting_activation", "processed": 0}
    async with sessions() as db:
        from services.schema_readiness import tables_available
        if not await tables_available(db, service.TABLES): return {"stage": "schema_not_ready", "processed": 0}
        async with service.write(db):
            # No catch-up and no inferred permission for old prepared plans.
            await db.execute(update(Schedule).where(Schedule.status == "scheduled",
                (Schedule.planned_at < cutoff) | (Schedule.updated_at < cutoff) | (Schedule.planned_at < at - timedelta(minutes=5)))
                .values(status="missed", revision=Schedule.revision + 1, message="已超过启用界限或错过执行窗口，请老板重新确认未来时间", updated_at=at).execution_options(synchronize_session=False))
            await db.execute(update(Action).where(Action.status == "pending", Action.dispatch_stage.in_(("initial_started", "publish_started")), Action.updated_at < at - timedelta(minutes=5))
                .values(status="unknown", dispatch_stage="unknown", revision=Action.revision + 1, message="原平台执行结果待核实，不会自动重发", updated_at=at).execution_options(synchronize_session=False))
            await db.execute(update(Schedule).where(Schedule.status == "dispatching",
                (Schedule.planned_at < cutoff) | (Schedule.updated_at < cutoff) | (Schedule.planned_at < at - timedelta(minutes=5)))
                .values(status="blocked", revision=Schedule.revision + 1, message="原执行窗口已过，请老板检查原请求；不会自动继续或重发", updated_at=at).execution_options(synchronize_session=False))
            row = await db.scalar(select(Schedule).where(Schedule.status == "dispatching", Schedule.action_id.is_not(None))
                .order_by(Schedule.updated_at, Schedule.id).limit(1).with_for_update())
            if row is not None:
                action = await db.get(Action, row.action_id, populate_existing=True)
                if action and action.status in {"succeeded", "failed", "unknown"}:
                    row.status = "blocked" if action.status == "failed" else action.status; row.message = action.message; row.revision += 1; row.updated_at = at
                    return {"stage": row.status, "processed": 1, "schedule_id": row.id}
                if action and action.status == "processing" and action.dispatch_stage == "container_created":
                    job = {"schedule_id": row.id, "owner_id": row.owner_id, "action_id": action.id, "action_revision": action.revision, "continue": True}
                else: return {"stage": "waiting_original", "processed": 0}
            else:
                row = await db.scalar(select(Schedule).where(Schedule.status == "scheduled", Schedule.planned_at >= cutoff,
                    Schedule.updated_at >= cutoff, Schedule.planned_at >= at - timedelta(minutes=5), Schedule.planned_at <= at)
                    .order_by(Schedule.planned_at, Schedule.id).limit(1).with_for_update())
                if row is None: return {"stage": "idle", "processed": 0}
                employee = await db.get(Employees, row.owner_id, populate_existing=True)
                user = SimpleNamespace(id=str(employee.id), role=employee.role, name=employee.name) if employee else None
                try:
                    if user is None: raise HTTPException(409, "老板账号已失效")
                    ctx = await service.context(db, user)
                    await service._approved(db, ctx, row.draft_id, row.draft_revision, row.preview_hash)
                    row.status = "dispatching"; row.revision += 1; row.message = "已登记原排期，正在核对平台发送条件"; row.updated_at = at
                    job = {"schedule_id": row.id, "owner_id": row.owner_id, "draft_id": row.draft_id, "draft_revision": row.draft_revision,
                        "preview_hash": row.preview_hash, "request_id": str(uuid5(NAMESPACE_URL, "t24-meta-schedule:" + str(row.id) + ":" + row.request_id)), "continue": False}
                except HTTPException:
                    row.status = "blocked"; row.revision += 1; row.message = "账号、授权、内容或图片已变化，请老板重新核对"; row.updated_at = at
                    return {"stage": "blocked", "processed": 1, "schedule_id": row.id}
        employee = await db.get(Employees, job["owner_id"], populate_existing=True)
        user = SimpleNamespace(id=str(employee.id), role=employee.role, name=employee.name) if employee else None
        try:
            if user is None: raise HTTPException(409, "老板账号已失效")
            if job["continue"]:
                await service.continue_action(db, user, job["action_id"], expected_revision=job["action_revision"])
                identity = job["action_id"]
            else:
                identity, fresh = await service._reserve(db, user, job["draft_id"], request_id=job["request_id"],
                    expected_revision=job["draft_revision"], preview_hash=job["preview_hash"], schedule_id=job["schedule_id"])
                async with service.write(db):
                    row = await db.get(Schedule, job["schedule_id"], populate_existing=True, with_for_update=True)
                    if row.status != "dispatching": raise HTTPException(409, "原排期状态已变化")
                    row.action_id = identity; row.updated_at = at
                if fresh: await service._dispatch(db, user, identity)
            await _sync(db, job["schedule_id"], identity)
        except asyncio.CancelledError: raise
        except Exception:
            await db.rollback()
            async with service.write(db):
                row = await db.get(Schedule, job["schedule_id"], populate_existing=True, with_for_update=True)
                if row and row.status == "dispatching" and row.action_id is None:
                    row.status = "blocked"; row.message = "原排期未完成发送登记，请核对原请求后重新安排"; row.revision += 1; row.updated_at = at
        return {"stage": "processed", "processed": 1, "schedule_id": job["schedule_id"]}


async def run_worker():
    while enabled():
        try: await run_tick()
        except asyncio.CancelledError: raise
        except Exception: pass
        await asyncio.sleep(30)


def start_scheduler(): return asyncio.create_task(run_worker()) if enabled() else None


async def stop_scheduler(task):
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError): await task
