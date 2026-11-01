"""Owner-scoped whole-month Meta packets using the existing native sender.

Private preparation/review and prepared schedules never grant public execution.
A persisted explicit native operating grant is required even for preparation.
No OAuth grant, employee ACL, business calculation or provider call is created.
"""
import asyncio
import hashlib
import io
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from models.employees import Employees
from models.media_monthly_workflow import MediaMonthlyWorkflow as Workflow, MediaMonthlyWorkflowRequest as Request
from models.media_monthly import MediaMonthlyRun as Run
from models.meta_operations import MetaOperationsBinding as Binding, MetaOperationsCredential as Credential, MetaOperationsDraft as Draft, MetaOperationsMedia as Media, MetaOperationsSchedule as Schedule, MetaOperationsAction as Action, MetaOperationsRequest as NativeRequest
from services import media_monthly as monthly, media_monthly_workflow as base
from services import media_operations as media, media_publication_images as images
from services import meta_operations as ops, meta_operations_media as pixels, meta_operations_scheduler as scheduler, meta_operations_provider as provider
from services.schema_readiness import require_tables, tables_available

META = {"facebook", "instagram"}
ACTIVE = {"prepared", "scheduled", "dispatching", "processing", "unknown", "succeeded"}
EXCEPTIONS = {"blocked", "unknown", "missed", "failed"}


async def binding_for(db, ctx, customer, platform):
    if platform not in META: raise HTTPException(422, "请选择Facebook或Instagram")
    await require_tables(db, ops.TABLES)
    rows = list((await db.scalars(select(Binding).where(Binding.owner_id == ctx.identity, Binding.customer_id == customer.id, Binding.platform == platform, Binding.active.is_(True)).execution_options(populate_existing=True))).all())
    if len(rows) != 1: raise HTTPException(409, "本客户、本平台尚无唯一有效的独立运营授权；只读连接不会自动获得运营权限")
    binding = await ops._binding(db, ctx, rows[0].id)
    if not isinstance(binding, Binding) or (binding.owner_id, binding.customer_id, binding.platform) != (ctx.identity, customer.id, platform):
        raise HTTPException(409, "独立运营授权归属已变化")
    # Local verification only: no provider enumeration/capability API during
    # private month preparation or central workspace aggregation.
    credential = await db.get(Credential, binding.credential_id, populate_existing=True)
    try: _, scopes = provider.OpsClient(credential.token_encrypted).access()
    except (provider.OpsProviderError, AttributeError): raise HTTPException(409, "独立运营凭据需重新核对") from None
    granted = credential.granted_scopes
    if not isinstance(granted, list) or len(granted) > 100 or not all(type(x) is str for x in granted) or len(set(granted)) != len(granted) or set(granted) != set(scopes):
        raise HTTPException(409, "独立运营权限范围已变化，请老板重新授权")
    required = {"pages_manage_posts"} if platform == "facebook" else {"instagram_basic", "instagram_content_publish"}
    if not required.issubset(set(granted)): raise HTTPException(409, "此独立运营授权未包含本平台发帖权限；只读权限不能用于整月运营")
    return binding


async def binding_data(db, ctx, customer, platform):
    try:
        b = await binding_for(db, ctx, customer, platform)
        return {"id": b.id, "revision": b.revision, "customer_id": b.customer_id, "customer_name": b.customer_name,
            "platform": b.platform, "title": b.asset_name, "asset_name": b.asset_name, "external_id": b.external_id, "page_id": b.page_id,
            "primary_operator_id": ctx.identity, "primary_operator_name": ctx.user.name or "老板", "owner_id": b.owner_id,
            "active": True, "operations_active": True, "lifecycle": "active", "connection_id": b.connection_id,
            "connection_revision": b.connection_revision, "credential_id": b.credential_id,
            "connection_active": True, "needs_reconnect": False, "configuration": ops._configuration()}
    except HTTPException as exc:
        if exc.status_code not in {403, 404, 409, 503}: raise
        return None


async def _context(db, user, run_id, *, write=False):
    ctx, customer = await base.context(db, user, run_id=run_id, write=write)
    await require_tables(db, ops.TABLES)
    run, workflow = await base._load(db, ctx, run_id)
    if monthly.run_platform(run) not in META: raise HTTPException(409, "此批次不是Meta月度内容")
    return ctx, customer, run, workflow


async def _rows(db, workflow):
    drafts = {}; schedules = {}
    if workflow:
        ids = [r["draft_id"] for r in workflow.task_refs]
        if ids: drafts = {r.id: r for r in (await db.scalars(select(Draft).where(Draft.id.in_(ids)).execution_options(populate_existing=True))).all()}
        ids = [r["schedule_id"] for r in workflow.schedule_refs]
        if ids: schedules = {r.id: r for r in (await db.scalars(select(Schedule).where(Schedule.id.in_(ids)).execution_options(populate_existing=True))).all()}
    return drafts, schedules


async def _started(db, workflow):
    if not workflow: return False
    ids = [r["draft_id"] for r in workflow.task_refs]
    return bool(ids and await db.scalar(select(Action.id).where(Action.draft_id.in_(ids)).limit(1)))


def _jpeg(body):
    from PIL import Image
    with Image.open(io.BytesIO(body)) as original:
        original.load(); rgb = original.convert("RGB")
        if max(rgb.size) > pixels.MAX_DIMENSION: raise HTTPException(422, "Meta图片最长边不能超过2048像素，请先准备合格固定图片")
        out = io.BytesIO(); rgb.save(out, "JPEG", quality=92, optimize=False, progressive=False, exif=b"", icc_profile=None)
        return pixels.canonical_jpeg(out.getvalue())


async def _private_image(db, ctx, customer, identity):
    source = await db.get(monthly.Image, identity, populate_existing=True)
    await images._valid_image(db, ctx, source, customer_id=customer.id, verify_bytes=True)
    body = await asyncio.to_thread(images._image_bytes, source)
    canonical, width, height = await asyncio.to_thread(_jpeg, body)
    sha = hashlib.sha256(canonical).hexdigest()
    old = await db.scalar(select(Media).where(Media.owner_id == ctx.identity, Media.customer_id == customer.id, Media.source_sha256 == source.image_sha256, Media.sha256 == sha).limit(1))
    if old:
        await asyncio.to_thread(pixels.read_image, old)
        return old
    identity = uuid4().hex
    signature = await asyncio.to_thread(pixels.write_image, identity, canonical)
    row = Media(id=identity, owner_id=ctx.identity, customer_id=customer.id, source_sha256=source.image_sha256, sha256=sha,
        width=width, height=height, byte_size=len(canonical), file_stat=signature, created_at=monthly.now())
    db.add(row); await db.flush(); return row


async def _media_fresh(db, ctx, customer, workflow):
    for item in workflow.snapshot["items"]:
        fixed = item.get("meta_media")
        row = await db.get(Media, fixed.get("id"), populate_existing=True) if fixed else None
        if not row or (row.owner_id, row.customer_id, row.source_sha256, row.sha256, row.width, row.height, row.byte_size) != (
            ctx.identity, customer.id, item["image_sha256"], fixed.get("sha256"), fixed.get("width"), fixed.get("height"), fixed.get("byte_size")):
            return False
        try: await asyncio.to_thread(pixels.read_image, row)
        except HTTPException: return False
    return True


async def _fresh(db, ctx, customer, run, workflow):
    return bool(workflow and await base._fresh(db, ctx, customer, run, workflow) and await _media_fresh(db, ctx, customer, workflow))


def _draft_matches(row, ref, item, workflow):
    return bool(row and row.owner_id == workflow.owner_id and row.binding_id == workflow.snapshot["binding"]["id"] and
        row.kind == "post" and row.status == "approved" and row.revision == ref["draft_revision"] and row.preview_hash == ref["preview_hash"] and
        (row.title, row.content, row.media_id) == (item["title"], item["content"], item["meta_media"]["id"]))


async def _view(db, ctx, customer, run, workflow):
    source, available, materials, binding = await base._sources(db, ctx, customer, run, workflow.snapshot["choices"] if workflow else None)
    stale = bool(workflow and (monthly.digest(source) != workflow.source_hash or not await _media_fresh(db, ctx, customer, workflow)))
    items = [dict(r) for r in workflow.snapshot["items"]] if workflow else available
    drafts, schedules = await _rows(db, workflow)
    drefs = {r["item_id"]: r for r in workflow.task_refs} if workflow else {}; srefs = {r["item_id"]: r for r in workflow.schedule_refs} if workflow else {}
    alerts = []
    def alert(key, status, title, message, item_id=None, schedule_id=None):
        r = {"key": f"monthly-meta:{run.id}:{key}", "run_id": run.id, "status": status, "level": "warning", "title": title, "message": message,
             "item_id": item_id, "task_id": None, "schedule_id": schedule_id, "action_id": None}
        r["version"] = monthly.digest(r); alerts.append(r)
    if stale and workflow and workflow.status != "cancelled": alert("source", "blocked", "本月内容或授权已变化", "请重新核对固定图片、菜单、文案和平台账号；旧排期不会继续提交")
    draft_ready = True
    for item in items:
        ref = drefs.get(item["item_id"]); row = drafts.get(ref["draft_id"]) if ref else None
        item["draft_id"] = row.id if row else None
        schedule = schedules.get(srefs.get(item["item_id"], {}).get("schedule_id"))
        item["schedule"] = ops.schedule_data(schedule) if schedule else None
        if ref and not _draft_matches(row, ref, item, workflow):
            draft_ready = False
            if workflow.status != "cancelled": alert("draft:" + str(ref["draft_id"]), "blocked", "原生草稿审核版本已变化", "请撤销旧整月确认后重新核对，不会按修改前的排期执行", item["item_id"])
        if schedule and schedule.status in EXCEPTIONS: alert(schedule.id, schedule.status, "Meta排期需要处理", schedule.message, item["item_id"], schedule.id)
        if srefs.get(item["item_id"]) and not schedule: alert("missing:" + str(item["item_id"]), "blocked", "原排期记录缺失", "请核对原记录，不会重新创建重复排期", item["item_id"])
        if monthly.run_platform(run) == "instagram" and item.get("meta_media"):
            image = item["meta_media"]
            if not 320 <= image["width"] <= 1440 or not 0.8 <= image["width"] / image["height"] <= 1.91:
                item["quality_warnings"] = list(dict.fromkeys([*item["quality_warnings"], "Instagram需320—1440像素宽、4:5至1.91:1的图片；系统不会静默裁剪或放大"]))
    warnings = any(r["quality_warnings"] for r in items)
    future = all(monthly.aware(monthly.datetime.fromisoformat(r["proposed_publish_at"])) > monthly.now() + timedelta(minutes=1) for r in items)
    expired = bool(workflow and monthly.aware(workflow.expires_at) <= monthly.now())
    native_ready = bool(binding and customer.status == "closed")
    config = scheduler.configuration()
    checks = [{"key": "materials", "state": "blocked" if warnings else "ready", "message": "请补齐合格配图及本批使用权" if warnings else "固定配图和实际JPEG均已核对"},
        {"key": "binding", "state": "ready" if native_ready else "blocked", "message": "本商家本平台已有明确独立运营授权" if native_ready else "须老板先为此商家此平台建立独立运营授权，不能继承只读连接"},
        {"key": "delivery", "state": "ready" if provider.execution_enabled() else "pending", "message": "公开执行已启用，仍需单独确认" if provider.execution_enabled() else "公开执行未启用；仅保存私有排期，不会发布"},
        {"key": "scheduler", "state": "ready" if config["enabled"] else "pending", "message": "定时服务已启用" if config["enabled"] else "定时服务未启用，旧待确认排期不会自动启用"},
        {"key": "source", "state": "blocked" if stale else "ready", "message": "资料或原生图片已变化，请重新准备" if stale else "菜单、文案、固定图片和平台账号版本一致"},
        {"key": "expiry", "state": "pending" if expired and workflow.status in {"prepared", "reviewed"} else "ready", "message": "预览已过期，请重新准备" if expired else "本次预览仍有效"},
        {"key": "dates", "state": "ready" if future else "blocked", "message": "建议日期均在未来" if future else "部分建议日期已过去，不会自动补发"}]
    counts = {"total": len(items), **{state: sum(r.status == state for r in schedules.values()) for state in ("prepared", "scheduled", "succeeded", "blocked", "unknown", "missed", "cancelled")}}
    return {"platform": monthly.run_platform(run), "run_id": run.id, "customer_id": customer.id, "month": run.month, "rules": run.snapshot["rules"], "run_revision": run.revision, "source_stale": stale,
        "workflow": ({"id": workflow.id, "revision": workflow.revision, "status": workflow.status, "preview_hash": workflow.preview_hash, "source_hash": workflow.source_hash,
            "expires_at": monthly.iso(workflow.expires_at), "reviewed_at": monthly.iso(workflow.reviewed_at), "created_at": monthly.iso(workflow.created_at), "updated_at": monthly.iso(workflow.updated_at)} if workflow else None),
        "items": items, "materials": materials, "binding": workflow.snapshot.get("binding") if workflow else binding, "current_binding": binding,
        "history_frozen": bool(workflow and await _started(db, workflow)), "delivery": {"enabled": provider.execution_enabled(), "can_manage": False, "notice": "仅在老板单独确认公开执行后，于指定时间由原生Meta发送器投递图片", "activated_at": None}, "scheduler": config,
        "checks": checks, "alerts": alerts, "counts": counts,
        "capabilities": {"is_owner": True, "can_prepare": bool(native_ready and (not workflow or workflow.status in {"prepared", "cancelled"}) and not await _started(db, workflow)),
            "can_review": bool(workflow and workflow.status == "prepared" and not warnings and not stale and not expired and native_ready),
            "can_schedule": bool(workflow and workflow.status == "reviewed" and draft_ready and not warnings and not stale and not expired and native_ready and future),
            "can_activate": bool(workflow and workflow.status == "schedule_prepared" and config["enabled"] and provider.execution_enabled() and draft_ready and not stale and native_ready and future),
            "can_cancel": bool(workflow and workflow.status != "cancelled")}}


async def get_workflow(db, user, run_id):
    ctx, customer, run, workflow = await _context(db, user, run_id)
    return await _view(db, ctx, customer, run, workflow)


async def receipt_current(db, ctx, request):
    run = await monthly._owned_run(db, ctx, request.run_id)
    workflow = await db.scalar(select(Workflow).where(Workflow.owner_id == ctx.identity, Workflow.run_id == run.id).execution_options(populate_existing=True))
    original = request.result.get("workflow") or {}
    if not workflow or (workflow.revision, workflow.preview_hash, workflow.status) != (original.get("revision"), original.get("preview_hash"), original.get("status")):
        raise HTTPException(409, "原操作已保存但当前批次已变化，请读取原流程，不要重做")
    _, customer = await monthly.context(db, ctx.user, run.customer_id)
    result = await _view(db, ctx, customer, run, workflow)
    if monthly.digest(result) != (request.result.get("request_receipt") or {}).get("result_hash"):
        raise HTTPException(409, "原操作已保存但来源或排期结果已变化，请读取原流程，不要重复创建")


async def _receipt(db, ctx, customer, run, workflow, request_id, kind, body):
    result = await _view(db, ctx, customer, run, workflow)
    result["request_receipt"] = {"request_id": request_id, "kind": kind, "workflow_revision": workflow.revision, "result_hash": monthly.digest(result)}
    db.add(Request(owner_id=ctx.identity, run_id=run.id, request_id=request_id, kind=kind, fingerprint=base._fingerprint(kind, run.id, body), result=result, created_at=monthly.now()))
    await db.flush(); return result


async def prepare(db, user, run_id, *, request_id, expected_run_revision, expected_workflow_revision, items, facts_confirmed):
    ctx, customer, run, workflow = await _context(db, user, run_id, write=True); request_id = media._key(request_id)
    body = {"expected_run_revision": expected_run_revision, "expected_workflow_revision": expected_workflow_revision, "items": items, "facts_confirmed": facts_confirmed}
    if facts_confirmed is not True or any(r.get("rights_confirmed") is not True for r in items): raise HTTPException(422, "请核对本月事实和全部实际配图使用权；这不是公开发布授权")
    async with media._write(db):
        ctx, customer, run, workflow = await _context(db, user, run_id, write=True)
        replay = await base._replay(db, ctx, request_id, "prepare", run_id, body)
        if replay is not None: return replay
        if run.revision != expected_run_revision or (workflow.revision if workflow else 0) != expected_workflow_revision: raise HTTPException(409, "月度草稿或准备版本已变化")
        if workflow and workflow.status not in {"prepared", "cancelled"}: raise HTTPException(409, "请先撤销旧整月确认再重新准备")
        if await _started(db, workflow): raise HTTPException(409, "此批次已有平台请求，不能重建或重复发送")
        await binding_for(db, ctx, customer, monthly.run_platform(run))
        source, packet, _, binding = await base._sources(db, ctx, customer, run, items)
        for item in packet:
            if item["image_version_id"] and not item["quality_warnings"]:
                image = await _private_image(db, ctx, customer, item["image_version_id"])
                item["meta_media"] = ops.media_data(image)
            else: item["meta_media"] = None
        if workflow is None:
            workflow = Workflow(owner_id=ctx.identity, customer_id=customer.id, run_id=run.id, revision=0, task_refs=[], schedule_refs=[], created_at=monthly.now()); db.add(workflow)
        workflow.revision += 1; workflow.status = "prepared"; workflow.source_hash = monthly.digest(source)
        workflow.snapshot = {"platform": monthly.run_platform(run), "source": source, "items": packet, "choices": items, "binding": binding}
        workflow.preview_hash = base._packet_hash(source, packet); workflow.reviewed_hash = None; workflow.reviewed_at = None; workflow.activation = None
        workflow.task_refs = []; workflow.schedule_refs = []; workflow.expires_at = monthly.now() + timedelta(hours=24); workflow.updated_at = monthly.now()
        await db.flush(); return await _receipt(db, ctx, customer, run, workflow, request_id, "prepare", body)


async def _confirmed(db, ctx, customer, run, workflow, revision, preview_hash, statuses):
    if not workflow or workflow.status not in statuses or workflow.revision != revision or workflow.preview_hash != preview_hash: raise HTTPException(409, "整月确认状态或版本已变化")
    if workflow.status in {"prepared", "reviewed"} and monthly.aware(workflow.expires_at) <= monthly.now(): raise HTTPException(409, "确认预览已过期，请重新准备")
    if not await _fresh(db, ctx, customer, run, workflow): raise HTTPException(409, "本月文案、素材、菜单、账号或独立运营授权已变化")
    view = await _view(db, ctx, customer, run, workflow)
    if any(r["quality_warnings"] or not r.get("meta_media") for r in view["items"]): raise HTTPException(409, "仍有不合格配图或使用权待确认")
    return await binding_for(db, ctx, customer, monthly.run_platform(run))


async def review(db, user, run_id, *, request_id, expected_revision, preview_hash, confirmed):
    request_id = media._key(request_id)
    body = {"expected_revision": expected_revision, "preview_hash": preview_hash, "confirmed": confirmed}
    if confirmed is not True: raise HTTPException(422, "请逐篇核对实际JPEG、文案和日期；仅确认内部审核，不公开发布")
    async with media._write(db):
        ctx, customer, run, workflow = await _context(db, user, run_id, write=True)
        replay = await base._replay(db, ctx, request_id, "review", run_id, body)
        if replay is not None: return replay
        binding = await _confirmed(db, ctx, customer, run, workflow, expected_revision, preview_hash, {"prepared"})
        other = await db.scalar(select(Workflow.id).join(Run, Run.id == Workflow.run_id).where(Workflow.owner_id == ctx.identity, Workflow.customer_id == customer.id,
            Run.month == run.month, monthly.platform_clause(monthly.run_platform(run)), Workflow.run_id != run.id, Workflow.status.in_(("reviewed", "schedule_prepared", "scheduled"))).limit(1))
        if other: raise HTTPException(409, "本客户此平台本月已有审核批次，请管理原批次")
        refs = []
        for item in workflow.snapshot["items"]:
            draft = Draft(owner_id=ctx.identity, binding_id=binding.id, kind="post", title=item["title"], content=item["content"], media_id=item["meta_media"]["id"],
                status="draft", revision=1, created_at=monthly.now(), updated_at=monthly.now())
            db.add(draft); await db.flush()
            snapshot, _, _ = await ops._snapshot(db, ctx, draft, binding, fresh_reply=False)
            draft.status = "approved"; draft.preview_hash = ops.digest(snapshot); draft.approved_snapshot = snapshot; draft.approved_at = monthly.now(); draft.revision += 1
            db.add(NativeRequest(owner_id=ctx.identity, request_id=base.key("meta-draft", ctx.identity, run.id, item["item_id"], workflow.revision), kind="monthly_draft", fingerprint=monthly.digest({"run_id": run.id, "workflow_id": workflow.id, "item_id": item["item_id"], "preview_hash": workflow.preview_hash}), result_id=str(draft.id), created_at=monthly.now()))
            refs.append({"item_id": item["item_id"], "draft_id": draft.id, "draft_revision": draft.revision, "preview_hash": draft.preview_hash})
        workflow.task_refs = refs; workflow.status = "reviewed"; workflow.reviewed_hash = workflow.preview_hash; workflow.reviewed_at = monthly.now()
        workflow.revision += 1; workflow.updated_at = monthly.now(); await db.flush()
        return await _receipt(db, ctx, customer, run, workflow, request_id, "review", body)


async def schedule(db, user, run_id, *, request_id, expected_revision, preview_hash, publication_confirmed, confirmation_version):
    request_id = media._key(request_id)
    body = {"expected_revision": expected_revision, "preview_hash": preview_hash, "publication_confirmed": publication_confirmed, "confirmation_version": confirmation_version}
    if type(publication_confirmed) is not bool or confirmation_version != base.PUBLIC_NOTICE_VERSION: raise HTTPException(422, "请明确此次仅保存私有排期还是单独确认公开执行")
    if publication_confirmed and (not scheduler.enabled() or not provider.execution_enabled()): raise HTTPException(409, "公开执行和定时服务尚未单独启用；不会静默启用或自动发布")
    if publication_confirmed:
        check_ctx, check_customer, check_run, _ = await _context(db, user, run_id, write=True)
        check_binding = await binding_for(db, check_ctx, check_customer, monthly.run_platform(check_run))
        frozen_binding = await binding_data(db, check_ctx, check_customer, monthly.run_platform(check_run))
        capability = await provider.capabilities(db, user, ops._provider_binding(check_binding))
        if not capability["can_publish"]: raise HTTPException(409, "平台当前未开放此门店的发帖权限，未启用任何排期")
    async with media._write(db):
        ctx, customer, run, workflow = await _context(db, user, run_id, write=True)
        replay = await base._replay(db, ctx, request_id, "schedule", run_id, body)
        if replay is not None: return replay
        binding = await _confirmed(db, ctx, customer, run, workflow, expected_revision, preview_hash, {"reviewed", "schedule_prepared"} if publication_confirmed else {"reviewed"})
        if publication_confirmed and await binding_data(db, ctx, customer, monthly.run_platform(run)) != frozen_binding: raise HTTPException(409, "刚核对的平台授权已变化，未启用任何排期")
        if workflow.reviewed_hash != workflow.preview_hash: raise HTTPException(409, "内部审核版本与排期版本不一致")
        drafts, old_schedules = await _rows(db, workflow); refs = {r["item_id"]: r for r in workflow.task_refs}; schedule_refs = []
        if set(refs) != {r["item_id"] for r in workflow.snapshot["items"]}: raise HTTPException(409, "整月原生草稿不完整")
        for item in workflow.snapshot["items"]:
            ref = refs[item["item_id"]]; draft = drafts.get(ref["draft_id"])
            if not _draft_matches(draft, ref, item, workflow): raise HTTPException(409, "原生草稿内容或审核版本已变化")
            draft, native_binding, snapshot = await ops._approved(db, ctx, draft.id, ref["draft_revision"], ref["preview_hash"])
            if native_binding.id != binding.id: raise HTTPException(409, "原生草稿所属平台已变化")
            at = ops._planned(item["proposed_publish_at"], item["timezone"])
            prior = next((r for r in workflow.schedule_refs if r["item_id"] == item["item_id"]), None)
            row = old_schedules.get(prior["schedule_id"]) if prior else None
            if row:
                if row.status != "prepared" or row.action_id or (row.owner_id, row.binding_id, row.draft_id, row.draft_revision, row.preview_hash, monthly.iso(row.planned_at), row.timezone) != (
                    ctx.identity, binding.id, draft.id, draft.revision, draft.preview_hash, item["proposed_publish_at"], item["timezone"]): raise HTTPException(409, "原私有排期已变化，不能批量启用")
                row.revision += 1
            else:
                if await db.scalar(select(Schedule.id).where(Schedule.draft_id == draft.id, Schedule.status.in_(ACTIVE)).limit(1)) or await db.scalar(select(Action.id).where(Action.draft_id == draft.id).limit(1)):
                    raise HTTPException(409, "原生草稿已有排期或平台请求，不会重复创建")
                image = await ops._image(db, ctx, binding, draft.media_id)
                row = Schedule(owner_id=ctx.identity, binding_id=binding.id, draft_id=draft.id, draft_revision=draft.revision, preview_hash=draft.preview_hash,
                    submitted_snapshot={**snapshot, "media": ops.media_data(image), "monthly": {"run_id": run.id, "workflow_id": workflow.id, "item_id": item["item_id"], "preview_hash": workflow.preview_hash, "platform": monthly.run_platform(run)}},
                    planned_at=at, timezone=item["timezone"], request_id=base.key("meta-schedule", ctx.identity, run.id, item["item_id"], workflow.revision), revision=1, created_at=monthly.now())
                db.add(row)
            row.status = "scheduled" if publication_confirmed else "prepared"; row.message = "老板已另行确认，将在指定日期按原生服务执行" if publication_confirmed else "整月私有排期已保存，等待老板单独确认公开执行；不会自动启用"
            row.updated_at = monthly.now(); await db.flush(); schedule_refs.append({**ref, "schedule_id": row.id})
        workflow.schedule_refs = schedule_refs; workflow.status = "scheduled" if publication_confirmed else "schedule_prepared"
        workflow.activation = {"armed": publication_confirmed, "confirmed_by": ctx.identity, "confirmed_at": monthly.iso(monthly.now()), "confirmation_version": base.PUBLIC_NOTICE_VERSION,
            "preview_hash": workflow.preview_hash, "binding_id": binding.id, "binding_revision": binding.revision, "platform": monthly.run_platform(run)}
        workflow.revision += 1; workflow.updated_at = monthly.now(); await db.flush()
        return await _receipt(db, ctx, customer, run, workflow, request_id, "schedule", body)


async def cancel(db, user, run_id, *, request_id, expected_revision, reason):
    request_id = media._key(request_id); reason = monthly._clean(reason, 200, required=True)
    if len(reason) < 3: raise HTTPException(422, "请填写至少3字的撤销原因")
    body = {"expected_revision": expected_revision, "reason": reason}
    async with media._write(db):
        ctx, customer, run, workflow = await _context(db, user, run_id)
        replay = await base._replay(db, ctx, request_id, "cancel", run_id, body)
        if replay is not None: return replay
        if not workflow or workflow.revision != expected_revision or workflow.status == "cancelled": raise HTTPException(409, "批次状态已变化")
        drafts, schedules = await _rows(db, workflow)
        for row in schedules.values():
            if row.action_id is None and row.status in {"prepared", "scheduled", "blocked", "missed"}:
                row.status = "cancelled"; row.revision += 1; row.message = reason; row.updated_at = monthly.now()
        workflow.status = "cancelled"; workflow.revision += 1; workflow.updated_at = monthly.now(); await db.flush()
        return await _receipt(db, ctx, customer, run, workflow, request_id, "cancel", body)


async def workspace_status(db, user, run_id):
    ctx, customer, run, workflow = await _context(db, user, run_id)
    if not workflow: return None
    view = await _view(db, ctx, customer, run, workflow)
    return {"revision": workflow.revision, "snapshot_hash": workflow.preview_hash, "status": workflow.status, "source_stale": view["source_stale"],
        "pending_owner_confirmation": workflow.status in {"prepared", "reviewed", "schedule_prepared"}, "requires_attention": bool(view["alerts"]), "exception_count": len(view["alerts"]),
        "task_ids": [], "draft_ids": [r["draft_id"] for r in workflow.task_refs], "schedule_ids": [r["schedule_id"] for r in workflow.schedule_refs], "alerts": view["alerts"],
        "message": "整月私有排期已保存，等待单独确认公开执行" if workflow.status == "schedule_prepared" else "逐篇核对整月文案、实际JPEG及平台账号；内部审核不会发布" if workflow.status in {"prepared", "reviewed"} else "原生排期结果保留，异常请核对原记录"}


async def alerts(db, user, customer_id, *, month=None, platform):
    ctx, customer = await base.context(db, user, customer_id=customer_id)
    query = select(Run.id).join(Workflow, Workflow.run_id == Run.id).where(Run.owner_id == ctx.identity, Run.customer_id == customer.id, monthly.platform_clause(platform))
    if month is not None: monthly.valid_month(month); query = query.where(Run.month == month)
    identity = await db.scalar(query.order_by(Run.id.desc()).limit(1))
    view = await get_workflow(db, user, identity) if identity else None
    rows = view["alerts"] if view else []
    return {"customer_id": customer.id, "platform": platform, "month": view["month"] if view else month, "run_id": identity, "items": rows,
        "counts": {"attention": len(rows), "total": len(rows), **{s: sum(r["status"] == s for r in rows) for s in ("blocked", "unknown", "missed", "failed")},
            "pending_confirmation": int(bool(view and view["workflow"]["status"] in {"prepared", "reviewed", "schedule_prepared"}))}}


async def guard_legacy(db, ctx, run_id, *, editing=False):
    workflow = await db.scalar(select(Workflow).where(Workflow.owner_id == ctx.identity, Workflow.run_id == run_id))
    if workflow and (not editing or workflow.status != "cancelled" or await _started(db, workflow)):
        raise HTTPException(409, "Meta批次已进入整月审核，请先撤销后修改；不可转为Google任务")


async def authorize_native(db, *, draft_id, schedule_id=None, action=None):
    """Fence all native send/continuation/activation paths, including direct UI."""
    if not await tables_available(db, base.TABLES): return
    draft = await db.get(Draft, draft_id, populate_existing=True)
    if draft is None: raise HTTPException(409, "原生草稿已不可读取")
    workflows = list((await db.scalars(select(Workflow).where(Workflow.owner_id == draft.owner_id).execution_options(populate_existing=True))).all())
    matches = [w for w in workflows if w.snapshot.get("platform") in META and any(r.get("draft_id") == draft_id for r in w.task_refs)]
    if not matches:
        if await db.scalar(select(NativeRequest.id).where(NativeRequest.owner_id == draft.owner_id, NativeRequest.kind == "monthly_draft", NativeRequest.result_id == str(draft_id)).limit(1)):
            raise HTTPException(409, "此草稿属于已撤销或替换的整月批次，不可单独公开发送")
        return
    if len(matches) != 1 or schedule_id is None: raise HTTPException(409, "此整月草稿只能按老板另行确认的原批次排期执行，不可直接或提前发布")
    workflow = matches[0]
    schedule = await db.get(Schedule, schedule_id, populate_existing=True)
    if not schedule or schedule.owner_id != workflow.owner_id or schedule.draft_id != draft_id or schedule.status not in {"scheduled", "dispatching"}:
        raise HTTPException(409, "此整月排期尚未确认或已经停止")
    actor = await db.get(Employees, workflow.owner_id, populate_existing=True)
    if not actor: raise HTTPException(409, "原确认老板身份已失效")
    user = SimpleNamespace(id=str(actor.id), role=actor.role, name=actor.name)
    ctx, customer, run, current = await _context(db, user, workflow.run_id)
    active = workflow.activation or {}
    if workflow.status != "scheduled" or active.get("armed") is not True or active.get("confirmation_version") != base.PUBLIC_NOTICE_VERSION or active.get("preview_hash") != workflow.preview_hash or workflow.reviewed_hash != workflow.preview_hash:
        raise HTTPException(409, "原整月公开确认不存在或已撤销")
    if not await _fresh(db, ctx, customer, run, workflow): raise HTTPException(409, "整月菜单、固定图片、文案或独立运营授权已变化")
    refs = [r for r in workflow.schedule_refs if r.get("schedule_id") == schedule.id and r.get("draft_id") == draft_id]
    if len(refs) != 1: raise HTTPException(409, "原生排期与整月归属不一致")
    ref = refs[0]; item = next((r for r in workflow.snapshot["items"] if r["item_id"] == ref["item_id"]), None)
    if not item or not _draft_matches(draft, ref, item, workflow) or (schedule.binding_id, schedule.draft_revision, schedule.preview_hash, monthly.iso(schedule.planned_at), schedule.timezone) != (
        active.get("binding_id"), ref["draft_revision"], ref["preview_hash"], item["proposed_publish_at"], item["timezone"]): raise HTTPException(409, "原生草稿、平台、图片或时间已变化")
    marker = (schedule.submitted_snapshot or {}).get("monthly") or {}
    if marker != {"run_id": run.id, "workflow_id": workflow.id, "item_id": item["item_id"], "preview_hash": workflow.preview_hash, "platform": monthly.run_platform(run)}: raise HTTPException(409, "原生排期的整月来源已变化")
    at = monthly.now()
    if not monthly.aware(schedule.planned_at) <= at <= monthly.aware(schedule.planned_at) + timedelta(minutes=5): raise HTTPException(409, "当前不在老板确认的执行窗口，不会提前或补发")
    if action is not None and (action.owner_id, action.binding_id, action.draft_id, action.draft_revision, action.preview_hash) != (
        workflow.owner_id, schedule.binding_id, draft_id, schedule.draft_revision, schedule.preview_hash): raise HTTPException(409, "原平台请求与整月排期不一致")
