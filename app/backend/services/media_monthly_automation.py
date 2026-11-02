"""Owner-consented, bounded next-month TEXT drafts. Never approve or publish.

An occurrence is committed before calling the existing single-attempt monthly
generator. Unknown/failed/interrupted occurrences are never retried by this
worker. Changes to the pinned merchant sources, account or AI destination need
new owner confirmation; no sensitive material or image bytes enter AI input.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_, select
from models.employees import Employees
from models.media_monthly import MediaMonthlyProfile as Profile, MediaMonthlyRun as Run
from models.media_monthly_automation import MediaMonthlyAutomationPolicy as Policy, MediaMonthlyAutomationOccurrence as Occurrence, MediaMonthlyAutomationRequest as Request
from services import media_monthly as monthly, media_operations as media
from services.schema_readiness import require_tables, tables_available

TABLES = {Policy.__tablename__, Occurrence.__tablename__, Request.__tablename__}
NOTICE_VERSION = "monthly-autoprep-v1"
NOTICE = "仅按本次确认的商家公开事实、所选菜单、图片对应菜品及频率，在下月开始前自动准备一次文字草案。图片字节、文件链接、联系人、CRM私密备注、财务及私人空间内容不发送。菜单、素材、账号、规则或AI服务变化会暂停并提示重新确认；不会自动审核、排期或公开发布。"
MAX_PER_TICK = 2
OWNER_DAILY_LIMIT = 24
GLOBAL_DAILY_LIMIT = 72
SCAN_LIMIT = 200
STATUSES = {"running", "generated", "existing", "blocked", "unknown", "failed", "missed"}


def now(): return monthly.now()
def enabled(): return os.getenv("T24_MEDIA_MONTHLY_AUTOPREP_ENABLED", "false").strip().lower() == "true"
def worker_configuration():
    return {"enabled": enabled(), "max_per_tick": MAX_PER_TICK, "owner_daily_limit": OWNER_DAILY_LIMIT, "global_daily_limit": GLOBAL_DAILY_LIMIT, "day_basis": "UTC"}


def target_window(at, zone_name, lead_days=7):
    """Only NEXT month, with an unambiguous 09:00 local preparation time."""
    local = monthly.aware(at).astimezone(ZoneInfo(zone_name))
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    first = datetime(year, month, 1, tzinfo=ZoneInfo(zone_name))
    trigger = (first - timedelta(days=lead_days)).replace(hour=9)
    return f"{year:04d}-{month:02d}", trigger.astimezone(timezone.utc), first.astimezone(timezone.utc)


async def _context(db, user, customer_id=None, *, write=False):
    ctx, customer = await monthly.context(db, user, customer_id, write=write)
    await require_tables(db, TABLES)
    return ctx, customer


async def _policy(db, owner_id, customer_id, platform, *, lock=False):
    statement = select(Policy).where(Policy.owner_id == owner_id, Policy.customer_id == customer_id, Policy.platform == platform).execution_options(populate_existing=True)
    return await db.scalar(statement.with_for_update() if lock else statement)


def policy_data(row):
    if row is None: return None
    fields = ("id", "revision", "enabled", "lead_days", "local_time", "timezone", "profile_revision", "source_signature", "runtime_fingerprint")
    return {**{key: getattr(row, key) for key in fields}, **{key: monthly.iso(getattr(row, key)) for key in ("confirmed_at", "created_at", "updated_at")}}


async def _source(db, ctx, customer, platform, at, lead_days):
    row = await db.scalar(select(Profile).where(Profile.owner_id == ctx.identity, Profile.customer_id == customer.id).execution_options(populate_existing=True))
    profile = monthly.effective_profile(row, platform)
    gaps = []; blocking = []
    zone = None
    if profile:
        try: zone = monthly.valid_rules(profile.rules).key
        except HTTPException: blocking.append("已保存规则的门店时区或频率需要重新核对")
    else: blocking.append("请先在本商家、本平台保存已核实的整月资料和规则")
    month, trigger, _ = target_window(at, zone or "UTC", lead_days)
    try: _, runtime = await monthly._runtime(db)
    except HTTPException:
        runtime = {"enabled": False, "provider": "", "model": "", "destination_host": "", "fingerprint": None}
    if not runtime["enabled"]: blocking.append("AI服务尚未配置或需要老板重新核对")
    if customer.status != "closed": blocking.append("客户当前未处于合作状态，自动准备已暂停")
    snapshot = None; input_hash = None; signature = None
    if profile:
        try:
            snapshot, input_hash, _, _, gaps = await monthly._platform_input(db, ctx, customer, profile, month, platform)
            if not snapshot: raise HTTPException(409, "当前资料尚未确认")
            # The consent pin excludes only the future calendar. Prices,
            # material fingerprints, quality acknowledgements and binding
            # revisions all remain pinned. Public sender switches do not grant
            # or revoke a text-only preparation policy.
            pin = {key: value for key, value in snapshot.items() if key != "slots"}
            if "meta_binding" in pin:
                pin["meta_binding"] = {key: value for key, value in pin["meta_binding"].items() if key != "configuration"}
            if platform == "google_business":
                from services.media_monthly_workflow import _binding
                binding = await _binding(db, ctx, customer)
                if not binding or not binding["active"] or binding["lifecycle"] != "active" or not binding["connection_active"] or binding["needs_reconnect"]:
                    raise HTTPException(409, "本商家的Google连接或门店绑定需要老板核对")
                pin["google_binding"] = binding
            if not profile.menu_item_ids and not profile.rules.get("generic_mode"):
                blocking.append("请确认所选菜单或明确选择仅公开门店介绍模式")
            if any(image["quality_warnings"] and image.get("quality_confirmed") is not True for image in snapshot["images"]):
                blocking.append("请确认未就绪图片只作为内部草稿参考，不代表发布质量通过")
            # Match the native generator's deterministic image/menu rotation
            # for input-size validation; setup snapshots do not assign menus
            # to calendar slots until generation is reserved.
            choices = snapshot["images"]; menu_ids = [item["id"] for item in snapshot["menu_items"]]
            planned = [dict(slot, image_index=index % len(choices), menu_item_ids=[choices[index % len(choices)]["menu_item_id"]]
                if choices[index % len(choices)].get("menu_item_id") else ([menu_ids[index % len(menu_ids)]] if menu_ids else []))
                for index, slot in enumerate(snapshot["slots"])]
            monthly._ai_payload({**snapshot, "slots": planned})
            signature = monthly.digest(pin)
        except HTTPException as exc:
            blocking.append(str(exc.detail)[:200]); snapshot = None; input_hash = None
    return {"profile": profile, "snapshot": snapshot, "input_hash": input_hash, "source_signature": signature,
        "runtime": runtime, "timezone": zone, "next_target_month": month, "next_run_at": monthly.iso(trigger) if zone else None,
        "can_enable": bool(signature and snapshot and profile and runtime["enabled"] and not blocking),
        "gaps": list(dict.fromkeys(blocking + gaps))[:24]}


async def _job_data(db, row, at=None):
    if row is None: return None
    value = {key: getattr(row, key) for key in ("id", "request_id", "customer_id", "customer_name", "platform", "month", "status", "run_id", "message")}
    # Read recovery uses the exact original request only. It never calls AI,
    # replays a write, marks an item reviewed or repairs a public schedule.
    if row.status in {"running", "unknown"}:
        run = await db.scalar(select(Run).where(Run.owner_id == row.owner_id, Run.request_id == row.request_id).execution_options(populate_existing=True))
        if run and run.customer_id == row.customer_id and monthly.run_platform(run) == row.platform:
            value["run_id"] = run.id
            if run.status in {"generated", "adopted"}:
                value.update(status="generated", message="本月文字草案已准备，等待老板集中审核；未安排公开发布")
            elif run.status in {"failed", "unknown"}:
                value.update(status=run.status, message="原文字生成未完成或结果待确认，请查看原批次；不会自动再次调用AI")
        if value["status"] == "running" and monthly.aware(row.updated_at) < monthly.aware(at or now()) - timedelta(minutes=5):
            value.update(status="unknown", message="原自动准备已中断或结果待确认；保留原请求，不会自动重试")
    return {**value, "created_at": monthly.iso(row.created_at), "updated_at": monthly.iso(row.updated_at)}


async def get_policy(db, user, customer_id, *, platform="google_business", at=None):
    monthly.platform_value(platform)
    ctx, customer = await _context(db, user, customer_id)
    row = await _policy(db, ctx.identity, customer.id, platform)
    source = await _source(db, ctx, customer, platform, at or now(), row.lead_days if row else 7)
    jobs = list((await db.scalars(select(Occurrence).where(Occurrence.owner_id == ctx.identity, Occurrence.customer_id == customer.id, Occurrence.platform == platform).order_by(Occurrence.created_at.desc(), Occurrence.id.desc()).limit(12))).all())
    recent = [await _job_data(db, job, at) for job in jobs]
    gaps = list(source["gaps"])
    if row and row.enabled and (source["source_signature"] != row.source_signature or source["runtime"]["fingerprint"] != row.runtime_fingerprint):
        gaps.insert(0, "资料、账号或AI服务已变化，原自动准备确认已失效，请重新核对并保存")
    return {"customer": {"id": customer.id, "name": customer.business_name}, "platform": platform,
        "policy": policy_data(row), "timezone": source["timezone"], "next_target_month": source["next_target_month"], "next_run_at": source["next_run_at"],
        "source_signature": source["source_signature"], "runtime": source["runtime"],
        "notice": {"version": NOTICE_VERSION, "text": NOTICE, "send_fields": monthly.SEND_FIELDS},
        "eligibility": {"can_enable": source["can_enable"], "gaps": gaps}, "worker": worker_configuration(),
        "latest_job": recent[0] if recent else None, "recent_jobs": recent, "automatic_publish": False}


async def save_policy(db, user, customer_id, *, platform="google_business", request_id, expected_revision, enabled, lead_days, local_time, source_signature, runtime_fingerprint, confirmed, notice_version):
    monthly.platform_value(platform)
    ctx, _ = await _context(db, user, customer_id)
    identity = media._key(request_id)
    if type(enabled) is not bool or type(lead_days) is not int or not 3 <= lead_days <= 14 or local_time != "09:00" or notice_version != NOTICE_VERSION:
        raise HTTPException(422, "请核对提前3—14天、门店当地09:00及自动草稿用途说明")
    fingerprint = monthly.digest({"customer_id": customer_id, "platform": platform, "expected_revision": expected_revision, "enabled": enabled,
        "lead_days": lead_days, "local_time": local_time, "source_signature": source_signature, "runtime_fingerprint": runtime_fingerprint,
        "confirmed": confirmed, "notice_version": notice_version})
    async with media._write(db):
        ctx, customer = await _context(db, user, customer_id, write=enabled)
        old = await db.scalar(select(Request).where(Request.owner_id == ctx.identity, Request.request_id == identity))
        if old:
            if old.fingerprint != fingerprint: raise HTTPException(409, "原请求编号对应另一份自动准备设置，请查询原结果")
            return {**old.result, "receipt_request_id": identity}
        row = await _policy(db, ctx.identity, customer_id, platform, lock=True)
        if (row.revision if row else 0) != expected_revision: raise HTTPException(409, "本平台自动准备设置已变化，请读取后重新确认")
        source = await _source(db, ctx, customer, platform, now(), lead_days)
        if enabled:
            if confirmed is not True or not source["can_enable"]: raise HTTPException(409, "请先核对当前商家资料、菜单、图片对应关系和AI文字发送范围")
            if source_signature != source["source_signature"] or runtime_fingerprint != source["runtime"]["fingerprint"]:
                raise HTTPException(409, "商家资料、账号或AI服务已变化，请读取后重新确认")
        elif row is None:
            raise HTTPException(409, "当前没有启用中的自动准备设置")
        at = now()
        if row is None:
            row = Policy(owner_id=ctx.identity, customer_id=customer.id, platform=platform, revision=0, enabled=False, created_at=at, updated_at=at)
            db.add(row)
        row.revision += 1; row.enabled = enabled; row.lead_days = lead_days; row.local_time = local_time; row.updated_at = at
        if enabled:
            row.timezone = source["timezone"]; row.profile_revision = source["profile"].revision
            row.source_signature = source_signature; row.runtime_fingerprint = runtime_fingerprint
            row.first_target_month = source["next_target_month"]; row.confirmed_at = at
        await db.flush()
        result = await get_policy(db, user, customer_id, platform=platform)
        db.add(Request(owner_id=ctx.identity, customer_id=customer_id, platform=platform, request_id=identity, fingerprint=fingerprint, result=result, created_at=at))
    return {**result, "receipt_request_id": identity}


async def request_result(db, user, request_id):
    ctx, _ = await _context(db, user)
    identity = media._key(request_id)
    row = await db.scalar(select(Request).where(Request.owner_id == ctx.identity, Request.request_id == identity))
    if row is None: raise HTTPException(404, "未找到本老板账号的原设置请求")
    await monthly.context(db, user, row.customer_id)
    current = await _policy(db, ctx.identity, row.customer_id, row.platform)
    return {"request_id": identity, "customer_id": row.customer_id, "platform": row.platform, "result": row.result, "current_revision": current.revision if current else 0}


async def overview(db, user):
    ctx, _ = await _context(db, user)
    end = now(); start = end - timedelta(days=31)
    policy_count = await db.scalar(select(func.count(Policy.id)).where(Policy.owner_id == ctx.identity))
    active_count = await db.scalar(select(func.count(Policy.id)).where(Policy.owner_id == ctx.identity, Policy.enabled.is_(True)))
    rows = list((await db.scalars(select(Occurrence).where(Occurrence.owner_id == ctx.identity, Occurrence.created_at >= start).order_by(Occurrence.created_at.desc(), Occurrence.id.desc()).limit(20))).all())
    counts = {"policies": policy_count or 0, "enabled": active_count or 0}
    native_platform = Run.snapshot["platform"].as_string()
    same_platform = or_(native_platform == Occurrence.platform,
        and_(Occurrence.platform == "google_business", native_platform.is_(None)))
    recoverable = Occurrence.status.in_(("running", "unknown"))
    projected = case(
        (and_(recoverable, Run.status.in_(("generated", "adopted"))), "generated"),
        (and_(recoverable, Run.status == "failed"), "failed"),
        (and_(recoverable, Run.status == "unknown"), "unknown"),
        (and_(Occurrence.status == "running", Occurrence.updated_at < end-timedelta(minutes=5)), "unknown"),
        else_=Occurrence.status)
    # Full owner totals, not the latest-20 display slice. Resolve exact original
    # generation receipts in SQL so a recovered draft is not still reported as
    # an unknown job. No provider refresh or per-merchant fan-out.
    original_run = and_(Run.owner_id == Occurrence.owner_id, Run.customer_id == Occurrence.customer_id,
        Run.request_id == Occurrence.request_id, same_platform)
    groups = dict((await db.execute(select(projected, func.count(Occurrence.id)).select_from(Occurrence)
        .outerjoin(Run, original_run)
        .where(Occurrence.owner_id == ctx.identity, Occurrence.created_at >= start).group_by(projected))).all())
    counts.update(blocked=sum(groups.get(status, 0) for status in ("blocked", "failed", "missed")),
        unknown=groups.get("unknown", 0), generated=groups.get("generated", 0))
    # Keep exceptions independently visible even when the newest twenty jobs
    # are successful. Use the same exact-request recovery projection as totals;
    # recovering a generated draft must also remove it from the attention list.
    attention = list((await db.scalars(select(Occurrence).select_from(Occurrence).outerjoin(Run, original_run)
        .where(Occurrence.owner_id == ctx.identity, Occurrence.created_at >= start,
            projected.in_(("blocked", "failed", "missed", "unknown")))
        .order_by(Occurrence.created_at.desc(), Occurrence.id.desc()).limit(20))).all())
    return {"automatic_publish": False, "worker": worker_configuration(), "counts": counts,
        "period_start": monthly.iso(start), "period_end": monthly.iso(end), "recent_jobs": [await _job_data(db, row, end) for row in rows],
        "attention_total": counts["blocked"] + counts["unknown"], "attention_jobs": [await _job_data(db, row, end) for row in attention]}


def sessions_factory():
    from core.database import db_manager
    return db_manager.async_session_maker


async def _actor(db, identity):
    employee = await db.get(Employees, identity, populate_existing=True)
    return SimpleNamespace(id=str(employee.id), role=employee.role, name=employee.name) if employee else None


async def _existing_month(db, policy, month):
    return await db.scalar(select(Run).where(Run.owner_id == policy.owner_id, Run.customer_id == policy.customer_id,
        Run.month == month, monthly.platform_clause(policy.platform)).order_by(Run.id.desc()).limit(1))


def _existing_status(run):
    return "existing" if run.status in {"generated", "adopted"} else "unknown" if run.status in {"generating", "unknown"} else "blocked"


async def _record_expired_month(db, policy, at):
    # A daily budget or interrupted service can exhaust the preparation window.
    # Surface only the CURRENT local month's missing preparation, never walk
    # older months or call AI to backfill an expired/current month.
    month = monthly.aware(at).astimezone(ZoneInfo(policy.timezone)).strftime("%Y-%m")
    if month < policy.first_target_month:
        return None
    previous = await db.scalar(select(Occurrence.id).where(Occurrence.owner_id == policy.owner_id,
        Occurrence.customer_id == policy.customer_id, Occurrence.platform == policy.platform, Occurrence.month == month).limit(1))
    if previous:
        return None
    user = await _actor(db, policy.owner_id)
    if user is None:
        return None
    try:
        _, customer = await _context(db, user, policy.customer_id)
    except HTTPException:
        return None  # revoked identity/ownership never obtains new source access
    existing = await _existing_month(db, policy, month)
    identity = str(uuid5(NAMESPACE_URL, f"t24-monthly-autoprep:{policy.owner_id}:{policy.customer_id}:{policy.platform}:{month}"))
    job = Occurrence(policy_id=policy.id, policy_revision=policy.revision, owner_id=policy.owner_id,
        customer_id=policy.customer_id, customer_name=customer.business_name, platform=policy.platform, month=month,
        request_id=identity, source_signature=policy.source_signature, runtime_fingerprint=policy.runtime_fingerprint,
        generation_input=None, run_id=existing.id if existing else None, status=_existing_status(existing) if existing else "missed",
        message="本月已有原批次，保留原文案与审核安排，不重复生成" if existing else "本月自动准备窗口已过，未生成或补发内容；请老板核对后在原整月流程中处理",
        ai_attempted_at=None, created_at=at, updated_at=at)
    db.add(job); await db.flush()
    return {"id": job.id, "user": user, "generate": False}


async def _claim(db, at):
    """Atomic reservation, including owner/global daily AI budgets."""
    async with media._write(db):
        stale = list((await db.scalars(select(Occurrence).where(Occurrence.status == "running", Occurrence.updated_at < at - timedelta(minutes=5)).order_by(Occurrence.id).limit(SCAN_LIMIT).with_for_update())).all())
        for old in stale:
            recovered = await _job_data(db, old, at)
            old.status = recovered["status"]; old.run_id = recovered["run_id"]; old.message = recovered["message"]; old.updated_at = at
        policies = list((await db.scalars(select(Policy).where(Policy.enabled.is_(True)).order_by(Policy.last_checked_at.asc().nullsfirst(), Policy.id).limit(SCAN_LIMIT).with_for_update(skip_locked=True))).all())
        day_start = at.replace(hour=0, minute=0, second=0, microsecond=0)
        global_attempts = await db.scalar(select(func.count(Occurrence.id)).where(Occurrence.ai_attempted_at >= day_start)) or 0
        for policy in policies:
            policy.last_checked_at = at
            expired = await _record_expired_month(db, policy, at)
            if expired:
                return expired
            month, trigger, first = target_window(at, policy.timezone, policy.lead_days)
            if not trigger <= at < first or month < policy.first_target_month: continue
            previous = await db.scalar(select(Occurrence.id).where(Occurrence.owner_id == policy.owner_id, Occurrence.customer_id == policy.customer_id, Occurrence.platform == policy.platform, Occurrence.month == month).limit(1))
            if previous: continue
            user = await _actor(db, policy.owner_id)
            source = None; message = ""; status = "running"; customer_name = "商家"
            try:
                if user is None: raise HTTPException(409, "老板账号已失效")
                ctx, customer = await _context(db, user, policy.customer_id, write=True)
                customer_name = customer.business_name
                source = await _source(db, ctx, customer, policy.platform, at, policy.lead_days)
                if not source["can_enable"] or source["source_signature"] != policy.source_signature or source["runtime"]["fingerprint"] != policy.runtime_fingerprint or source["profile"].revision != policy.profile_revision:
                    raise HTTPException(409, "商家资料、账号、合作状态或AI服务已变化，请老板重新确认自动准备")
                existing = await _existing_month(db, policy, month)
                if existing:
                    status = _existing_status(existing)
                    message = "本月已有原批次，保留原文案与审核安排，不重复生成"
            except HTTPException as exc:
                status = "blocked"; message = str(exc.detail)[:300]; existing = None
            # Non-AI outcomes remain visible even when the daily AI cap is hit.
            if status == "running":
                owner_attempts = await db.scalar(select(func.count(Occurrence.id)).where(Occurrence.owner_id == policy.owner_id, Occurrence.ai_attempted_at >= day_start)) or 0
                if global_attempts >= GLOBAL_DAILY_LIMIT or owner_attempts >= OWNER_DAILY_LIMIT:
                    continue  # still next month; check again on another day
            identity = str(uuid5(NAMESPACE_URL, f"t24-monthly-autoprep:{policy.owner_id}:{policy.customer_id}:{policy.platform}:{month}"))
            generation = None
            if status == "running":
                generation = {"request_id": identity, "expected_profile_revision": policy.profile_revision, "month": month, "platform": policy.platform,
                    "input_hash": source["input_hash"], "consent": {"confirmed": True, "notice_version": monthly.NOTICE_VERSION, "input_hash": source["input_hash"], "runtime_fingerprint": policy.runtime_fingerprint}}
            job = Occurrence(policy_id=policy.id, policy_revision=policy.revision, owner_id=policy.owner_id, customer_id=policy.customer_id, customer_name=customer_name,
                platform=policy.platform, month=month, request_id=identity, source_signature=policy.source_signature, runtime_fingerprint=policy.runtime_fingerprint,
                generation_input=generation, run_id=existing.id if existing else None, status=status,
                message=message or "已登记本次自动准备，正在核对原生成请求；不会审核、排期或发布", ai_attempted_at=at if status == "running" else None, created_at=at, updated_at=at)
            db.add(job); await db.flush()
            return {"id": job.id, "user": user, "generate": status == "running"}
    return None


async def _execute(db, claim):
    identity = claim["id"]
    job = await db.get(Occurrence, identity, populate_existing=True)
    if not job or job.status != "running" or not claim["generate"]: return
    generation = dict(job.generation_input)
    try:
        # Pause and source changes are checked again after durable reservation.
        policy = await db.get(Policy, job.policy_id, populate_existing=True)
        if not enabled() or not policy or not policy.enabled or policy.revision != job.policy_revision:
            raise HTTPException(409, "自动准备已暂停或设置已变化，未调用新的文字生成")
        ctx, customer = await _context(db, claim["user"], job.customer_id, write=True)
        source = await _source(db, ctx, customer, policy.platform, now(), policy.lead_days)
        if source["next_target_month"] != job.month:
            raise HTTPException(409, "原自动准备窗口已过，不补做历史或当月批次")
        if source["source_signature"] != job.source_signature or source["runtime"]["fingerprint"] != job.runtime_fingerprint:
            raise HTTPException(409, "商家资料、账号或AI服务已变化，未调用新的文字生成")
        result = await monthly.generate(db, claim["user"], job.customer_id, **generation)
        async with media._write(db):
            job = await db.get(Occurrence, identity, populate_existing=True, with_for_update=True)
            if result["customer_id"] != job.customer_id or result.get("platform", "google_business") != job.platform:
                raise HTTPException(409, "原生成结果归属需要核对")
            job.run_id = result["id"]
            job.status = "generated" if result["status"] in {"generated", "adopted"} else "unknown" if result["status"] in {"generating", "unknown"} else "failed"
            job.message = "本月文字草案已准备，等待老板集中审核；未安排公开发布" if job.status == "generated" else "原文字生成未完成或结果待确认，请查看原批次；不会自动再次调用AI"
            job.updated_at = now()
    except asyncio.CancelledError:
        raise  # committed occurrence survives; never replay on restart
    except Exception as exc:
        await db.rollback()
        async with media._write(db):
            job = await db.get(Occurrence, identity, populate_existing=True, with_for_update=True)
            if not job: return
            recovered = await _job_data(db, job)
            if recovered["run_id"]:
                job.run_id = recovered["run_id"]; job.status = recovered["status"]; job.message = recovered["message"]
            else:
                job.status = "blocked" if isinstance(exc, HTTPException) and exc.status_code in {403, 404, 409, 422} else "unknown"
                job.message = "账号、商家资料或设置需要重新核对，未继续自动准备" if job.status == "blocked" else "原自动准备结果待确认；保留原请求，不会自动重试"
            job.updated_at = now()


async def run_tick(*, sessions=None, clock=None):
    if not enabled(): return {"stage": "disabled", "processed": 0}
    sessions = sessions or sessions_factory()
    processed = 0
    for _ in range(MAX_PER_TICK):
        at = monthly.aware((clock or now)())
        async with sessions() as db:
            if not await tables_available(db, TABLES | monthly.TABLES): return {"stage": "schema_not_ready", "processed": processed}
            claim = await _claim(db, at)
            if not claim: break
            processed += 1
            await _execute(db, claim)
    return {"stage": "processed" if processed else "idle", "processed": processed}
