"""Read-only preparation checks; never grant access, reserve or send a post.

This view deliberately does not replace the dispatch guards. It describes the
current database state so an operator can prepare content and the owner can
review it before separately confirming any public operation.
"""
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

from models.customers import Customers
from models.employees import Employees
from models.google_business import GoogleBusinessAction as Action, GoogleBusinessSchedule as Schedule
from models.media_operations import MediaOperationEvent
from services import google_business as g
from services import google_business_management as management
from services import google_business_scheduler as scheduler
from services import media_publication_images as images


def check(key, label, status, message):
    return {"key": key, "label": label, "status": status, "message": message}


async def _approved_content(db, ctx, binding, task):
    """Mirror the immutable-content checks without row locks or delivery URLs."""
    if not task.content.strip() or len(task.content.strip()) > 1500:
        raise HTTPException(422, "Google 帖子正文需要为 1—1500 字，请修改草稿后重新审核")
    approval = await db.scalar(select(MediaOperationEvent).where(
        MediaOperationEvent.task_id == task.id, MediaOperationEvent.action == "approve",
        MediaOperationEvent.after_status == "ready").order_by(MediaOperationEvent.revision.desc()).limit(1))
    snapshot = approval.snapshot if approval and isinstance(approval.snapshot, dict) else {}
    if not approval or snapshot.get("content") != task.content or snapshot.get("material_id") != task.material_id:
        raise HTTPException(422, "当前正文或素材尚未获得老板审核，请提交或退回后重新审核")
    publication = await g.media.publication_for_task(db, task)
    if "publication" in snapshot:
        if snapshot["publication"] != publication or snapshot.get("timezone") != task.timezone:
            raise HTTPException(422, "发布类型、活动时间、链接或商家时区已变化，请重新审核")
    elif publication != g.media.DEFAULT_PUBLICATION:
        raise HTTPException(422, "当前发布配置尚未审核，请重新审核")
    # Validate event/offer local-time conversion using the same pure transform.
    g.media.publication_payload(publication, task.timezone)
    prepared = await images.approved_image(db, ctx, binding, task, snapshot)
    if prepared is None and task.material_id is not None:
        customer = await db.get(Customers, task.customer_id)
        material = await g.media._material(db, ctx, customer, task.material_id, proof=True)
        await db.refresh(material)
        fingerprint = g.media._hash({"id": material.id, "customer_id": material.customer_id,
            "file_url": material.file_url, "content_type": material.content_type,
            "updated_at": g.media._iso(material.updated_at)})
        if not snapshot.get("google_material_fingerprint") or snapshot["google_material_fingerprint"] != fingerprint:
            raise HTTPException(422, "图片引用未经过当前版本审核或已变化，请重新审核")
        if not g.provider.public_image_url(material.file_url):
            raise HTTPException(422, "请先准备固定发布图片；私人附件不能直接公开发布")


async def readiness(db, user, binding_id, task_id=None):
    ctx = await g.context(db, user)
    binding, connection, permissions = await g._binding(db, ctx, binding_id)
    binding_snapshot = g.binding_data(binding, permissions)
    customer, _ = await g.media._customer(db, ctx, binding.customer_id)
    checks = []
    _, missing_configuration = g.provider.settings()
    configured = not missing_configuration
    checks.append(check("configuration", "发布服务配置", "passed" if configured else "blocked",
        "Google 发布服务已配置" if configured else "Google 发布服务配置或 API 接入审批尚未完成，请老板核对"))
    cooperating = bool(binding.lifecycle == "active" and customer.status == "closed")
    checks.append(check("merchant", "合作与门店", "passed" if cooperating else "blocked",
        "客户正在合作，Google 门店正在运营" if cooperating else "客户或门店当前已暂停、停止或不在合作状态"))
    connected = bool(connection.active and not connection.needs_reconnect and connection.token_encrypted)
    checks.append(check("connection", "Google 连接", "passed" if connected else "blocked",
        "已保存 Google 授权；实际连接状态以平台读取结果为准" if connected else "请老板重新连接 Google 商家账号"))
    checks.append(check("publish_permission", "当前账号操作范围", "passed" if permissions["can_publish"] else "blocked",
        "可在审核后另行确认发布" if permissions["can_publish"] else "当前账号尚不具备此门店的 Google 发布权限"))
    operator_valid = False
    if binding.primary_operator_id:
        operator = await db.get(Employees, binding.primary_operator_id, populate_existing=True)
        if operator:
            try:
                operator_user = SimpleNamespace(id=str(operator.id), name=operator.name, role=operator.role)
                operator_ctx = await g.context(db, operator_user)
                await g._binding(db, operator_ctx, binding.id, action="publish")
                operator_valid = True
            except HTTPException:
                pass
    checks.append(check("operator", "主要运营", "passed" if operator_valid else "pending",
        "主运营具备当前门店的运营协作和 Google 发布权限" if operator_valid else
        "请老板选择具备现有客户协作与 Google 发布权限的主运营；此检查不会自动授权"))
    policy = await images.delivery_policy(db, user, binding.customer_id)
    checks.append(check("image_delivery", "图片投递范围", "passed" if policy["enabled"] else "pending",
        "当前投递设置已启用，作用于老板账号；仅已审核任务实际提交时开放发布副本" if policy["enabled"] else
        "图片投递尚未启用，仍可先准备、预览和审核；不影响纯文字任务"))
    configuration = scheduler.configuration()
    checks.append(check("scheduler", "定时发布服务", "passed" if configuration["enabled"] else "pending",
        "定时服务已启用；必须另外确认具体任务排期才会执行" if configuration["enabled"] else
        "定时服务尚未启用；任务截止时间不等于自动发布排期"))
    task_data = None
    action_data = None
    schedule_data = None
    can_publish = False
    can_schedule = False
    if task_id is None:
        checks.append(check("task", "内容与老板审核", "pending", "先准备任务、图片和文案，再提交老板审核；本清单不会发布内容"))
    else:
        task, _, _ = await g.media._get_task(db, ctx, task_id)
        if task.customer_id != binding.customer_id or task.platform != "google_business":
            raise HTTPException(404, "Google 运营任务不存在或不属于此门店")
        task_data = {key: getattr(task, key) for key in ("id", "customer_id", "title", "status", "revision", "assignee_id", "assignee_name", "timezone")}
        task_data["due_at"] = g.iso(task.due_at)
        latest_action = await db.scalar(select(Action).where(Action.binding_id == binding.id,
            Action.task_id == task.id, Action.kind == "post_publish",
            Action.status.in_(("pending", "unknown", "accepted", "succeeded"))).order_by(Action.id.desc()).limit(1))
        latest_schedule = await db.scalar(select(Schedule).where(Schedule.binding_id == binding.id,
            Schedule.task_id == task.id).order_by(Schedule.id.desc()).limit(1))
        if latest_action:
            action_data = g.action_data(latest_action, ctx)
            action_data["can_reconcile"] = bool(action_data["can_reconcile"] and permissions["can_publish"])
        if latest_schedule:
            schedule_data = management.schedule_data(latest_schedule)
        reserved = bool(latest_action or latest_schedule and latest_schedule.status in management.LIVE_SCHEDULES)
        checks.append(check("existing_request", "已有发布与排期", "blocked" if reserved else "passed",
            "此任务已有发布或有效排期，请查询原结果；不要再次提交" if reserved else "当前任务没有待确认、已成功的发布或有效排期"))
        approved = False
        if task.status != "ready":
            checks.append(check("approval", "图片文案审核", "pending" if task.status in {"draft", "in_review"} else "blocked",
                "草稿可继续准备，图片和文案须先由老板确认" if task.status == "draft" else
                "图片和文案正等待老板审核" if task.status == "in_review" else "当前任务状态不能新建 Google 发布"))
        else:
            try:
                await _approved_content(db, ctx, binding, task)
                approved = True
                checks.append(check("approval", "图片文案审核", "passed", "当前正文、发布配置和图片与老板审核版本一致"))
            except HTTPException as exc:
                checks.append(check("approval", "图片文案审核", "blocked", str(exc.detail)))
        can_publish = bool(configured and cooperating and connected and permissions["can_publish"] and approved and not reserved)
        assigned_primary = bool(operator_valid and task.assignee_id == binding.primary_operator_id)
        checks.append(check("schedule_operator", "排期负责人", "passed" if assigned_primary else "pending",
            "任务负责人和门店主运营一致" if assigned_primary else "定时发布要求任务负责人和门店主运营一致；不会自动转派"))
        can_schedule = bool(can_publish and assigned_primary and (ctx.owner or ctx.identity == binding.primary_operator_id))
    # Re-check the request actor's current rights after all preparation reads.
    fresh_ctx = await g.context(db, user)
    fresh_binding, fresh_connection, fresh_permissions = await g._binding(db, fresh_ctx, binding_id)
    fresh_policy = await images.delivery_policy(db, user, binding.customer_id)
    _, fresh_missing_configuration = g.provider.settings()
    if (g.binding_data(fresh_binding, fresh_permissions) != binding_snapshot or
            bool(fresh_connection.active and not fresh_connection.needs_reconnect and fresh_connection.token_encrypted) != connected or
            bool(fresh_missing_configuration) != bool(missing_configuration) or
            (fresh_policy["enabled"], fresh_policy["activated_at"]) != (policy["enabled"], policy["activated_at"])):
        raise HTTPException(409, "门店、权限或图片投递设置已变化，请重新读取准备状态")
    if task_id is not None:
        fresh_task, _, _ = await g.media._get_task(db, fresh_ctx, task_id)
        if (fresh_task.customer_id != task_data["customer_id"] or fresh_task.platform != "google_business" or
                fresh_task.revision != task_data["revision"] or fresh_task.status != task_data["status"] or
                fresh_task.assignee_id != task_data["assignee_id"]):
            raise HTTPException(409, "任务已变化，请重新读取准备状态")
    return {"binding": binding_snapshot, "task": task_data, "checks": checks,
        "image_delivery": {**policy, "scope": "owner_account"}, "scheduler": configuration,
        "active_action": action_data, "active_schedule": schedule_data,
        "can_open_publish": can_publish, "can_open_schedule": can_schedule,
        "notice": "这是当前准备状态，不会发布、排期、启用投递或授予权限；实际提交前仍会重新核验。"}
