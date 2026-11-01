"""One owner-reviewed month, native Google tasks/schedules, no alternate sender.

Preparation and internal review never create a delivery lease or provider action.
The distinct schedule confirmation is the only transition into the existing
Google queue. Original copy is retained when current fixed images are selected.
"""
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid5, NAMESPACE_URL
from fastapi import HTTPException
from sqlalchemy import select
from models.media_monthly_workflow import MediaMonthlyWorkflow as Workflow, MediaMonthlyWorkflowRequest as Request
from models.media_monthly import MediaMonthlyProfile as Profile, MediaMonthlyItem as Item, MediaMonthlyRun as Run
from models.media_operations import MediaOperationTask as Task
from models.media_publication_images import MediaPublicationImage as Image
from models.google_business import GoogleBusinessBinding as Binding, GoogleBusinessConnection as Connection, GoogleBusinessSchedule as Schedule, GoogleBusinessAction as Action
from models.employees import Employees
from services import media_monthly as monthly, media_operations as media, media_publication_images as images
from services import google_business as google, google_business_management as management, google_business_scheduler as scheduler
from services.schema_readiness import require_tables, tables_available

TABLES = {"media_monthly_workflows", "media_monthly_workflow_requests"}
PUBLIC_NOTICE_VERSION = "monthly-publication-v1"
TASK_PREFIX = "a24c2026-"
SCHEDULE_PREFIX = "b24c2026-"
LIVE = {"scheduled", "dispatching", "pending", "accepted", "unknown", "succeeded"}
EXCEPTIONS = {"blocked", "unknown", "missed", "failed", "rejected"}


def key(kind, owner, run, item, revision):
    value = str(uuid5(NAMESPACE_URL, f"t24-monthly-workflow:{kind}:{owner}:{run}:{item}:{revision}"))
    return (SCHEDULE_PREFIX if kind == "schedule" else TASK_PREFIX if kind == "task" else value[:9]) + value[9:]


async def context(db, user, *, customer_id=None, run_id=None, write=False):
    # Resolve the persisted run's customer before applying existing owner and
    # customer module rules. A caller-controlled default can never cross-bind.
    ctx, _ = await monthly.context(db, user, None)
    if run_id is not None:
        run = await monthly._owned_run(db, ctx, run_id)
        if customer_id is not None and customer_id != run.customer_id: raise HTTPException(404, "月度批次不存在")
        customer_id = run.customer_id
    ctx, customer = await monthly.context(db, user, customer_id, write=write)
    await require_tables(db, TABLES)
    return ctx, customer


async def _load(db, ctx, run_id, lock=False):
    run = await monthly._owned_run(db, ctx, run_id, lock=lock)
    if run.status != "generated": raise HTTPException(409, "本流程只接收尚未采用的月度草案；已有任务请管理原任务")
    query = select(Workflow).where(Workflow.owner_id == ctx.identity, Workflow.run_id == run.id).execution_options(populate_existing=True)
    if lock: query = query.with_for_update()
    return run, await db.scalar(query)


async def _binding(db, ctx, customer):
    rows = list((await db.execute(select(Binding, Connection).join(Connection, Binding.connection_id == Connection.id)
        .where(Binding.customer_id == customer.id, Connection.owner_id == ctx.identity).execution_options(populate_existing=True))).all())
    if len(rows) != 1: return None
    binding, connection = rows[0]
    return {"id": binding.id, "revision": binding.revision, "customer_id": binding.customer_id, "customer_name": binding.customer_name,
        "title": binding.title, "primary_operator_id": binding.primary_operator_id, "primary_operator_name": binding.primary_operator_name,
        "active": binding.active, "lifecycle": binding.lifecycle, "connection_id": connection.id, "connection_active": connection.active,
        "needs_reconnect": connection.needs_reconnect, "owner_id": connection.owner_id}


async def _sources(db, ctx, customer, run, choices=None):
    entries = list((await db.scalars(select(Item).where(Item.run_id == run.id).order_by(Item.slot_id).execution_options(populate_existing=True))).all())
    expected_slots = monthly.slots(run.month, run.snapshot["rules"])
    expected = {slot["slot_id"]: slot for slot in expected_slots}
    if (len(entries) != len(expected_slots) or {item.slot_id for item in entries} != set(expected)
        or any(item.task_id or monthly.iso(item.proposed_publish_at) != expected[item.slot_id]["proposed_publish_at"] or item.timezone != expected[item.slot_id]["timezone"] for item in entries)): raise HTTPException(409, "本月候选数量或原任务状态已变化，请核对原批次")
    menus, materials, versions = await monthly._sources(db, ctx, customer)
    material_map = {row["id"]: row for row in materials}; menu_map = {row["id"]: row for row in menus}
    selected = {row["item_id"]: row for row in choices} if choices else {}
    if choices is not None and (len(choices) != len(entries) or set(selected) != {item.id for item in entries}): raise HTTPException(422, "请逐一核对本月全部草案，不可遗漏或重复篇目")
    output = []; source_items = []
    for item in entries:
        choice = selected.get(item.id, {"image_version_id": item.image_version_id, "rights_confirmed": False})
        image = versions.get(choice.get("image_version_id")); material = material_map.get(image.material_id if image else item.material_id)
        material_row = await db.get(monthly.Material, material["id"], populate_existing=True) if material else None
        material_source = ({name: material[name] for name in ("id", "title", "linked_item_id", "approval_status", "copyright_status")} |
            {"source_fingerprint": images.source_fingerprint(material_row)}) if material_row else None
        warnings = monthly._quality(image)
        if image and image.rights_basis not in {"owned", "client_provided", "licensed"}: warnings.append("固定图片缺少有效使用权依据")
        if choice.get("rights_confirmed") is not True: warnings.append("请确认本批具体配图的使用权和内容归属")
        if not material: warnings.append("当前客户共享素材不可用")
        if material and material.get("linked_item_id") is not None and material["linked_item_id"] not in item.menu_item_ids:
            warnings.append("此图片已绑定其他菜品，不能用作本篇配图")
        chosen_menus = []
        for identity in item.menu_item_ids:
            menu = menu_map.get(identity)
            if not menu or menu["status"] != "active": warnings.append("对应菜单已停用或移除，请先核对文案")
            else: chosen_menus.append(menu)
        title, content = monthly._copy(item.title, item.content, run.snapshot["rules"])
        dto = {"item_id": item.id, "slot_id": item.slot_id, "title": title, "content": content, "owner_summary": item.owner_summary,
            "proposed_publish_at": monthly.iso(item.proposed_publish_at), "timezone": item.timezone, "revision": item.revision, "copy_hash": item.copy_hash,
            "material_id": image.material_id if image else item.material_id, "image_version_id": image.id if image else None,
            "image_sha256": image.image_sha256 if image else None, "publication_image": images.image_data(image, ctx, material_row) if image else None,
            "quality_warnings": list(dict.fromkeys(warnings)), "task_id": None, "schedule": None}
        output.append(dto)
        source_items.append({"item_id": item.id, "revision": item.revision, "copy_hash": item.copy_hash, "title": title, "content": content,
            "owner_summary": item.owner_summary, "at": dto["proposed_publish_at"], "timezone": item.timezone, "menu_items": chosen_menus,
            "material": material_source, "image": dto["publication_image"], "rights_confirmed": choice.get("rights_confirmed") is True})
    profile = await db.get(Profile, run.profile_id, populate_existing=True)
    binding = await _binding(db, ctx, customer)
    source = {"run_id": run.id, "run_revision": run.revision, "month": run.month, "customer_id": customer.id, "customer_status": customer.status,
        "profile": monthly.profile_data(profile), "items": source_items, "binding": binding}
    return source, output, materials, binding


def _packet_hash(source, items):
    return monthly.digest({"source": source, "items": items})


async def _fresh(db, ctx, customer, run, workflow):
    if not workflow: return False
    try:
        source, _, _, _ = await _sources(db, ctx, customer, run, workflow.snapshot["choices"])
        return monthly.digest(source) == workflow.source_hash
    except HTTPException: return False


async def _native_rows(db, workflow):
    tasks = {}; schedules = {}
    if workflow:
        tids = [row["task_id"] for row in workflow.task_refs]; sids = [row["schedule_id"] for row in workflow.schedule_refs]
        if tids: tasks = {row.id: row for row in (await db.scalars(select(Task).where(Task.id.in_(tids)).execution_options(populate_existing=True))).all()}
        if sids: schedules = {row.id: row for row in (await db.scalars(select(Schedule).where(Schedule.id.in_(sids)).execution_options(populate_existing=True))).all()}
    return tasks, schedules


async def _nonrebuildable(db, workflow, schedules=None):
    if not workflow: return False
    tids = [row["task_id"] for row in workflow.task_refs]
    if tids and await db.scalar(select(Task.id).where(Task.id.in_(tids), Task.status == "completed").limit(1)):
        return True
    if tids and await db.scalar(select(Action.id).where(Action.task_id.in_(tids),
        (Action.dispatch_started_at.is_not(None)) | (Action.status.in_(("pending", "unknown", "accepted", "succeeded")))).limit(1)):
        return True
    if schedules is None: _, schedules = await _native_rows(db, workflow)
    return any(row.status in {"dispatching", "unknown", "accepted", "succeeded"} for row in schedules.values())


def _task_matches(task, ref, item, workflow):
    return bool(task and task.status == "ready" and task.revision == ref["task_revision"] and
        (task.customer_id, task.platform, task.title, task.content, task.material_id, task.timezone, task.assignee_id) ==
        (workflow.customer_id, "google_business", item["title"], item["content"], item["material_id"], item["timezone"], workflow.snapshot["binding"]["primary_operator_id"]))


async def _alerts(db, workflow, stale, schedules, tasks):
    rows = []
    if not workflow: return rows
    def add(identity, status, title, message, item_id=None, task_id=None, schedule_id=None, action_id=None):
        value = {"key": f"monthly:{workflow.id}:{identity}", "run_id": workflow.run_id, "level": "error" if status in {"unknown", "failed", "rejected"} else "warning",
            "status": status, "title": title, "message": message, "item_id": item_id, "task_id": task_id, "schedule_id": schedule_id, "action_id": action_id}
        value["version"] = monthly.digest(value); rows.append(value)
    if stale and workflow.status in {"reviewed", "scheduled"}:
        add("source", "blocked", "本月内容来源已变化", "菜单、素材、文案、门店或负责人已变化，相关内容不会继续提交；请核对后重新准备")
    if workflow.status == "reviewed":
        for ref in workflow.task_refs:
            item = next((row for row in workflow.snapshot["items"] if row["item_id"] == ref["item_id"]), None)
            if not item or not _task_matches(tasks.get(ref["task_id"]), ref, item, workflow):
                add("task:" + str(ref["task_id"]), "blocked", "本月任务审核状态已变化", "请重新核对原任务内容与老板整月确认；不能直接建立排期", ref["item_id"], ref["task_id"])
    for ref in workflow.schedule_refs:
        row = schedules.get(ref["schedule_id"])
        if not row: add(ref["schedule_id"], "blocked", "排期记录需要核对", "原排期当前不可读取，不会另建重复任务", ref["item_id"], ref["task_id"], ref["schedule_id"]); continue
        action = await db.get(Action, row.action_id, populate_existing=True) if row.action_id else None
        status = action.status if action and action.status in EXCEPTIONS else row.status
        if row.status in {"scheduled", "dispatching"}:
            item = next((item for item in workflow.snapshot["items"] if item["item_id"] == ref["item_id"]), None)
            if not item or not _task_matches(tasks.get(ref["task_id"]), ref, item, workflow):
                add("task:" + str(ref["task_id"]), "blocked", "待发布任务已变化", "原任务或审核状态与整月确认不符，不会继续提交这条排期", ref["item_id"], ref["task_id"], row.id, row.action_id)
        if status in EXCEPTIONS:
            add(row.id, status, {"unknown": "发布结果待确认", "blocked": "发布条件未满足", "missed": "错过发布窗口", "failed": "发布失败", "rejected": "Google未批准发布"}[status],
                action.message if action and action.status in EXCEPTIONS else row.message, ref["item_id"], row.task_id, row.id, row.action_id)
    return rows


async def _view(db, ctx, customer, run, workflow):
    history_frozen = bool(workflow and await _nonrebuildable(db, workflow))
    use_packet = bool(workflow and (workflow.status != "cancelled" or history_frozen))
    source, current_items, materials, binding = await _sources(db, ctx, customer, run, workflow.snapshot["choices"] if use_packet else None)
    stale = bool(workflow and monthly.digest(source) != workflow.source_hash)
    items = [dict(item) for item in workflow.snapshot["items"]] if use_packet else current_items
    tasks, schedules = await _native_rows(db, workflow)
    trefs = {row["item_id"]: row for row in workflow.task_refs} if workflow else {}; srefs = {row["item_id"]: row for row in workflow.schedule_refs} if workflow else {}
    for item in items:
        item["task_id"] = trefs.get(item["item_id"], {}).get("task_id")
        scheduled = schedules.get(srefs.get(item["item_id"], {}).get("schedule_id"))
        item["schedule"] = management.schedule_data(scheduled) if scheduled else None
    delivery = await images.delivery_policy(db, ctx.user, customer.id); configuration = scheduler.configuration()
    warnings = any(item["quality_warnings"] for item in items)
    expired = bool(workflow and monthly.aware(workflow.expires_at) <= monthly.now())
    binding_ready = bool(customer.status == "closed" and binding and binding["active"] and binding["lifecycle"] == "active" and binding["connection_active"] and not binding["needs_reconnect"] and binding["primary_operator_id"])
    future = all(monthly.aware(monthly.datetime.fromisoformat(item["proposed_publish_at"])) > monthly.now() for item in items)
    checks = [{"key": "materials", "state": "blocked" if warnings else "ready", "message": "请补齐每篇合格配图及本批使用权确认" if warnings else "全部固定配图与本批使用权已核对"},
        {"key": "binding", "state": "ready" if binding_ready else "blocked", "message": "门店与现有主要运营已核对" if binding_ready else "请核对现有门店连接、合作状态和主要运营，不会自动分配权限"},
        {"key": "delivery", "state": "ready" if delivery["enabled"] else "pending", "message": "图片投递已启用" if delivery["enabled"] else "图片投递未启用；可先内部准备，真实发布前由老板另行确认"},
        {"key": "scheduler", "state": "ready" if configuration["enabled"] else "pending", "message": "定时服务已启用；只有明确确认的排期会执行" if configuration["enabled"] else "定时服务未启用"},
        {"key": "source", "state": "blocked" if stale else "ready", "message": "本批来源已变化，请重新准备；原文案会保留" if stale else "当前文案、菜单、图片及门店版本一致"},
        {"key": "expiry", "state": "pending" if expired and workflow.status != "scheduled" else "ready", "message": "确认预览已过期，请重新准备后核对" if expired and workflow.status != "scheduled" else "确认预览仍有效；正式排期后按已确认日期执行"},
        {"key": "dates", "state": "ready" if future else "blocked", "message": "建议日期均在未来" if future else "部分建议日期已过去，不会自动补发历史内容"}]
    task_ready = not workflow or workflow.status != "reviewed" or len(workflow.task_refs) == len(items) and all(
        _task_matches(tasks.get(ref["task_id"]), ref, next(item for item in workflow.snapshot["items"] if item["item_id"] == ref["item_id"]), workflow) for ref in workflow.task_refs)
    alert_rows = await _alerts(db, workflow, stale, schedules, tasks)
    counts = {"total": len(items), **{state: sum(row.status == state for row in schedules.values()) for state in ("scheduled", "succeeded", "blocked", "unknown", "missed", "cancelled")}}
    can_prepare = customer.status == "closed" and (not workflow or workflow.status in {"prepared", "cancelled"} and not await _nonrebuildable(db, workflow, schedules))
    return {"run_id": run.id, "customer_id": customer.id, "month": run.month, "rules": run.snapshot["rules"], "run_revision": run.revision, "source_stale": stale,
        "workflow": ({"id": workflow.id, "revision": workflow.revision, "status": workflow.status, "preview_hash": workflow.preview_hash,
            "source_hash": workflow.source_hash, "expires_at": monthly.iso(workflow.expires_at), "reviewed_at": monthly.iso(workflow.reviewed_at),
            "created_at": monthly.iso(workflow.created_at), "updated_at": monthly.iso(workflow.updated_at)} if workflow else None),
        "items": items, "materials": materials, "binding": workflow.snapshot["binding"] if workflow else binding,
        "current_binding": binding, "history_frozen": history_frozen,
        "delivery": delivery, "scheduler": configuration, "checks": checks, "alerts": alert_rows, "counts": counts,
        "capabilities": {"is_owner": True, "can_prepare": can_prepare, "can_review": bool(workflow and workflow.status == "prepared" and not warnings and not stale and not expired and binding_ready),
            "can_schedule": bool(workflow and workflow.status == "reviewed" and task_ready and not warnings and not stale and not expired and binding_ready and delivery["enabled"] and configuration["enabled"] and future),
            "can_cancel": bool(workflow and workflow.status != "cancelled")}}


async def get_workflow(db, user, run_id):
    ctx, customer = await context(db, user, run_id=run_id); run, workflow = await _load(db, ctx, run_id)
    return await _view(db, ctx, customer, run, workflow)


def _fingerprint(kind, run_id, body): return monthly.digest({"kind": kind, "run_id": run_id, "body": body})


async def _replay(db, ctx, request_id, kind, run_id, body):
    identity = media._key(request_id)
    row = await db.scalar(select(Request).where(Request.owner_id == ctx.identity, Request.request_id == identity))
    if row:
        if row.run_id != run_id or row.kind != kind or row.fingerprint != _fingerprint(kind, run_id, body): raise HTTPException(409, "此请求编号对应不同月度操作，请读取原结果")
        await _receipt_current(db, ctx, row)
        return row.result
    if await db.scalar(select(Run.id).where(Run.owner_id == ctx.identity, (Run.request_id == identity) | (Run.adopt_request_id == identity)).limit(1)):
        raise HTTPException(409, "此请求编号已用于其他月度操作，请读取原结果")
    return None


async def _receipt_current(db, ctx, request):
    workflow = await db.scalar(select(Workflow).where(Workflow.owner_id == ctx.identity, Workflow.run_id == request.run_id).execution_options(populate_existing=True))
    original = request.result.get("workflow") or {}
    if not workflow or (workflow.revision, workflow.preview_hash, workflow.status) != (original.get("revision"), original.get("preview_hash"), original.get("status")):
        raise HTTPException(409, "原操作已保存，但当前批次已变化；请重新读取当前流程，不要重做")
    run = await monthly._owned_run(db, ctx, request.run_id)
    customer, _ = await media._customer(db, ctx, workflow.customer_id)
    current = await _view(db, ctx, customer, run, workflow)
    if monthly.digest(current) != (request.result.get("request_receipt") or {}).get("result_hash"):
        raise HTTPException(409, "原操作已保存，但当前来源、排期结果或确认时间已变化；请重新读取当前流程，不要重做")


async def _receipt(db, ctx, customer, run, workflow, request_id, kind, body):
    result = await _view(db, ctx, customer, run, workflow)
    result["request_receipt"] = {"request_id": request_id, "kind": kind, "workflow_revision": workflow.revision, "result_hash": monthly.digest(result)}
    db.add(Request(owner_id=ctx.identity, run_id=run.id, request_id=request_id, kind=kind, fingerprint=_fingerprint(kind, run.id, body), result=result, created_at=monthly.now()))
    await db.flush(); return result


async def prepare(db, user, run_id, *, request_id, expected_run_revision, expected_workflow_revision, items, facts_confirmed):
    ctx, customer = await context(db, user, run_id=run_id, write=True); request_id = media._key(request_id)
    body = {"expected_run_revision": expected_run_revision, "expected_workflow_revision": expected_workflow_revision, "items": items, "facts_confirmed": facts_confirmed}
    if facts_confirmed is not True or any(row.get("rights_confirmed") is not True for row in items): raise HTTPException(422, "请核对本月事实、全部具体配图与使用权；本步骤不代表公开发布授权")
    async with media._write(db):
        ctx, customer = await context(db, user, run_id=run_id, write=True)
        replay = await _replay(db, ctx, request_id, "prepare", run_id, body)
        if replay is not None: return replay
        run, workflow = await _load(db, ctx, run_id, True)
        if run.revision != expected_run_revision or (workflow.revision if workflow else 0) != expected_workflow_revision: raise HTTPException(409, "月度草稿或准备版本已变化，请重新读取")
        if workflow and workflow.status not in {"prepared", "cancelled"}: raise HTTPException(409, "请先撤销本批内部审核或停止尚未提交的排期，再重新准备")
        source, packet_items, _, binding = await _sources(db, ctx, customer, run, items)
        if await _nonrebuildable(db, workflow):
            raise HTTPException(409, "本批已有公开提交或结果待确认记录，不能重新建立整月任务；请核对剩余排期")
        if workflow is None:
            workflow = Workflow(owner_id=ctx.identity, customer_id=customer.id, run_id=run.id, revision=0, task_refs=[], schedule_refs=[], created_at=monthly.now()); db.add(workflow)
        workflow.revision += 1; workflow.status = "prepared"; workflow.source_hash = monthly.digest(source)
        workflow.snapshot = {"source": source, "items": packet_items, "choices": items, "binding": binding}
        workflow.preview_hash = _packet_hash(source, packet_items); workflow.reviewed_hash = None; workflow.reviewed_at = None; workflow.activation = None
        workflow.schedule_refs = []; workflow.expires_at = monthly.now() + timedelta(hours=24); workflow.updated_at = monthly.now()
        await db.flush(); return await _receipt(db, ctx, customer, run, workflow, request_id, "prepare", body)


async def _confirmed(db, ctx, customer, run, workflow, expected_revision, preview_hash, status):
    if not workflow or workflow.revision != expected_revision or workflow.status != status or workflow.preview_hash != preview_hash:
        raise HTTPException(409, "整月确认版本或状态已变化，请重新读取具体整月内容")
    if monthly.aware(workflow.expires_at) <= monthly.now(): raise HTTPException(409, "确认预览已过期，请重新准备；原文案会保留")
    if not await _fresh(db, ctx, customer, run, workflow): raise HTTPException(409, "文案、素材、菜单、门店或负责人已变化，请撤销旧确认后重新准备")
    if any(item["quality_warnings"] or not item["image_version_id"] for item in workflow.snapshot["items"]): raise HTTPException(409, "本批仍有素材或图片使用权问题，请先补齐")
    binding_info = workflow.snapshot["binding"]
    if not binding_info or not binding_info["primary_operator_id"]: raise HTTPException(409, "当前门店主要运营未确认，不会自动授予权限")
    binding, _, _ = await google._binding(db, ctx, binding_info["id"], action="publish", lock=True)
    await media._assignee(db, ctx, customer, binding.primary_operator_id)
    return binding


async def review(db, user, run_id, *, request_id, expected_revision, preview_hash, confirmed):
    ctx, customer = await context(db, user, run_id=run_id, write=True); request_id = media._key(request_id)
    body = {"expected_revision": expected_revision, "preview_hash": preview_hash, "confirmed": confirmed}
    if confirmed is not True: raise HTTPException(422, "请逐篇核对具体文字、图片和日期，仅确认内部审核；本步骤不公开发布")
    async with media._write(db):
        ctx, customer = await context(db, user, run_id=run_id, write=True)
        replay = await _replay(db, ctx, request_id, "review", run_id, body)
        if replay is not None: return replay
        run, workflow = await _load(db, ctx, run_id, True)
        binding = await _confirmed(db, ctx, customer, run, workflow, expected_revision, preview_hash, "prepared")
        other = await db.scalar(select(Workflow.id).join(Run, Run.id == Workflow.run_id).where(Workflow.customer_id == customer.id, Run.month == run.month, Workflow.run_id != run.id, Workflow.status.in_(("reviewed", "scheduled"))).limit(1))
        if other: raise HTTPException(409, "此客户已有整月审核批次，请管理原批次，避免重复发布")
        old_refs = {row["item_id"]: row for row in workflow.task_refs}; task_refs = []
        for item in workflow.snapshot["items"]:
            material = await media._material(db, ctx, customer, item["material_id"])
            assignee_id, assignee_name = await media._assignee(db, ctx, customer, binding.primary_operator_id)
            fields = {"title": item["title"], "content": item["content"], "platform": "google_business", "timezone": item["timezone"],
                "due_at": monthly.iso(monthly.datetime.fromisoformat(item["proposed_publish_at"]) - timedelta(days=1))}
            prior = old_refs.get(item["item_id"])
            task = await db.get(Task, prior["task_id"], populate_existing=True) if prior else None
            if task is None:
                task_key = key("task", ctx.identity, run.id, item["item_id"], workflow.id)
                if await db.scalar(select(Task.id).where(Task.created_by_id == ctx.identity, Task.client_request_id == task_key)): raise HTTPException(409, "原月度任务已存在，请先核对原结果")
                task = Task(customer_id=customer.id, customer_name=customer.business_name, material_id=material.id, material_title=material.title,
                    created_by_id=ctx.identity, assignee_id=assignee_id, assignee_name=assignee_name, client_request_id=task_key,
                    creation_fingerprint=monthly.digest({"workflow_id": workflow.id, "item_id": item["item_id"]}), status="draft", revision=1,
                    created_at=monthly.now(), updated_at=monthly.now(), **media._validate_content_fields(fields))
                db.add(task); await db.flush(); await media._save_publication(db, task, media.DEFAULT_PUBLICATION)
                await images.save_selection(db, ctx, task, item["image_version_id"]); await media._event(db, ctx, task, "create", None)
            else:
                if task.customer_id != customer.id or task.created_by_id != ctx.identity or not task.client_request_id.startswith(TASK_PREFIX): raise HTTPException(409, "原月度任务归属需要核对")
                if task.status == "ready":
                    await media.transition_task_locked(db, ctx, task.id, expected_revision=task.revision,
                        request_id=key("return-before-review", ctx.identity, run.id, item["item_id"], workflow.revision), action="return", note="重新准备已撤回的原月度清单")
                    await db.refresh(task)
                await media.edit_task_locked(db, ctx, task.id, expected_revision=task.revision, material_id=material.id,
                    assignee_id=assignee_id, image_version_id=item["image_version_id"], publication=media.DEFAULT_PUBLICATION, **fields)
                await db.refresh(task)
            await media.transition_task_locked(db, ctx, task.id, expected_revision=task.revision,
                request_id=key("submit", ctx.identity, run.id, item["item_id"], workflow.revision), action="submit")
            await db.refresh(task)
            await media.transition_task_locked(db, ctx, task.id, expected_revision=task.revision,
                request_id=key("approve", ctx.identity, run.id, item["item_id"], workflow.revision), action="approve", note="老板逐篇核对整月固定内容；未授权公开发布")
            await db.refresh(task); task_refs.append({"item_id": item["item_id"], "task_id": task.id, "task_revision": task.revision})
        workflow.task_refs = task_refs; workflow.status = "reviewed"; workflow.reviewed_hash = workflow.preview_hash; workflow.reviewed_at = monthly.now()
        workflow.revision += 1; workflow.updated_at = monthly.now(); await db.flush()
        return await _receipt(db, ctx, customer, run, workflow, request_id, "review", body)


async def schedule(db, user, run_id, *, request_id, expected_revision, preview_hash, publication_confirmed, confirmation_version):
    ctx, customer = await context(db, user, run_id=run_id, write=True); request_id = media._key(request_id)
    body = {"expected_revision": expected_revision, "preview_hash": preview_hash, "publication_confirmed": publication_confirmed, "confirmation_version": confirmation_version}
    if publication_confirmed is not True or confirmation_version != PUBLIC_NOTICE_VERSION: raise HTTPException(422, "请另行确认本月具体文字、实际配图、门店与日期，将在到期时公开发布")
    async with media._write(db):
        ctx, customer = await context(db, user, run_id=run_id, write=True)
        replay = await _replay(db, ctx, request_id, "schedule", run_id, body)
        if replay is not None: return replay
        run, workflow = await _load(db, ctx, run_id, True)
        binding = await _confirmed(db, ctx, customer, run, workflow, expected_revision, preview_hash, "reviewed")
        if workflow.reviewed_hash != workflow.preview_hash: raise HTTPException(409, "内部审核版本与本次公开确认不一致")
        delivery = await images.delivery_policy(db, user, customer.id)
        if not delivery["enabled"] or not scheduler.enabled(): raise HTTPException(409, "请先由老板单独确认图片投递和现有定时服务，不会在本步骤自动启用")
        refs = {row["item_id"]: row for row in workflow.task_refs}
        if set(refs) != {item["item_id"] for item in workflow.snapshot["items"]}: raise HTTPException(409, "内部审核任务不完整，未建立任何排期")
        schedule_refs = []
        for item in workflow.snapshot["items"]:
            ref = refs[item["item_id"]]
            result = await management.schedule_locked(db, ctx, binding.id, request_id=key("schedule", ctx.identity, run.id, item["item_id"], workflow.revision),
                task_id=ref["task_id"], expected_revision=ref["task_revision"], planned_at=item["proposed_publish_at"], timezone=item["timezone"], _monthly=True)
            schedule_refs.append({"item_id": item["item_id"], "task_id": ref["task_id"], "task_revision": ref["task_revision"], "schedule_id": result["id"]})
        workflow.schedule_refs = schedule_refs; workflow.activation = {"confirmed_by": ctx.identity, "confirmed_at": monthly.iso(monthly.now()),
            "confirmation_version": PUBLIC_NOTICE_VERSION, "preview_hash": preview_hash, "binding_id": binding.id, "binding_revision": binding.revision,
            "operator_id": binding.primary_operator_id, "delivery": {"enabled": delivery["enabled"], "activated_at": delivery.get("activated_at")}}
        workflow.status = "scheduled"; workflow.revision += 1; workflow.updated_at = monthly.now(); await db.flush()
        return await _receipt(db, ctx, customer, run, workflow, request_id, "schedule", body)


async def cancel(db, user, run_id, *, request_id, expected_revision, reason):
    ctx, customer = await context(db, user, run_id=run_id); request_id = media._key(request_id)
    reason = monthly._clean(reason, 200, required=True)
    if len(reason) < 3: raise HTTPException(422, "请填写至少3字的撤销原因")
    body = {"expected_revision": expected_revision, "reason": reason}
    async with media._write(db):
        ctx, customer = await context(db, user, run_id=run_id)
        replay = await _replay(db, ctx, request_id, "cancel", run_id, body)
        if replay is not None: return replay
        run, workflow = await _load(db, ctx, run_id, True)
        if not workflow or workflow.revision != expected_revision or workflow.status == "cancelled": raise HTTPException(409, "批次状态已变化，请重新读取")
        tasks, schedules = await _native_rows(db, workflow)
        for row in schedules.values():
            if row.status in {"scheduled", "blocked", "missed"} and row.action_id is None:
                await management.cancel_schedule_locked(db, ctx, row.id, row.revision, _allow_stopped=True)
        for task in tasks.values():
            live = await db.scalar(select(Action.id).where(Action.task_id == task.id, Action.kind == "post_publish", Action.status.in_(("pending", "unknown", "accepted", "succeeded"))).limit(1))
            if task.status == "ready" and not live:
                await media.transition_task_locked(db, ctx, task.id, expected_revision=task.revision,
                    request_id=key("return", ctx.identity, run.id, task.id, workflow.revision), action="return", note=reason)
        workflow.status = "cancelled"; workflow.revision += 1; workflow.updated_at = monthly.now(); await db.flush()
        return await _receipt(db, ctx, customer, run, workflow, request_id, "cancel", body)


async def request_result(db, user, request_id):
    ctx, _ = await context(db, user); identity = media._key(request_id)
    row = await db.scalar(select(Request).where(Request.owner_id == ctx.identity, Request.request_id == identity))
    if not row: raise HTTPException(404, "原月度操作尚未登记，请保留原请求编号，不要另建一批")
    await monthly._owned_run(db, ctx, row.run_id)
    await _receipt_current(db, ctx, row)
    return row.result


async def workspace_status(db, user, run_id):
    if monthly.normalized_role(user) != "super_admin": raise HTTPException(403, "月度流程仅老板可查看")
    if not await tables_available(db, TABLES): return None
    ctx, customer = await context(db, user, run_id=run_id); run, workflow = await _load(db, ctx, run_id)
    if not workflow: return None
    view = await _view(db, ctx, customer, run, workflow)
    pending = workflow.status in {"prepared", "reviewed"}
    return {"revision": workflow.revision, "snapshot_hash": workflow.preview_hash, "status": workflow.status, "source_stale": view["source_stale"],
        "pending_owner_confirmation": pending, "requires_attention": bool(view["alerts"]), "exception_count": len(view["alerts"]),
        "task_ids": [row["task_id"] for row in workflow.task_refs], "schedule_ids": [row["schedule_id"] for row in workflow.schedule_refs],
        "alerts": view["alerts"], "message": "已停止尚未提交的本批任务；已提交的结果仍需核对" if workflow.status == "cancelled" else
        "已内部审核，等待老板单独确认公开排期" if workflow.status == "reviewed" else "月度素材和内容已准备，等待老板逐篇确认" if pending else "仅按老板明确确认的日期执行，异常会单独列出"}


async def alerts(db, user, customer_id=monthly.PILOT_CUSTOMER_ID, *, month=None):
    ctx, customer = await context(db, user, customer_id=customer_id)
    query = select(Workflow).where(Workflow.owner_id == ctx.identity, Workflow.customer_id == customer.id)
    if month is not None:
        monthly.valid_month(month); query = query.join(Run, Run.id == Workflow.run_id).where(Run.month == month, Run.customer_id == customer.id, Run.owner_id == ctx.identity)
    workflow = await db.scalar(query.order_by(Workflow.id.desc()).limit(1))
    if not workflow: return {"customer_id": customer.id, "month": month, "run_id": None, "items": [], "counts": {"attention": 0, "total": 0, "blocked": 0, "unknown": 0, "missed": 0, "failed": 0, "pending_confirmation": 0}}
    run, workflow = await _load(db, ctx, workflow.run_id); view = await _view(db, ctx, customer, run, workflow)
    rows = view["alerts"]
    return {"customer_id": customer.id, "month": run.month, "run_id": run.id, "items": rows,
        "counts": {"attention": len(rows), "total": len(rows), **{state: sum(row["status"] == state or state == "failed" and row["status"] == "rejected" for row in rows) for state in ("blocked", "unknown", "missed", "failed")},
            "pending_confirmation": int(workflow.status in {"prepared", "reviewed"})}}


async def guard_legacy(db, ctx, run_id, *, editing=False):
    if not await tables_available(db, TABLES): return
    workflow = await db.scalar(select(Workflow).where(Workflow.owner_id == ctx.identity, Workflow.run_id == run_id))
    if workflow and (not editing or workflow.status in {"reviewed", "scheduled"} or await _nonrebuildable(db, workflow)):
        raise HTTPException(409, "本月已进入整月审核流程，请先在月度流程撤销确认，再修改或重新准备；不要重复采用旧任务入口")


async def authorize_schedule(db, *, schedule, task=None):
    """Fail closed only for reserved monthly lineage; ordinary jobs are unchanged."""
    marked = bool(schedule and str(schedule.request_id).startswith(SCHEDULE_PREFIX)) or bool(task and str(task.client_request_id).startswith(TASK_PREFIX))
    if not marked: return
    if not await tables_available(db, TABLES): raise HTTPException(409, "月度确认资料尚未就绪，本次不会公开提交")
    if schedule is None: raise HTTPException(409, "此月度任务只能按老板确认的具体排期执行，不允许提前或另建发布请求")
    if schedule.status not in {"scheduled", "dispatching"}: raise HTTPException(409, "此月度排期已停止或结果待核对，不会重新发送")
    if task is None: task = await db.get(Task, schedule.task_id, populate_existing=True)
    if task is None: raise HTTPException(409, "月度任务已不可核对，不会发布")
    workflow = None
    rows = list((await db.scalars(select(Workflow).where(Workflow.customer_id == task.customer_id, Workflow.status.in_(("scheduled", "cancelled"))).with_for_update().execution_options(populate_existing=True))).all())
    for candidate in rows:
        if any(ref["schedule_id"] == schedule.id for ref in candidate.schedule_refs): workflow = candidate; break
    if not workflow or workflow.status != "scheduled" or not workflow.activation or workflow.activation.get("confirmation_version") != PUBLIC_NOTICE_VERSION:
        raise HTTPException(409, "原整月公开确认已撤销或不存在，本次不会发布")
    actor = await db.get(Employees, workflow.owner_id, populate_existing=True)
    user = SimpleNamespace(id=str(actor.id), role=actor.role, name=actor.name) if actor else None
    if not user: raise HTTPException(409, "原确认老板身份已失效")
    ctx, customer = await context(db, user, run_id=workflow.run_id); run, current = await _load(db, ctx, workflow.run_id, True)
    if not await _fresh(db, ctx, customer, run, current): raise HTTPException(409, "月度文案、图片、门店或负责人已变化，停止原排期")
    if current.reviewed_hash != current.preview_hash or current.activation.get("preview_hash") != current.preview_hash:
        raise HTTPException(409, "月度公开确认与审核版本不一致")
    refs = [ref for ref in current.schedule_refs if ref["schedule_id"] == schedule.id]
    if len(refs) != 1: raise HTTPException(409, "排期与月度确认不一致")
    ref = refs[0]; item = next((row for row in current.snapshot["items"] if row["item_id"] == ref["item_id"]), None)
    if not item or (schedule.task_id, schedule.task_revision, schedule.binding_id, schedule.operator_id, monthly.iso(schedule.planned_at), schedule.timezone) != (
        ref["task_id"], ref["task_revision"], current.activation["binding_id"], current.activation["operator_id"], item["proposed_publish_at"], item["timezone"]):
        raise HTTPException(409, "排期内容、门店、负责人或时间与老板确认不一致")
    at = monthly.now()
    if not monthly.aware(schedule.planned_at) <= at <= monthly.aware(schedule.planned_at) + timedelta(minutes=5): raise HTTPException(409, "当前不在老板确认的发布窗口内，不会提前或补发")
    policy = await images.delivery_policy(db, user, customer.id)
    if {"enabled": policy["enabled"], "activated_at": policy.get("activated_at")} != current.activation["delivery"] or not policy["enabled"]:
        raise HTTPException(409, "图片投递设置已变化，请老板重新核对")
