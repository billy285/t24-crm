"""Native content operations. Writes are confined to content, audit and opt-in publication tables.

There is deliberately no scheduler, platform publisher, billing hook, permission
repair, AI call or external URL fetching in this first phase.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import re
import unicodedata
from types import SimpleNamespace
from urllib.parse import urlsplit, unquote
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from models.customer_access_grants import CustomerAccessGrant
from models.customer_materials import Customer_materials
from models.customers import Customers
from models.employees import Employees
from models.media_operations import MediaOperationTask, MediaOperationEvent, MediaOperationPublicationSpec
from models.service_progresses import Service_progresses
from services.customer_permissions import customer_permissions_for_rows, _role_config
from services.customers import CustomersService
from services.role_permissions import load_role_permission_config, normalized_role
from services.schema_readiness import require_tables, tables_available

TABLES = {"media_operation_tasks", "media_operation_events", "media_operation_publication_specs"}
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


DEFAULT_PUBLICATION = {"topic_type": "STANDARD"}


def _publication_object(value, allowed, message):
    if type(value) is not dict or set(value) - set(allowed): raise HTTPException(422, message)
    return value


def _publication_text(value, maximum, *, required=False, multiline=False):
    if not isinstance(value, str): raise HTTPException(422, "发布配置文字格式不正确")
    if any(unicodedata.category(c).startswith("C") and (not multiline or c not in "\n\t") for c in value):
        raise HTTPException(422, "发布配置不能包含隐藏控制字符")
    result = value.strip()
    if len(result) > maximum or (required and not result): raise HTTPException(422, "发布配置文字长度不正确")
    return result


def _publication_url(value):
    if not isinstance(value, str) or not value or len(value) > 2048 or any(c.isspace() or unicodedata.category(c).startswith("C") or c == "\\" for c in value):
        raise HTTPException(422, "请填写不含凭据或控制字符的公开 HTTPS 链接")
    try:
        parsed = urlsplit(value); host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host or parsed.username is not None or parsed.password is not None or "#" in value or parsed.port not in {None, 443}: raise ValueError()
        if parsed.port is not None and not parsed.netloc.endswith(":443"): raise ValueError()
        if host.endswith((".localhost", ".local", ".internal", ".test", ".invalid", ".example", ".lan", ".home", ".arpa", ".onion")) or "." not in host or len(host) > 253: raise ValueError()
        try: ipaddress.ip_address(host)
        except ValueError: pass
        else: raise ValueError()
        if all(re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", part) for part in host.split(".")): raise ValueError()
        if not re.search(r"[a-z]", host.rsplit(".", 1)[-1]) or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in host.split(".")): raise ValueError()
        decoded = value
        for _ in range(3):
            decoded = unquote(decoded)
            if any(ord(c) < 32 or ord(c) == 127 or c == "\\" for c in decoded): raise ValueError()
    except (ValueError, TypeError, UnicodeError):
        raise HTTPException(422, "请填写公开域名的 HTTPS 链接，不允许内网、IP、凭据、片段或非443端口")
    # Preserve normal query parameters verbatim. Never fetch, resolve, rewrite,
    # append tracking, or treat this as a source-image authorization.
    return value


def _publication_instant(value, zone):
    if not isinstance(value, str) or len(value) > 80 or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?(?:Z|[+-][0-9]{2}:[0-9]{2})", value) or value.endswith("-00:00"):
        raise HTTPException(422, "活动起止时间必须包含明确时区偏移，精确到分钟")
    try:
        if not value.endswith("Z") and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59): raise ValueError()
        supplied = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if supplied.second or supplied.microsecond: raise ValueError()
        utc = supplied.astimezone(timezone.utc); local = utc.astimezone(ZoneInfo(zone))
        if not 2000 <= local.year <= 2100: raise ValueError()
        if supplied.utcoffset().total_seconds() != 0 and (supplied.replace(tzinfo=None) != local.replace(tzinfo=None) or supplied.utcoffset() != local.utcoffset()):
            raise HTTPException(422, "活动时间偏移与商家时区不一致，请重新选择当地时间")
        wall = local.replace(tzinfo=None); tz = ZoneInfo(zone)
        first, second = wall.replace(tzinfo=tz, fold=0), wall.replace(tzinfo=tz, fold=1)
        if first.utcoffset() != second.utcoffset() and all(x.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == wall for x in (first, second)):
            raise HTTPException(422, "活动时间落在夏令时重复时段，Google活动无法表达此偏移，请选择明确时刻")
        return utc, local
    except (ValueError, TypeError, OverflowError, ZoneInfoNotFoundError):
        raise HTTPException(422, "活动起止时间无效或不是完整分钟")


def normalize_publication(value, platform, zone):
    if platform != "google_business":
        if value is not None: raise HTTPException(422, "此发布配置仅用于 Google，其他平台仍为手工交付")
        return None
    if value is None: return dict(DEFAULT_PUBLICATION)
    value = _publication_object(value, {"topic_type", "event", "offer", "call_to_action"}, "存在不支持的 Google 发布配置")
    kind = value.get("topic_type")
    if not isinstance(kind, str) or kind not in {"STANDARD", "EVENT", "OFFER"}: raise HTTPException(422, "请选择普通图文、活动或优惠")
    result = {"topic_type": kind}; event = value.get("event"); offer = value.get("offer"); cta = value.get("call_to_action")
    if kind == "STANDARD" and (event is not None or offer is not None): raise HTTPException(422, "普通图文不能包含活动或优惠配置")
    if kind in {"EVENT", "OFFER"}:
        event = _publication_object(event, {"title", "start_at", "end_at"}, "活动与优惠必须填写完整的标题及起止时间")
        title = _publication_text(event.get("title"), 200, required=True)
        start, local_start = _publication_instant(event.get("start_at"), zone); end, local_end = _publication_instant(event.get("end_at"), zone)
        if end <= start or local_end.replace(tzinfo=None) <= local_start.replace(tzinfo=None): raise HTTPException(422, "活动结束时间必须晚于开始时间")
        result["event"] = {"title": title, "start_at": start.isoformat().replace("+00:00", "Z"), "end_at": end.isoformat().replace("+00:00", "Z")}
    if kind == "OFFER":
        offer = _publication_object(offer, {"coupon_code", "redeem_online_url", "terms_conditions"}, "优惠必须包含有效的优惠配置对象")
        if cta is not None: raise HTTPException(422, "Google优惠不使用行动按钮，请填写优惠兑换链接")
        result["offer"] = {}
        for key, maximum in (("coupon_code", 100), ("terms_conditions", 5000)):
            if offer.get(key) is not None:
                text = _publication_text(offer[key], maximum, multiline=key == "terms_conditions")
                if text: result["offer"][key] = text
        if offer.get("redeem_online_url") is not None: result["offer"]["redeem_online_url"] = _publication_url(offer["redeem_online_url"])
    elif offer is not None: raise HTTPException(422, "只有优惠类型可以包含优惠配置")
    if cta is not None:
        cta = _publication_object(cta, {"action_type", "url"}, "行动按钮配置不正确")
        action = cta.get("action_type")
        if not isinstance(action, str) or action not in {"BOOK", "ORDER", "SHOP", "LEARN_MORE", "SIGN_UP", "CALL"}: raise HTTPException(422, "请选择支持的行动按钮")
        result["call_to_action"] = {"action_type": action}
        if action == "CALL":
            if cta.get("url") is not None: raise HTTPException(422, "拨打电话按钮使用Google商家电话，不允许自填电话或链接")
        else: result["call_to_action"]["url"] = _publication_url(cta.get("url"))
    return result


def publication_payload(publication, zone):
    spec = normalize_publication(publication, "google_business", zone)
    result = {"topicType": spec["topic_type"]}
    if "event" in spec:
        event = spec["event"]; schedule = {}
        for prefix, key in (("start", "start_at"), ("end", "end_at")):
            _, local = _publication_instant(event[key], zone)
            schedule[prefix + "Date"] = {"year": local.year, "month": local.month, "day": local.day}
            schedule[prefix + "Time"] = {"hours": local.hour, "minutes": local.minute, "seconds": 0, "nanos": 0}
        result["event"] = {"title": event["title"], "schedule": schedule}
    if "offer" in spec:
        result["offer"] = {target: spec["offer"][key] for key, target in (("coupon_code", "couponCode"), ("redeem_online_url", "redeemOnlineUrl"), ("terms_conditions", "termsConditions")) if key in spec["offer"]}
    if "call_to_action" in spec:
        cta = spec["call_to_action"]; result["callToAction"] = {"actionType": cta["action_type"]}
        if "url" in cta: result["callToAction"]["url"] = cta["url"]
    return result


async def publication_for_task(db, task):
    row = await db.get(MediaOperationPublicationSpec, task.id, populate_existing=True)
    if row is None: return normalize_publication(None, task.platform, task.timezone)
    if type(row.spec) is not dict: raise HTTPException(422, "发布配置记录无效，请退回后重新保存")
    result = normalize_publication(row.spec, task.platform, task.timezone)
    if result != row.spec: raise HTTPException(422, "发布配置已变化，请退回后重新审核")
    return result


async def _save_publication(db, task, value):
    row = await db.get(MediaOperationPublicationSpec, task.id, populate_existing=True)
    if value is None or value == DEFAULT_PUBLICATION:
        if row is not None: await db.delete(row)
    elif row is None: db.add(MediaOperationPublicationSpec(task_id=task.id, spec=value))
    else: row.spec = value
    await db.flush()


async def _add_publications(db, rows):
    if not rows: return
    specs = (await db.scalars(select(MediaOperationPublicationSpec).where(MediaOperationPublicationSpec.task_id.in_([row["id"] for row in rows])))).all()
    by_id = {row.task_id: row.spec for row in specs}
    for row in rows:
        stored = by_id.get(row["id"])
        if row["id"] in by_id and type(stored) is not dict: raise HTTPException(422, "发布配置记录无效，请重新核对")
        publication = normalize_publication(stored, row["platform"], row["timezone"])
        if row["id"] in by_id and stored != publication: raise HTTPException(422, "发布配置记录无效，请重新核对")
        row["publication"] = publication


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
        "can_return": ctx.owner and (task.status == "in_review" or (task.platform == "google_business" and task.status == "ready")),
        "can_complete": write and task.status == "ready",
        "can_block": write and task.status in {"draft", "in_review", "ready"},
        "can_resume": write and task.status == "blocked",
    }
    # References can outlive a materials invitation. Never reveal a material
    # pointer/title to someone who now lacks that separate module.
    if not permissions["modules"]["materials"]["read"]:
        data.update(material_id=None, material_title=None, proof_material_id=None)
    return data


async def _google_return_permissions(db, rows):
    candidates = [row for row in rows if row["platform"] == "google_business" and row["status"] == "ready" and row["permissions"].get("can_return")]
    if not candidates: return
    if not await tables_available(db, {"google_business_actions"}):
        for row in candidates: row["permissions"]["can_return"] = False
        return
    from models.google_business import GoogleBusinessAction
    blocked = set((await db.execute(select(GoogleBusinessAction.task_id).where(
        GoogleBusinessAction.task_id.in_([row["id"] for row in candidates]), GoogleBusinessAction.kind == "post_publish",
        GoogleBusinessAction.status.in_(("pending", "unknown", "accepted", "succeeded"))))).scalars())
    for row in candidates:
        if row["id"] in blocked: row["permissions"]["can_return"] = False


async def _detail(db, ctx, task, permissions):
    data = _data(task, ctx, permissions)
    data["publication"] = await publication_for_task(db, task)
    await _google_return_permissions(db, [data])
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
    await _add_publications(db, items)
    await _google_return_permissions(db, items)
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
    snapshot = {"title": task.title, "platform": task.platform, "content": task.content, "material_id": task.material_id,
                "assignee_id": task.assignee_id, "due_at": _iso(task.due_at), "timezone": task.timezone,
                "proof_url": task.proof_url, "proof_material_id": task.proof_material_id,
                "publication": await publication_for_task(db, task)}
    if action == "approve" and task.platform == "google_business" and task.material_id is not None:
        # Freeze the approved asset reference, not its remote bytes. Google
        # publishing must refuse a changed reference and require re-approval.
        material = await db.get(Customer_materials, task.material_id, populate_existing=True)
        if material and material.customer_id == task.customer_id and material.visibility == "team":
            snapshot["google_material_fingerprint"] = _hash({"id": material.id, "customer_id": material.customer_id,
                "file_url": material.file_url, "content_type": material.content_type, "updated_at": _iso(material.updated_at)})
    db.add(MediaOperationEvent(task_id=task.id, revision=task.revision, action=action, actor_id=ctx.identity,
           actor_name=ctx.user.name or str(ctx.identity), before_status=before_status, after_status=task.status,
           request_id=request_id, request_fingerprint=fingerprint, note=note,
           snapshot=snapshot, created_at=now()))
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
    publication = normalize_publication(fields.get("publication"), values["platform"], values["timezone"])
    fingerprint_values = {**values, "customer_id": customer_id, "service_progress_id": service_progress_id,
                         "assignee_id": assignee_id or ctx.identity, "material_id": material_id}
    if publication not in (None, DEFAULT_PUBLICATION): fingerprint_values["publication"] = publication
    fingerprint = _hash(fingerprint_values)
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
            await _save_publication(db, task, publication)
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
        prior_publication = await publication_for_task(db, task)
        publication = normalize_publication(fields.get("publication", prior_publication), values["platform"], values["timezone"])
        if "material_id" in fields:
            material = await _material(db, ctx, customer, fields["material_id"])
            values.update(material_id=fields["material_id"], material_title=material.title if material else None)
        if "assignee_id" in fields and fields["assignee_id"] != task.assignee_id:
            if not ctx.owner:
                raise HTTPException(403, "仅老板可以转派运营负责人")
            identity, name = await _assignee(db, ctx, customer, fields["assignee_id"])
            values.update(assignee_id=identity, assignee_name=name)
        await _cas(db, task, expected_revision, values)
        await _save_publication(db, task, publication)
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
            elif action in {"approve", "return"} and (before == "in_review" or (action == "return" and before == "ready" and task.platform == "google_business")):
                if not ctx.owner:
                    raise HTTPException(403, "第一阶段由老板审核内容")
                if action == "return" and (not note or len(note) < 3):
                    raise HTTPException(422, "请填写至少 3 字的退回原因")
                if before == "ready":
                    # Serialize against GBP reservation/dispatch before checking
                    # active publication. A sent/unknown task must never reopen.
                    await db.execute(select(MediaOperationTask).where(MediaOperationTask.id == task.id).with_for_update())
                    await db.refresh(task)
                    if task.status != "ready" or task.revision != expected_revision:
                        raise HTTPException(409, "任务状态已变化，请刷新后重试")
                    await require_tables(db, {"google_business_actions"})
                    from models.google_business import GoogleBusinessAction
                    pending_publication = await db.scalar(select(GoogleBusinessAction.id).where(
                        GoogleBusinessAction.task_id == task.id, GoogleBusinessAction.kind == "post_publish",
                        GoogleBusinessAction.status.in_(("pending", "unknown", "accepted", "succeeded"))).limit(1))
                    if pending_publication:
                        raise HTTPException(409, "此任务已有 Google 发布请求，请先核对原结果；已发送或结果未明的任务不能退回重发")
                else:
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
