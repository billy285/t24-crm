"""Opt-in approved-content dispatcher. No catch-up, blind retry or external AI."""
import asyncio
import contextlib
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from fastapi import HTTPException
from sqlalchemy import select, update
from models.employees import Employees
from models.google_business import GoogleBusinessSchedule as Schedule, GoogleBusinessAction as Action, GoogleBusinessBinding as Binding
from services import google_business as g


def activation_from():
    value = os.getenv('T24_GBP_SCHEDULER_ACTIVATION_FROM', '').strip()
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None or result.utcoffset() is None: return None
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError): return None


def enabled():
    return os.getenv('T24_GBP_SCHEDULER_ENABLED', 'false').strip().lower() == 'true' and activation_from() is not None


def configuration():
    at = activation_from()
    return {'enabled': enabled(), 'activation_from': g.iso(at)}


def sessions_factory():
    from core.database import db_manager
    return db_manager.async_session_maker


async def run_tick(*, sessions=None, clock=None):
    if not enabled(): return {'stage': 'disabled', 'processed': 0}
    sessions = sessions or sessions_factory(); at = (clock or g.now)(); cutoff = activation_from()
    if cutoff is None or at < cutoff: return {'stage': 'waiting_activation', 'processed': 0}
    async with sessions() as db:
        from services.schema_readiness import tables_available
        if not await tables_available(db, {'google_business_schedules'}): return {'stage': 'schema_not_ready', 'processed': 0}
        async with g.write(db):
            # Deliberately do not replay historical jobs or a crashed dispatch.
            await db.execute(update(Schedule).where(Schedule.status == 'scheduled',
                (Schedule.planned_at < cutoff) | (Schedule.planned_at < at - timedelta(minutes=5)))
                .values(status='missed', message='已超过启用界限或错过发布窗口，请老板重新核对后创建新排期', revision=Schedule.revision + 1, updated_at=at)
                .execution_options(synchronize_session=False))
            await db.execute(update(Schedule).where(Schedule.status == 'dispatching', Schedule.updated_at < at - timedelta(minutes=5))
                .values(status='unknown', message='原调度执行结果待确认，不会重新发送', revision=Schedule.revision + 1, updated_at=at)
                .execution_options(synchronize_session=False))
            row = await db.scalar(select(Schedule).where(Schedule.status == 'scheduled', Schedule.planned_at >= cutoff,
                Schedule.planned_at >= at - timedelta(minutes=5), Schedule.planned_at <= at).order_by(Schedule.planned_at, Schedule.id).limit(1).with_for_update())
            if row is None: return {'stage': 'idle', 'processed': 0}
            employee = await db.get(Employees, row.operator_id, populate_existing=True)
            user = SimpleNamespace(id=str(employee.id), role=employee.role, name=employee.name) if employee else None
            try:
                if user is None: raise HTTPException(409, '主运营账号已失效')
                ctx = await g.context(db, user)
                binding, connection, _ = await g._binding(db, ctx, row.binding_id, action='publish', lock=True)
                if connection.owner_id != row.owner_id or binding.primary_operator_id != row.operator_id: raise HTTPException(409, '商家主运营或连接归属已变更')
                task, payload, _ = await g._post_payload(db, ctx, binding, row.task_id, row.task_revision)
                if task.assignee_id != row.operator_id or g.digest(payload) != row.payload_fingerprint: raise HTTPException(409, '审核内容、素材或任务负责人已变化')
                row.status = 'dispatching'; row.revision += 1; row.updated_at = at; row.message = '调度已登记，正在再次核查发布条件'
                job = {'id': row.id, 'binding_id': row.binding_id, 'task_id': row.task_id, 'task_revision': row.task_revision,
                    'request_id': row.request_id, 'user': user, 'payload': payload, 'actor_id': row.operator_id}
            except HTTPException as exc:
                row.status = 'blocked'; row.revision += 1; row.updated_at = at; row.message = str(exc.detail)
                return {'stage': 'blocked', 'processed': 1, 'schedule_id': row.id}
        # Reservation/claim are durable before network, never inside a long DB write.
        try:
            ctx = await g.context(db, job['user'])
            action_id, fresh = await g._reserve(db, ctx, job['binding_id'], 'post_publish', job['request_id'], job['payload'],
                task_id=job['task_id'], expected_revision=job['task_revision'])
            async with g.write(db):
                row = await db.get(Schedule, job['id'], populate_existing=True)
                if row.status != 'dispatching': raise HTTPException(409, '排期状态已变更，请核对原发布请求')
                row.action_id = action_id; row.updated_at = at
            if fresh:
                await g._dispatch(db, job['user'], action_id, expected_revision=job['task_revision'], schedule_id=job['id'])
        except HTTPException:
            await db.rollback()
        except asyncio.CancelledError:
            # Committed dispatch remains fenced; a restart never creates a new attempt.
            raise
        except Exception:
            await db.rollback()  # Never print provider bodies, tokens or app data.
        async with g.write(db):
            row = await db.get(Schedule, job['id'], populate_existing=True)
            action = await db.scalar(select(Action).where(Action.actor_id == job['actor_id'], Action.request_id == job['request_id']))
            if action:
                row.action_id = action.id; row.status = action.status; row.message = action.message
            else:
                row.status = 'blocked'; row.message = '调度未完成发布登记，请老板核对后重新安排'
            row.revision += 1; row.updated_at = g.now()
        return {'stage': row.status, 'processed': 1, 'schedule_id': row.id}


async def run_worker():
    while enabled():
        try: await run_tick()
        except asyncio.CancelledError: raise
        except Exception: pass  # A later tick only claims never-dispatched jobs.
        await asyncio.sleep(30)


def start_scheduler():
    return asyncio.create_task(run_worker()) if enabled() else None


async def stop_scheduler(task):
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError): await task
