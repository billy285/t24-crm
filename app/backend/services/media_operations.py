"""Native content operations. Writes are confined to the two media tables.

There is deliberately no scheduler, platform publisher, billing hook, permission
repair, AI call or external URL fetching in this first phase.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from models.customer_access_grants import CustomerAccessGrant
from models.customer_materials import Customer_materials
from models.customers import Customers
from models.employees import Employees
from models.media_operations import MediaOperationTask, MediaOperationEvent
from models.service_progresses import Service_progresses
from services.customer_permissions import customer_permissions_for_rows, _role_config
from services.customers import CustomersService
from services.role_permissions import load_role_permission_config, normalized_role
from services.schema_readiness import require_tables

TABLES = {"media_operation_tasks", "media_operation_events"}
PLATFORMS = (("google_business", "Google Business"), ("facebook", "Facebook"), ("instagram", "Instagram"),
             ("tiktok", "TikTok"), ("xiaohongshu", "小红书"), ("other", "其他"))
STATUSES = ("draft", "in_review", "ready", "completed", "blocked")
DOMAIN_LOCK = int.from_bytes(b"T24MEDI", "big")


def now():
    return datetime.now(timezone.utc)


def _iso(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.astimezone(timezone.utc).isoformat()


def _key(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value.lower():
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, "请使用有效的防重复请求编号")
    return value.lower()


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=_iso).encode()).hexdigest()


def _identity(user):
    try:
        identity = int(user.id)
        if identity < 1:
            raise ValueError()
        return identity
    except (ValueError, TypeError):
        raise HTTPException(403, "员工身份无效")


async def context(db, user):
    role = normalized_role(user)
    if role not in {"super_admin", "admin", "ops"}:
        raise HTTPException(403, "此账号未开放代运营中心")
    identity = _identity(user)
    config = await load_role_permission_config(db, user)
    owner = role == "super_admin"
    if not owner and not set(config.get("pages", [])).intersection({"/customers", "/service-board"}):
        raise HTTPException(403, "代运营功能尚未授权")
    await require_tables(db, TABLES)
    return SimpleNamespace(identity=identity, owner=owner, config=config, user=user,
                           can_create=owner or "task_create" in config.get("buttons", []),
                           can_edit=owner or "task_edit" in config.get("buttons", []))


async def _customer(db, ctx, customer_id, *, write=False):
    query = select(Customers).where(Customers.id == customer_id)
    scope = CustomersService._scope_filter_for_user(ctx.user, module="delivery", write=write)
    if scope is not None:
        query = query.where(scope)
    row = (await db.execute(query)).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "客户不存在或未获运营授权")
    if write and not ctx.owner:
        # Lock the current grant as well as the task during a write. A concurrent
        # revocation must serialize with this validation on PostgreSQL too.
        await db.execute(select(CustomerAccessGrant).where(CustomerAccessGrant.customer_id == customer_id,
                         CustomerAccessGrant.employee_id == ctx.identity).with_for_update())
    permissions = (await customer_permissions_for_rows(db, ctx.user, [row], config=ctx.config))[row.id]
    level = permissions["modules"]["delivery"]
    if not level["read"] or (not ctx.owner and not permissions["explicit"]):
        raise HTTPException(404, "客户不存在或未获运营授权")
    if write and not level["write"]:
        raise HTTPException(403, "此客户仅可查看，尚未开放运营协作")
    return row, permissions


async def _assignee(db, ctx, customer, assignee_id):
    identity = assignee_id or ctx.identity
    if identity != ctx.identity and not ctx.owner:
        raise HTTPException(403, "仅老板可以分配运营负责人")
    if identity == ctx.identity and ctx.owner:
        return identity, ctx.user.name or "老板"
    employee = await db.get(Employees, identity)
    if not employee or employee.status not in {"active", "probation"}:
        raise HTTPException(422, "请选择有效的运营负责人")
    target = SimpleNamespace(id=str(employee.id), role=employee.role, name=employee.name)
    if normalized_role(target) not in {"super_admin", "admin", "ops"}:
        raise HTTPException(422, "负责人账号未开放运营功能")
    await db.execute(select(CustomerAccessGrant).where(CustomerAccessGrant.customer_id == customer.id,
                     CustomerAccessGrant.employee_id == identity).with_for_update())
    config = await _role_config(db, target)
    if normalized_role(target) != "super_admin" and ("task_edit" not in config.get("buttons", []) or
            not set(config.get("pages", [])).intersection({"/customers", "/service-board"})):
        raise HTTPException(422, "负责人账号尚未开放运营编辑功能")
    permissions = (await customer_permissions_for_rows(db, target, [customer]))[customer.id]
    if normalized_role(target) != "super_admin" and (not permissions["explicit"] or not permissions["modules"]["delivery"]["write"]):
        raise HTTPException(422, "请先由老板邀请该员工协作此客户的服务交付")
    return employee.id, employee.name


async def _material(db, ctx, customer, material_id, *, proof=False):
    if material_id is None:
        return None
    permissions = (await customer_permissions_for_rows(db, ctx.user, [customer], config=ctx.config))[customer.id]
    if not permissions["modules"]["materials"]["read"]:
        raise HTTPException(403, "此客户的素材资料尚未授权")
    material = (await db.execute(select(Customer_materials).where(Customer_materials.id == material_id,
                   Customer_materials.customer_id == customer.id,
                   Customer_materials.visibility == "team"))).scalar_one_or_none()
    if not material:
        raise HTTPException(422, "请选择该客户已共享的运营素材")
    if proof and not (str(material.content_type or "").startswith("image/") or material.material_type in {"image", "photo", "screenshot"}):
        raise HTTPException(422, "发布截图凭证必须是已共享的图片素材")
    return material


def _validate_content_fields(value):
    title = str(value.get("title") or "").strip()
    if not title or len(title) > 200:
        raise HTTPException(422, "请输入 1—200 字的任务标题")
    platform = value.get("platform")
    if platform not in dict(PLATFORMS):
        raise HTTPException(422, "请选择支持的发布平台")
    zone = str(value.get("timezone") or "").strip()
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise HTTPException(422, "请选择有效的商家时区")
    due = value.get("due_at")
    try:
        due = datetime.fromisoformat(due.replace("Z", "+00:00")) if isinstance(due, str) else due
        if not isinstance(due, datetime) or due.tzinfo is None or due.utcoffset() is None:
            raise ValueError()
        due = due.astimezone(timezone.utc)
        if not 2000 <= due.year <= 2100:
            raise ValueError()
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise HTTPException(422, "截止时间必须包含时区偏移")
    content = str(value.get("content") or "").strip()
    if len(content) > 20000:
        raise HTTPException(422, "内容最多 20000 字")
    return {"title": title, "platform": platform, "due_at": due, "timezone": zone, "content": content}


def _proof_url(value):
    if not value or not value.strip():
        return None
    value = value.strip()
    if len(value) > 2048 or any(ord(c) < 33 for c in value) or "\\" in value:
        raise HTTPException(422, "请输入有效的公开 HTTPS 发布链接")
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in {None, 443}:
            raise ValueError()
        host.encode("idna")
        if "." not in host or host.endswith((".local", ".internal", ".localhost", ".test", ".example", ".invalid")):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
        if not all(part and all(ch.isalnum() or ch == "-" for ch in part) for part in host.split(".")):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise HTTPException(422, "请输入有效的公开 HTTPS 发布链接")
    # This is a human-entered reference. It is never fetched by this service.
    return value


async def _get_task(db, ctx, task_id, *, write=False):
    query = select(MediaOperationTask).where(MediaOperationTask.id == task_id).execution_options(populate_existing=True)
    if not ctx.owner:
        query = query.where(MediaOperationTask.assignee_id == ctx.identity)
    task = (await db.execute(query)).scalar_one_or_none()
    if not task:
        raise HTTPException(404, "运营任务不存在或未获授权")
    customer, permissions = await _customer(db, ctx, task.customer_id, write=write)
    if write and not ctx.can_edit:
        raise HTTPException(403, "运营编辑功能尚未授权")
    return task, customer, permissions


def _data(task, ctx, permissions):
    fields = ("id", "customer_id", "customer_name", "service_progress_id", "title", "platform", "status", "timezone",
              "assignee_id", "assignee_name", "content", "material_id", "material_title", "proof_url", "proof_material_id",
              "review_note", "block_reason", "revision")
    data = {key: getattr(task, key) for key in fields}
    for key in ("due_at", "created_at", "updated_at", "completed_at"):
        data[key] = _iso(getattr(task, key))
    write = bool(ctx.can_edit and permissions["modules"]["delivery"]["write"] and (ctx.owner or task.assignee_id == ctx.identity))
    data["permissions"] = {
        "can_edit": write and task.status == "draft",
        "can_submit": write and task.status == "draft",
        "can_review": ctx.owner and task.status == "in_review",
        "can_complete": write and task.status == "ready",
        "can_block": write and task.status in {"draft", "in_review", "ready"},
        "can_resume": write and task.status == "blocked",
    }
    # References can outlive a materials invitation. Never reveal a material
    # pointer/title to someone who now lacks that separate module.
    if not permissions["modules"]["materials"]["read"]:
        data.update(material_id=None, material_title=None, proof_material_id=None)
    return data


async def _detail(db, ctx, task, permissions):
    data = _data(task, ctx, permissions)
    await _redact_material_references(db, [data])
    events = (await db.execute(select(MediaOperationEvent).where(MediaOperationEvent.task_id == task.id)
                             .order_by(MediaOperationEvent.revision.desc()).limit(100))).scalars().all()
    data["events"] = [{"id": e.id, "action": e.action, "actor_name": e.actor_name, "created_at": _iso(e.created_at),
                       "note": e.note, "revision": e.revision, "before_status": e.before_status, "after_status": e.after_status} for e in events]
    return data


async def _redact_material_references(db, rows):
    """Re-check separate material visibility even after a task was reviewed.

    The existing material download endpoint still performs its own permission
    check. This prevents an old snapshot from leaking private material titles
    after the owner changes visibility or moves/removes the source record.
    """
    ids = {row[key] for row in rows for key in ("material_id", "proof_material_id") if row.get(key) is not None}
    if not ids:
        return
    visible = {row.id: row.customer_id for row in (await db.execute(select(Customer_materials.id, Customer_materials.customer_id)
               .where(Customer_materials.id.in_(ids), Customer_materials.visibility == "team"))).all()}
    for row in rows:
        if visible.get(row.get("material_id")) != row["customer_id"]:
            row.update(material_id=None, material_title=None)
        if visible.get(row.get("proof_material_id")) != row["customer_id"]:
            row["proof_material_id"] = None


async def options(db, user):
    ctx = await context(db, user)
    query = select(Customers).order_by(Customers.business_name, Customers.id)
    scope = CustomersService._scope_filter_for_user(user, module="delivery")
    if scope is not None:
        query = query.where(scope)
    customers = (await db.execute(query)).scalars().all()
    permissions = await customer_permissions_for_rows(db, user, customers, config=ctx.config)
    customers = [c for c in customers if permissions[c.id]["modules"]["delivery"]["read"] and (ctx.owner or permissions[c.id]["explicit"])]
    ids = [c.id for c in customers]
    services = (await db.execute(select(Service_progresses).where(Service_progresses.customer_id.in_(ids)))).scalars().all() if ids else []
    material_customers = [c.id for c in customers if permissions[c.id]["modules"]["materials"]["read"]]
    materials = (await db.execute(select(Customer_materials.id, Customer_materials.customer_id, Customer_materials.title,
                  Customer_materials.material_type, Customer_materials.content_type).where(Customer_materials.customer_id.in_(material_customers),
                  Customer_materials.visibility == "team"))).all() if material_customers else []
    items = [{"id": c.id, "name": c.business_name, "can_write": bool(permissions[c.id]["modules"]["delivery"]["write"] and ctx.can_edit),
              "services": [{"id": s.id, "name": s.package_name or s.service_type or "服务项目"} for s in services if s.customer_id == c.id],
              "materials": [{"id": m.id, "title": m.title, "material_type": m.material_type, "content_type": m.content_type} for m in materials if m.customer_id == c.id]} for c in customers]
    assignees = [{"id": ctx.identity, "name": user.name or "当前员工", "eligible_customer_ids": [c["id"] for c in items if c["can_write"]]}]
    if ctx.owner:
        assignees = []
        for employee in (await db.execute(select(Employees).where(Employees.status.in_(("active", "probation"))).order_by(Employees.name))).scalars():
            target = SimpleNamespace(id=str(employee.id), role=employee.role, name=employee.name)
            if normalized_role(target) not in {"super_admin", "admin", "ops"}:
                continue
            target_config = await _role_config(db, target)
            if normalized_role(target) != "super_admin" and ("task_edit" not in target_config.get("buttons", []) or
                    not set(target_config.get("pages", [])).intersection({"/customers", "/service-board"})):
                continue
            assigned = await customer_permissions_for_rows(db, target, customers)
            eligible = [c.id for c in customers if assigned[c.id]["modules"]["delivery"]["write"] and
                        (normalized_role(target) == "super_admin" or assigned[c.id]["explicit"])]
            if eligible:
                assignees.append({"id": employee.id, "name": employee.name, "eligible_customer_ids": eligible})
        if not any(a["id"] == ctx.identity for a in assignees):
            assignees.insert(0, {"id": ctx.identity, "name": user.name or "老板", "eligible_customer_ids": ids})
    return {"customers": items, "assignees": assignees, "platforms": [{"value": value, "label": label} for value, label in PLATFORMS]}


async def list_tasks(db, user, *, status=None, customer_id=None, q=None, skip=0, limit=50):
    ctx = await context(db, user)
    if status and status not in STATUSES:
        raise HTTPException(422, "无效的运营任务状态")
    query = select(MediaOperationTask).join(Customers, MediaOperationTask.customer_id == Customers.id)
    scope = CustomersService._scope_filter_for_user(user, module="delivery")
    if scope is not None:
        query = query.where(scope, MediaOperationTask.assignee_id == ctx.identity)
    # The role's page requirement is already checked; SQL grant scope enforces
    # current explicit invitations for every list/count/summary result.
    if customer_id is not None:
        query = query.where(MediaOperationTask.customer_id == customer_id)
    if q:
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where((MediaOperationTask.title.ilike(f"%{escaped}%", escape="\\")) |
                            (MediaOperationTask.customer_name.ilike(f"%{escaped}%", escape="\\")))
    summary = {name: 0 for name in (*STATUSES, "overdue")}
    grouped = await db.execute(select(MediaOperationTask.status, func.count()).where(MediaOperationTask.id.in_(query.with_only_columns(MediaOperationTask.id))).group_by(MediaOperationTask.status))
    for name, count in grouped:
        summary[name] = count
    summary["overdue"] = await db.scalar(select(func.count()).select_from(MediaOperationTask).where(
        MediaOperationTask.id.in_(query.with_only_columns(MediaOperationTask.id)), MediaOperationTask.status != "completed", MediaOperationTask.due_at < now())) or 0
    if status:
        query = query.where(MediaOperationTask.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await db.execute(query.order_by(MediaOperationTask.due_at, MediaOperationTask.id).offset(skip).limit(limit))).scalars().all()
    customer_rows = (await db.execute(select(Customers).where(Customers.id.in_({r.customer_id for r in rows})))).scalars().all() if rows else []
    perms = await customer_permissions_for_rows(db, user, customer_rows, config=ctx.config)
    items = [_data(row, ctx, perms[row.customer_id]) for row in rows]
    await _redact_material_references(db, items)
    return {"items": items, "total": total, "skip": skip, "limit": limit,
            "summary": summary, "capabilities": {"can_create": ctx.can_create, "is_owner": ctx.owner}}


async def get_task(db, user, task_id):
    ctx = await context(db, user)
    task, _, permissions = await _get_task(db, ctx, task_id)
    return await _detail(db, ctx, task, permissions)


async def _lock(db):
    if db.get_bind().dialect.name == "sqlite":
        await db.execute(text("UPDATE media_operation_tasks SET id=id WHERE 0"))
    elif db.get_bind().dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": DOMAIN_LOCK})


@asynccontextmanager
async def _write(db):
    try:
        await _lock(db)
        yield
        await db.commit()
    except (IntegrityError, DBAPIError):
        await db.rollback()
        raise HTTPException(409, "任务正在更新或已保存，请刷新核对后重试")
    except BaseException:
        await db.rollback()
        raise


async def _event(db, ctx, task, action, before_status, *, request_id=None, fingerprint=None, note=None):
    db.add(MediaOperationEvent(task_id=task.id, revision=task.revision, action=action, actor_id=ctx.identity,
           actor_name=ctx.user.name or str(ctx.identity), before_status=before_status, after_status=task.status,
           request_id=request_id, request_fingerprint=fingerprint, note=note,
           snapshot={"title": task.title, "platform": task.platform, "content": task.content, "material_id": task.material_id,
                     "assignee_id": task.assignee_id, "due_at": _iso(task.due_at), "timezone": task.timezone,
                     "proof_url": task.proof_url, "proof_material_id": task.proof_material_id}, created_at=now()))
    await db.flush()


async def _cas(db, task, expected_revision, values):
    if expected_revision != task.revision:
        raise HTTPException(409, "任务已更新，请刷新后再操作")
    result = await db.execute(update(MediaOperationTask).where(MediaOperationTask.id == task.id,
                MediaOperationTask.revision == expected_revision, MediaOperationTask.status == task.status)
                .values(**values, revision=expected_revision + 1, updated_at=now()).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise HTTPException(409, "任务正在被其他人处理，请刷新后再试")
    await db.refresh(task)


async def create_task(db, user, *, client_request_id, customer_id, service_progress_id=None, assignee_id=None,
                      material_id=None, **fields):
    ctx = await context(db, user)
    if not ctx.can_create:
        raise HTTPException(403, "运营新建功能尚未授权")
    key = _key(client_request_id)
    values = _validate_content_fields(fields)
    fingerprint = _hash({**values, "customer_id": customer_id, "service_progress_id": service_progress_id,
                         "assignee_id": assignee_id or ctx.identity, "material_id": material_id})
    async with _write(db):
        existing = (await db.execute(select(MediaOperationTask).where(MediaOperationTask.created_by_id == ctx.identity,
                    MediaOperationTask.client_request_id == key))).scalar_one_or_none()
        if existing:
            task, _, permissions = await _get_task(db, ctx, existing.id)
            if task.creation_fingerprint != fingerprint:
                raise HTTPException(409, "相同请求编号对应的任务内容不一致")
            result = await _detail(db, ctx, task, permissions)
        else:
            customer, permissions = await _customer(db, ctx, customer_id, write=True)
            if service_progress_id is not None:
                service = await db.get(Service_progresses, service_progress_id)
                if not service or service.customer_id != customer.id:
                    raise HTTPException(422, "服务项目与客户不匹配")
            assignee, name = await _assignee(db, ctx, customer, assignee_id)
            material = await _material(db, ctx, customer, material_id)
            task = MediaOperationTask(customer_id=customer.id, customer_name=customer.business_name,
                   service_progress_id=service_progress_id, assignee_id=assignee, assignee_name=name,
                   material_id=material_id, material_title=material.title if material else None,
                   created_by_id=ctx.identity, client_request_id=key, creation_fingerprint=fingerprint,
                   status="draft", revision=1, created_at=now(), updated_at=now(), **values)
            db.add(task)
            await db.flush()
            await _event(db, ctx, task, "create", None)
            result = await _detail(db, ctx, task, permissions)
    return result


async def edit_task(db, user, task_id, *, expected_revision, **fields):
    ctx = await context(db, user)
    async with _write(db):
        task, customer, permissions = await _get_task(db, ctx, task_id, write=True)
        if task.status != "draft":
            raise HTTPException(409, "仅待准备或已退回的内容可以修改")
        merged = {name: fields.get(name, getattr(task, name)) for name in ("title", "platform", "due_at", "timezone", "content")}
        if "due_at" not in fields:
            # SQLite stores UTC DateTime values without their timezone marker.
            # User input remains offset-required; preserving an existing deadline
            # during a partial edit must not reinterpret it as local time.
            merged["due_at"] = _iso(task.due_at)
        values = _validate_content_fields(merged)
        if "material_id" in fields:
            material = await _material(db, ctx, customer, fields["material_id"])
            values.update(material_id=fields["material_id"], material_title=material.title if material else None)
        if "assignee_id" in fields and fields["assignee_id"] != task.assignee_id:
            if not ctx.owner:
                raise HTTPException(403, "仅老板可以转派运营负责人")
            identity, name = await _assignee(db, ctx, customer, fields["assignee_id"])
            values.update(assignee_id=identity, assignee_name=name)
        await _cas(db, task, expected_revision, values)
        await _event(db, ctx, task, "edit", "draft")
        result = await _detail(db, ctx, task, permissions)
    return result


async def transition_task(db, user, task_id, *, expected_revision, request_id, action, note=None, proof_url=None, proof_material_id=None):
    ctx = await context(db, user)
    key = _key(request_id)
    note = note.strip() if note else None
    fingerprint = _hash({"action": action, "expected_revision": expected_revision, "note": note,
                         "proof_url": proof_url, "proof_material_id": proof_material_id})
    async with _write(db):
        task, customer, permissions = await _get_task(db, ctx, task_id, write=True)
        previous = (await db.execute(select(MediaOperationEvent).where(MediaOperationEvent.task_id == task.id,
                          MediaOperationEvent.request_id == key))).scalar_one_or_none()
        if previous:
            if previous.actor_id != ctx.identity or previous.request_fingerprint != fingerprint:
                raise HTTPException(409, "相同请求编号对应的操作不一致")
            result = await _detail(db, ctx, task, permissions)
        else:
            before = task.status
            values = {}
            if action == "submit" and before == "draft":
                if not task.content.strip():
                    raise HTTPException(422, "请先填写内容草稿再提交审核")
                # Revalidate referenced assets at the moment content enters review.
                await _material(db, ctx, customer, task.material_id)
                values = {"status": "in_review", "review_note": None}
            elif action in {"approve", "return"} and before == "in_review":
                if not ctx.owner:
                    raise HTTPException(403, "第一阶段由老板审核内容")
                if action == "return" and (not note or len(note) < 3):
                    raise HTTPException(422, "请填写至少 3 字的退回原因")
                await _material(db, ctx, customer, task.material_id)
                values = {"status": "ready" if action == "approve" else "draft", "review_note": note}
            elif action == "complete" and before == "ready":
                url = _proof_url(proof_url)
                await _material(db, ctx, customer, proof_material_id, proof=True)
                if not url and proof_material_id is None:
                    raise HTTPException(422, "请提交公开发布链接或该客户已共享的截图凭证")
                values = {"status": "completed", "proof_url": url, "proof_material_id": proof_material_id, "completed_at": now()}
            elif action == "block" and before in {"draft", "in_review", "ready"}:
                if not note or len(note) < 3:
                    raise HTTPException(422, "请填写至少 3 字的阻塞原因")
                values = {"status": "blocked", "block_reason": note, "blocked_from_status": before}
            elif action == "resume" and before == "blocked":
                values = {"status": "ready" if task.blocked_from_status == "ready" else "draft", "block_reason": None, "blocked_from_status": None}
            else:
                raise HTTPException(409, "当前状态不能执行此操作，请刷新任务")
            if action != "complete" and (proof_url is not None or proof_material_id is not None):
                raise HTTPException(422, "仅完成发布时可以提交凭证")
            await _cas(db, task, expected_revision, values)
            await _event(db, ctx, task, action, before, request_id=key, fingerprint=fingerprint, note=note)
            result = await _detail(db, ctx, task, permissions)
    return result
