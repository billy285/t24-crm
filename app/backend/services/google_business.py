"""CRM-only Google delegation, live reads and durable externally visible actions.

Only new Google tables are written. Existing customer invitations, private space,
financial records and the manually reviewed media workflow remain untouched.
"""
from __future__ import annotations
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import secrets
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from models.employees import Employees
from models.customers import Customers
from models.media_operations import MediaOperationTask, MediaOperationEvent
from models.customer_access_grants import CustomerAccessGrant
from models.google_business import GoogleBusinessConnection as Connection, GoogleBusinessOAuthState as OAuthState, GoogleBusinessBinding as Binding, GoogleBusinessGrant as Grant, GoogleBusinessAction as Action
from services import media_operations as media
from services import google_business_provider as provider
from services.customer_permissions import customer_permissions_for_rows
from services.role_permissions import normalized_role
from services.schema_readiness import require_tables

TABLES = {"google_business_connections", "google_business_oauth_states", "google_business_bindings", "google_business_grants", "google_business_actions"}
COOKIE = "__Secure-t24_gbp_oauth"
LOCK = int.from_bytes(b"T24GBP1", "big")
MESSAGES = {"reconnect_required": "Google 授权已失效，请老板重新连接", "access_denied": "Google 门店权限或 API 接入资格不足，请老板核查", "quota_limited": "Google 请求额度暂时不足，请稍后重新读取", "not_found": "Google 记录不存在或已无权查看", "listing_too_large": "Google 门店列表过大，请联系管理员分批接入", "invalid_request": "Google 未接受这次操作，请检查内容和门店状态", "invalid_response": "Google 返回结果暂无法核实，请重新读取状态", "provider_unavailable": "Google 暂时无法连接，请稍后重新读取"}


def now(): return datetime.now(timezone.utc)
def aware(value): return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
def iso(value): return aware(value).isoformat() if value else None
def digest(value): return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
def hash_text(value): return hashlib.sha256(str(value).encode()).hexdigest()


async def context(db, user, *, owner=False):
    ctx = await media.context(db, user)
    employee = await db.get(Employees, ctx.identity, populate_existing=True)
    if not employee or employee.status not in {"active", "probation"} or normalized_role(SimpleNamespace(role=employee.role)) != normalized_role(user):
        raise HTTPException(403, "当前员工身份已失效，请重新登录")
    await require_tables(db, TABLES)
    if owner and not ctx.owner: raise HTTPException(403, "仅老板可以管理 Google 门店连接与授权")
    return ctx


async def _lock(db):
    if db.get_bind().dialect.name == "sqlite": await db.execute(text("UPDATE google_business_actions SET id=id WHERE 0"))
    elif db.get_bind().dialect.name == "postgresql": await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK})


@asynccontextmanager
async def write(db):
    try:
        await _lock(db)
        yield
        await db.commit()
    except (DBAPIError, IntegrityError):
        await db.rollback()
        raise HTTPException(409, "Google 记录正在更新，请刷新后核对")
    except BaseException:
        await db.rollback()
        raise


async def _connection(db, ctx, connection_id, *, lock=False):
    query = select(Connection).where(Connection.id == connection_id).execution_options(populate_existing=True)
    if ctx.owner: query = query.where(Connection.owner_id == ctx.identity)
    if lock: query = query.with_for_update()
    result = (await db.execute(query)).scalar_one_or_none()
    if not result or not result.active: raise HTTPException(404, "Google 连接不存在或已断开")
    return result


async def _permissions(db, ctx, binding, *, lock=False):
    customer, existing = await media._customer(db, ctx, binding.customer_id, write=False)
    public_allowed = binding.active and binding.lifecycle == "active" and customer.status == "closed"
    if ctx.owner: return {"can_read": True, "can_reply": bool(public_allowed), "can_publish": bool(public_allowed), "can_manage": True}
    query = select(Grant).where(Grant.binding_id == binding.id, Grant.employee_id == ctx.identity).execution_options(populate_existing=True)
    if lock: query = query.with_for_update()
    grant = (await db.execute(query)).scalar_one_or_none()
    if not grant or not (grant.can_reply or grant.can_publish): raise HTTPException(404, "此门店尚未向你开放 Google 操作")
    if lock:
        await db.execute(select(CustomerAccessGrant).where(CustomerAccessGrant.customer_id == binding.customer_id, CustomerAccessGrant.employee_id == ctx.identity).with_for_update().execution_options(populate_existing=True))
        _, existing = await media._customer(db, ctx, binding.customer_id, write=False)
    allowed = bool(public_allowed and ctx.can_edit and existing["modules"]["delivery"]["write"])
    return {"can_read": True, "can_reply": bool(allowed and grant.can_reply), "can_publish": bool(allowed and grant.can_publish), "can_manage": False}


async def _binding(db, ctx, binding_id, *, action=None, lock=False):
    if lock:
        actor = await db.scalar(select(Employees).where(Employees.id == ctx.identity).with_for_update().execution_options(populate_existing=True))
        if not actor or actor.status not in {"active", "probation"} or normalized_role(SimpleNamespace(role=actor.role)) != normalized_role(ctx.user):
            raise HTTPException(403, "当前员工身份已失效，请重新登录")
    query = select(Binding).where(Binding.id == binding_id, Binding.active.is_(True)).execution_options(populate_existing=True)
    if lock: query = query.with_for_update()
    binding = (await db.execute(query)).scalar_one_or_none()
    if not binding: raise HTTPException(404, "Google 门店绑定不存在或已停用")
    connection = await _connection(db, ctx, binding.connection_id, lock=lock)
    # Delegation is anchored to an active owner; disabling that account fences staff too.
    owner = await db.scalar(select(Employees).where(Employees.id == connection.owner_id).with_for_update().execution_options(populate_existing=True)) if lock else await db.get(Employees, connection.owner_id, populate_existing=True)
    if not owner or owner.status not in {"active", "probation"} or normalized_role(SimpleNamespace(role=owner.role)) != "super_admin":
        raise HTTPException(404, "Google 门店连接需要老板重新确认")
    permissions = await _permissions(db, ctx, binding, lock=lock)
    if action:
        customer = await db.get(Customers, binding.customer_id, populate_existing=True)
        if binding.lifecycle != "active" or not customer or customer.status != "closed":
            raise HTTPException(409, "此商家已暂停、停止或当前并非合作状态，不能公开操作")
    if action and not permissions.get("can_" + action): raise HTTPException(403, "此门店尚未授权该项 Google 操作")
    return binding, connection, permissions


def binding_data(binding, permissions):
    return {"id": binding.id, "customer_id": binding.customer_id, "customer_name": binding.customer_name,
            "connection_id": binding.connection_id, "location_name": binding.location_name, "title": binding.title,
            "address": binding.address, "active": binding.active, "revision": binding.revision, "permissions": permissions,
            "lifecycle": binding.lifecycle if binding.active else "stopped", "primary_operator_id": binding.primary_operator_id, "primary_operator_name": binding.primary_operator_name}


def _public_post_configuration(payload):
    """Project frozen public fields only; dates remain Google's local wall time."""
    if type(payload) is not dict or type(payload.get("topicType")) is not str or payload["topicType"] not in {"STANDARD", "EVENT", "OFFER"}:
        return None
    date = {"year": (int, 1, 9999), "month": (int, 1, 12), "day": (int, 1, 31)}
    time = {"hours": (int, 0, 23), "minutes": (int, 0, 59), "seconds": (int, 0, 59), "nanos": (int, 0, 999999999)}
    schema = {"topicType": (str, 16),
              "event": {"title": (str, 200), "schedule": {"startDate": date, "startTime": time, "endDate": date, "endTime": time}},
              "offer": {"couponCode": (str, 100), "redeemOnlineUrl": (str, 2048), "termsConditions": (str, 5000)},
              "callToAction": {"actionType": (str, 16), "url": (str, 2048)}}

    def project(value, fields):
        if type(value) is not dict:
            return {}
        result = {}
        for key, expected in fields.items():
            item = value.get(key)
            if type(expected) is dict:
                if type(item) is dict:
                    result[key] = project(item, expected)
            elif type(item) is expected[0]:
                if expected[0] is str and len(item) <= expected[1]:
                    result[key] = item
                elif expected[0] is int and expected[1] <= item <= expected[2]:
                    result[key] = item
        return result

    return project(payload, schema)


def action_data(action, ctx):
    retained = type(action.payload) is dict and action.created_at is not None and aware(action.created_at) >= now() - timedelta(days=30)
    return {"id": action.id, "binding_id": action.binding_id, "customer_id": action.customer_id, "kind": action.kind,
            "request_id": action.request_id, "task_id": action.task_id, "status": action.status, "actor_name": action.actor_name,
            "created_at": iso(action.created_at), "updated_at": iso(action.updated_at), "provider_state": action.provider_state,
            "provider_url": provider.public_result_url(action.provider_url), "message": action.message, "confirmed_at": iso(action.confirmed_at),
            "can_reconcile": action.status in {"pending", "unknown", "accepted"},
            "content": (action.payload.get("comment") or action.payload.get("summary")) if retained else None,
            "publication_payload": _public_post_configuration(action.payload) if retained and action.kind == "post_publish" else None}


async def action_data_with_image(db, action, ctx):
    from services import media_publication_images as images
    return {**action_data(action, ctx), **(await images.submitted_image_data(db, ctx, action))}


async def _audit(db, ctx, binding, kind, payload):
    db.add(Action(binding_id=binding.id, customer_id=binding.customer_id, kind=kind, request_id=str(uuid4()), fingerprint=digest(payload),
                  actor_id=ctx.identity, actor_name=ctx.user.name or str(ctx.identity), payload=payload, status="succeeded", message="授权配置已更新", created_at=now(), updated_at=now()))


async def _expire_payloads(db):
    from models.google_business import GoogleBusinessAIDraft
    await db.execute(update(GoogleBusinessAIDraft).where(GoogleBusinessAIDraft.expires_at < now()).values(reply_text="", approved_reply_hash=None).execution_options(synchronize_session=False))
    # Retain only locally authored outbound text for 30 days; never cache review originals.
    await db.execute(update(Action).where(Action.created_at < now() - timedelta(days=30), Action.payload.is_not(None)).values(payload=None).execution_options(synchronize_session=False))
    await db.execute(update(OAuthState).where(OAuthState.expires_at < now(), OAuthState.verifier_encrypted != "").values(verifier_encrypted="", consumed=True).execution_options(synchronize_session=False))


async def status(db, user):
    ctx = await context(db, user)
    _, missing = provider.settings()
    bindings = []
    for row in (await db.execute(select(Binding).where(Binding.active.is_(True)).order_by(Binding.customer_name, Binding.id))).scalars():
        try:
            _, _, permissions = await _binding(db, ctx, row.id)
            bindings.append(binding_data(row, permissions))
        except HTTPException as exc:
            if exc.status_code not in {403, 404}: raise
    connections = []
    if ctx.owner:
        for row in (await db.execute(select(Connection).where(Connection.owner_id == ctx.identity).order_by(Connection.id.desc()))).scalars():
            connections.append({"id": row.id, "label": row.label, "active": row.active, "needs_reconnect": row.needs_reconnect,
                                "connected_at": iso(row.connected_at), "last_error": MESSAGES.get(row.last_error) if row.last_error else None})
    return {"enabled": provider.enabled(), "configured": not missing, "setup_missing": missing if ctx.owner else [], "is_owner": ctx.owner,
            "connections": connections, "bindings": bindings}


async def options(db, user):
    await context(db, user, owner=True)
    old = await media.options(db, user)
    return {"customers": [{"id": x["id"], "name": x["name"]} for x in old["customers"]], "assignees": old["assignees"]}


async def oauth_start(db, user, reconnect_connection_id=None):
    ctx = await context(db, user, owner=True)
    provider.require_config()
    state, cookie, verifier = secrets.token_urlsafe(40), secrets.token_urlsafe(40), secrets.token_urlsafe(64)
    async with write(db):
        await _expire_payloads(db)
        if reconnect_connection_id is not None:
            target = await db.get(Connection, reconnect_connection_id, populate_existing=True)
            if not target or target.owner_id != ctx.identity: raise HTTPException(404, "原 Google 连接不存在")
        active = await db.scalar(select(func.count()).select_from(Connection).where(Connection.owner_id == ctx.identity, Connection.active.is_(True)))
        if active >= 20 and reconnect_connection_id is None: raise HTTPException(409, "请先断开不再使用的 Google 连接")
        db.add(OAuthState(state_hash=hash_text(state), cookie_hash=hash_text(cookie), owner_id=ctx.identity, verifier_encrypted=provider.encrypt({"verifier": verifier}), expires_at=now() + timedelta(minutes=10), consumed=False, created_at=now(), reconnect_connection_id=reconnect_connection_id))
    return {"authorization_url": provider.authorize_url(state, verifier), "expires_in": 600}, cookie


async def oauth_callback(db, state, cookie, code):
    provider.require_config()
    if not isinstance(state, str) or len(state) > 200 or not isinstance(cookie, str) or len(cookie) > 200 or not isinstance(code, str) or not 1 <= len(code) <= 4096:
        raise HTTPException(400, "Google 授权验证失败，请重新连接")
    async with write(db):
        row = (await db.execute(select(OAuthState).where(OAuthState.state_hash == hash_text(state)).with_for_update())).scalar_one_or_none()
        if not row or row.consumed or aware(row.expires_at) < now() or not hmac.compare_digest(row.cookie_hash, hash_text(cookie)):
            raise HTTPException(400, "Google 授权已过期或已使用，请重新连接")
        owner = await db.get(Employees, row.owner_id)
        if not owner or owner.status not in {"active", "probation"} or normalized_role(SimpleNamespace(role=owner.role)) != "super_admin":
            raise HTTPException(403, "老板账号状态已变更，请重新登录")
        owner_id = row.owner_id
        reconnect_connection_id = row.reconnect_connection_id
        verifier = provider.decrypt(row.verifier_encrypted)["verifier"]
        row.consumed = True; row.verifier_encrypted = ""
    client = provider.GoogleClient()
    tokens = await client.exchange(code, verifier)
    async with write(db):
        owner = await db.get(Employees, owner_id, populate_existing=True)
        if not owner or owner.status not in {"active", "probation"} or normalized_role(SimpleNamespace(role=owner.role)) != "super_admin": raise HTTPException(403, "老板账号已失效")
        if reconnect_connection_id is not None:
            connection = await db.get(Connection, reconnect_connection_id, populate_existing=True)
            if not connection or connection.owner_id != owner_id: raise HTTPException(404, "原 Google 连接已变化")
            connection.token_encrypted = provider.encrypt(tokens); connection.active = True
            connection.needs_reconnect = False; connection.last_error = None; connection.connected_at = now()
        else:
            connection = Connection(owner_id=owner_id, label="Google 商家连接", token_encrypted=provider.encrypt(tokens), active=True, needs_reconnect=False, connected_at=now())
            db.add(connection); await db.flush()
            connection.label = "Google 商家连接 #" + str(connection.id)
    return True


async def _read_provider(db, user, connection_id, method, *args, binding_id=None):
    # Ordinary Google GETs may take several pages. Do not hold SQLite's writer
    # lock (or even a read transaction) while waiting for the external provider.
    ctx = await context(db, user, owner=binding_id is None)
    if binding_id is not None:
        _, connection, _ = await _binding(db, ctx, binding_id)
        if connection.id != connection_id: raise HTTPException(409, "门店连接已更新，请重新读取")
    else:
        connection = await _connection(db, ctx, connection_id)
    original_token = connection.token_encrypted
    detached = SimpleNamespace(active=connection.active, needs_reconnect=connection.needs_reconnect, token_encrypted=original_token)
    await db.commit()
    failure = None
    result = None
    try:
        result = await getattr(provider.GoogleClient(detached), method)(*args)
    except provider.ProviderError as exc:
        failure = exc
    async with write(db):
        ctx = await context(db, user, owner=binding_id is None)
        if binding_id is not None:
            _, current, _ = await _binding(db, ctx, binding_id, lock=True)
            if current.id != connection_id: raise HTTPException(409, "门店连接已更新，请重新读取")
        else:
            current = await _connection(db, ctx, connection_id, lock=True)
        # A concurrent successful refresh/reconnect must never be overwritten by
        # a late stale refresh or a stale invalid-grant response.
        if current.token_encrypted == original_token:
            if detached.token_encrypted != original_token:
                current.token_encrypted = detached.token_encrypted
            if failure is not None:
                current.last_error = failure.code
                if failure.code == "reconnect_required": current.needs_reconnect = True
            elif not current.needs_reconnect:
                current.last_error = None
        await _expire_payloads(db)
    if failure is not None: raise HTTPException(503, MESSAGES.get(failure.code, MESSAGES["provider_unavailable"]))
    return result


async def locations(db, user, connection_id):
    return await _read_provider(db, user, connection_id, "locations")


async def bind(db, user, *, request_id, customer_id, connection_id, location_name):
    ctx = await context(db, user, owner=True); request_id = media._key(request_id)
    if not provider.LOCATION.fullmatch(location_name): raise HTTPException(422, "请选择已授权的 Google 门店")
    prior = await db.scalar(select(Binding).where(Binding.request_id == request_id))
    if prior:
        if (prior.customer_id, prior.connection_id, prior.location_name, prior.created_by_id) != (customer_id, connection_id, location_name, ctx.identity): raise HTTPException(409, "同一请求编号对应了不同绑定")
        if not prior.active: raise HTTPException(409, "这次绑定已被停用，不能重放旧请求")
        binding, _, permissions = await _binding(db, ctx, prior.id)
        return binding_data(binding, permissions)
    result = await _read_provider(db, user, connection_id, "locations")
    if not any(x["location_name"] == location_name for x in result["items"]): raise HTTPException(422, "此 Google 门店未在当前授权列表中，请重新读取后选择")
    async with write(db):
        ctx = await context(db, user, owner=True)
        customer, _ = await media._customer(db, ctx, customer_id, write=True)
        connection = await _connection(db, ctx, connection_id, lock=True)
        if customer.status != "closed": raise HTTPException(409, "请先确认该客户仍处于合作已成交状态")
        prior = await db.scalar(select(Binding).where(Binding.request_id == request_id))
        if prior:
            if (prior.customer_id, prior.connection_id, prior.location_name, prior.created_by_id) != (customer_id, connection_id, location_name, ctx.identity): raise HTTPException(409, "同一请求编号对应了不同绑定")
            return binding_data(prior, {"can_read": True, "can_reply": True, "can_publish": True, "can_manage": True})
        # Discovery was live and exact. Google titles/addresses are never retained as a cache.
        existing_rows = (await db.execute(select(Binding).where((Binding.customer_id == customer_id) | (Binding.location_id == location_name.rsplit("/", 1)[1])).with_for_update())).scalars().all()
        if len(existing_rows) > 1: raise HTTPException(409, "客户或 Google 门店已有其他绑定，请先核对归属")
        existing = existing_rows[0] if existing_rows else None
        if existing:
            if existing.active or existing.customer_id != customer_id or existing.location_name != location_name: raise HTTPException(409, "客户或 Google 门店已有绑定，请先核对归属")
            existing.connection_id = connection_id; existing.active = True; existing.lifecycle = "active"; existing.primary_operator_id = None; existing.primary_operator_name = None; existing.revision += 1; existing.request_id = request_id
            existing.title = customer.business_name; existing.address = ""; existing.customer_name = customer.business_name
            row = existing
        else:
            row = Binding(customer_id=customer_id, customer_name=customer.business_name, connection_id=connection_id, location_name=location_name, location_id=location_name.rsplit("/", 1)[1],
                          title=customer.business_name, address="", active=True, revision=1, request_id=request_id, created_by_id=ctx.identity, created_at=now())
            db.add(row); await db.flush()
        await _audit(db, ctx, row, "binding_created", {"location_name": location_name, "connection_id": connection_id})
        output = binding_data(row, {"can_read": True, "can_reply": True, "can_publish": True, "can_manage": True})
    return output


async def grants(db, user, binding_id):
    ctx = await context(db, user, owner=True)
    binding, _, permissions = await _binding(db, ctx, binding_id)
    old = await media.options(db, user)
    eligible = {x["id"]: x for x in old["assignees"] if binding.customer_id in x.get("eligible_customer_ids", [])}
    rows = (await db.execute(select(Grant).where(Grant.binding_id == binding_id))).scalars().all()
    grant_map = {x.employee_id: x for x in rows}
    ids = set(eligible) | set(grant_map)
    employees = (await db.execute(select(Employees).where(Employees.id.in_(ids)).order_by(Employees.name))).scalars().all() if ids else []
    return {"binding": binding_data(binding, permissions), "revision": binding.revision, "employees": [{"employee_id": x.id, "name": x.name,
            "eligible": x.id in eligible and normalized_role(SimpleNamespace(role=x.role)) != "super_admin", "can_reply": bool(grant_map.get(x.id) and grant_map[x.id].can_reply),
            "can_publish": bool(grant_map.get(x.id) and grant_map[x.id].can_publish)} for x in employees if x.id != ctx.identity]}


async def set_grant(db, user, binding_id, *, expected_revision, employee_id, can_reply, can_publish):
    ctx = await context(db, user, owner=True)
    async with write(db):
        binding, _, _ = await _binding(db, ctx, binding_id, lock=True)
        if binding.revision != expected_revision: raise HTTPException(409, "Google 授权已被更新，请刷新后重试")
        row = await db.scalar(select(Grant).where(Grant.binding_id == binding_id, Grant.employee_id == employee_id).with_for_update())
        if can_reply or can_publish:
            if binding.lifecycle != "active": raise HTTPException(409, "请先恢复商家，再重新授权运营")
            customer, _ = await media._customer(db, ctx, binding.customer_id, write=True)
            if customer.status != "closed": raise HTTPException(409, "请先确认客户仍在合作，再重新授权")
            await media._assignee(db, ctx, customer, employee_id)
            employee = await db.get(Employees, employee_id)
            if not employee or normalized_role(SimpleNamespace(role=employee.role)) == "super_admin": raise HTTPException(422, "老板已有完整权限，无需额外授权")
        elif not row:
            raise HTTPException(404, "该员工尚无 Google 操作授权")
        before = {"can_reply": bool(row and row.can_reply), "can_publish": bool(row and row.can_publish)}
        if not row:
            row = Grant(binding_id=binding_id, employee_id=employee_id, granted_by_id=ctx.identity); db.add(row)
        row.can_reply = can_reply; row.can_publish = can_publish; row.granted_by_id = ctx.identity; row.updated_at = now()
        binding.revision += 1
        if not can_publish and binding.primary_operator_id == employee_id:
            from services.google_business_management import cancel_binding_schedules
            await cancel_binding_schedules(db, binding.id, message="主运营的发布权限已撤销，原排期已取消")
        if not can_reply and not can_publish and binding.primary_operator_id == employee_id:
            binding.primary_operator_id = None; binding.primary_operator_name = None
            from services.google_business_management import cancel_binding_schedules
            await cancel_binding_schedules(db, binding.id)
        await _audit(db, ctx, binding, "grant_updated", {"employee_id": employee_id, "before": before, "after": {"can_reply": can_reply, "can_publish": can_publish}})
    return await grants(db, user, binding_id)


async def disconnect_binding(db, user, binding_id, expected_revision):
    ctx = await context(db, user, owner=True)
    async with write(db):
        binding, _, _ = await _binding(db, ctx, binding_id, lock=True)
        if binding.revision != expected_revision: raise HTTPException(409, "门店配置已更新，请刷新后重试")
        from services.google_business_management import cancel_binding_schedules
        await cancel_binding_schedules(db, binding.id)
        await _audit(db, ctx, binding, "binding_disconnected", {"revision": binding.revision})
        binding.active = False; binding.lifecycle = "stopped"; binding.primary_operator_id = None; binding.primary_operator_name = None; binding.revision += 1
        await db.execute(update(Grant).where(Grant.binding_id == binding.id).values(can_reply=False, can_publish=False, updated_at=now()))
    return {"disconnected": True}


async def disconnect_connection(db, user, connection_id):
    ctx = await context(db, user, owner=True)
    async with write(db):
        connection = await _connection(db, ctx, connection_id, lock=True)
        bindings = (await db.execute(select(Binding).where(Binding.connection_id == connection.id, Binding.active.is_(True)).with_for_update())).scalars().all()
        for binding in bindings:
            await _audit(db, ctx, binding, "connection_disconnected", {"connection_id": connection.id})
            binding.active = False; binding.lifecycle = "stopped"; binding.primary_operator_id = None; binding.primary_operator_name = None; binding.revision += 1
            from services.google_business_management import cancel_binding_schedules
            await cancel_binding_schedules(db, binding.id)
            await db.execute(update(Grant).where(Grant.binding_id == binding.id).values(can_reply=False, can_publish=False, updated_at=now()))
        connection.active = False; connection.token_encrypted = None; connection.needs_reconnect = False
    return {"disconnected": True}


def review_version(row):
    return digest({"name": row.get("name"), "updateTime": row.get("updateTime"), "reply": row.get("reviewReply")})


def review_data(row, location):
    from services.google_business_ai import risk_flags
    name = row.get("name", "")
    if not isinstance(name, str) or not name.startswith(location + "/reviews/") or not provider.REVIEW.fullmatch(name): return None
    reply = row.get("reviewReply") or {}
    return {"name": name, "reviewer_name": str((row.get("reviewer") or {}).get("displayName") or "Google 用户")[:255], "rating": str(row.get("starRating") or ""),
            "comment": str(row.get("comment") or "")[:20000], "created_at": row.get("createTime"), "updated_at": row.get("updateTime"),
            "reply": str(reply.get("comment") or "")[:4096], "reply_updated_at": reply.get("updateTime"), "reply_state": reply.get("reviewReplyState") or None, "requires_owner_review": bool(risk_flags(row)), "version": review_version(row)}


async def reviews(db, user, binding_id, page_token=None):
    ctx = await context(db, user)
    binding, connection, _ = await _binding(db, ctx, binding_id)
    location_name, connection_id = binding.location_name, connection.id
    data = await _read_provider(db, user, connection_id, "reviews", location_name, page_token, binding_id=binding_id)
    items = [x for x in (review_data(r, location_name) for r in data.get("reviews", [])) if x]
    return {"items": items, "next_page_token": data.get("nextPageToken"), "fetched_at": iso(now())}


async def review(db, user, binding_id, review_name):
    # Google's list and single-review resources can expose different reply
    # metadata. Prepare an edit from the authoritative GET representation;
    # generation and dispatch still compare the complete unchanged version.
    ctx = await context(db, user)
    binding, connection, _ = await _binding(db, ctx, binding_id, action="reply")
    if not isinstance(review_name, str) or not provider.REVIEW.fullmatch(review_name) or not review_name.startswith(binding.location_name + "/reviews/"):
        raise HTTPException(422, "请选择当前门店的评论")
    connection_id = connection.id
    raw = await _read_provider(db, user, connection_id, "review", review_name, binding_id=binding_id)
    # A read may outlive the employee's reply grant. Read-only access at the
    # provider seam does not authorize delivering an editable reply context.
    ctx = await context(db, user)
    binding, connection, _ = await _binding(db, ctx, binding_id, action="reply")
    if connection.id != connection_id or not isinstance(raw, dict) or raw.get("name") != review_name:
        raise HTTPException(409, "评论或门店连接已变化，请重新读取后处理")
    item = review_data(raw, binding.location_name)
    if item is None:
        raise HTTPException(409, "评论已不属于当前门店，请重新读取后处理")
    return {"item": item, "fetched_at": iso(now())}


async def _post_payload(db, ctx, binding, task_id, expected_revision=None):
    task, customer, _ = await media._get_task(db, ctx, task_id, write=True)
    await db.execute(select(MediaOperationTask).where(MediaOperationTask.id == task_id).with_for_update())
    await db.refresh(task)
    if task.customer_id != binding.customer_id or task.platform != "google_business" or task.status != "ready": raise HTTPException(422, "请选择此客户已审核、待发布的 Google 运营任务")
    if expected_revision is not None and task.revision != expected_revision: raise HTTPException(409, "运营任务已更新，请重新读取后发布")
    approval = await db.scalar(select(MediaOperationEvent).where(MediaOperationEvent.task_id == task.id, MediaOperationEvent.action == "approve", MediaOperationEvent.after_status == "ready").order_by(MediaOperationEvent.revision.desc()).limit(1))
    snapshot = approval.snapshot if approval and isinstance(approval.snapshot, dict) else {}
    if not approval or snapshot.get("content") != task.content or snapshot.get("material_id") != task.material_id:
        raise HTTPException(422, "未找到与当前内容一致的老板审核记录，请退回并重新审核")
    publication = await media.publication_for_task(db, task)
    # Legacy approvals predate publication settings: their exact STANDARD
    # payload remains valid. Explicit settings, including their wall-time zone,
    # must match the immutable approval snapshot on every dispatch/schedule.
    if "publication" in snapshot:
        if snapshot["publication"] != publication or snapshot.get("timezone") != task.timezone:
            raise HTTPException(422, "发布类型、活动时间、链接或商家时区已变化，请退回并重新审核")
    elif publication != media.DEFAULT_PUBLICATION:
        raise HTTPException(422, "当前发布配置尚未审核，请退回并重新审核")
    content = (task.content or "").strip()
    if not content or len(content) > 1500: raise HTTPException(422, "Google 帖子内容需为 1—1500 字，请修改草稿并重新审核")
    payload = {"languageCode": "en-US", "summary": content}
    payload.update(media.publication_payload(publication, task.timezone))
    has_image = False
    from services import media_publication_images as images
    prepared_image = await images.approved_image(db, ctx, binding, task, snapshot)
    if prepared_image is not None:
        payload["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": images.delivery_url(prepared_image)}]
        has_image = True
    elif task.material_id is not None:
        material = await media._material(db, ctx, customer, task.material_id, proof=True)
        await db.refresh(material)
        reference_hash = media._hash({"id": material.id, "customer_id": material.customer_id, "file_url": material.file_url,
                                      "content_type": material.content_type, "updated_at": media._iso(material.updated_at)})
        if not snapshot.get("google_material_fingerprint") or snapshot["google_material_fingerprint"] != reference_hash:
            raise HTTPException(422, "图片引用未经过当前版本审核或已发生变化，请退回并重新审核；系统不会发布更换后的图片")
        url = provider.public_image_url(material.file_url)
        if not url: raise HTTPException(422, "该任务图片不是可公开读取的 HTTPS 图片，请换用公开图片素材并重新审核；私人附件不会对外开放")
        payload["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": url}]; has_image = True
    return task, payload, has_image


async def ready_tasks(db, user, binding_id):
    ctx = await context(db, user)
    binding, _, _ = await _binding(db, ctx, binding_id, action="publish")
    published_tasks = select(Action.task_id).where(Action.task_id.is_not(None), Action.kind == "post_publish", Action.status.in_(("pending", "unknown", "accepted", "succeeded")))
    query = select(MediaOperationTask).where(MediaOperationTask.customer_id == binding.customer_id, MediaOperationTask.platform == "google_business", MediaOperationTask.status == "ready", ~MediaOperationTask.id.in_(published_tasks)).order_by(MediaOperationTask.due_at)
    if not ctx.owner: query = query.where(MediaOperationTask.assignee_id == ctx.identity)
    rows = (await db.execute(query.limit(100))).scalars().all()
    output = []
    _, customer_permissions = await media._customer(db, ctx, binding.customer_id)
    from services import media_publication_images as images
    task_images = await images.task_images_data(db, ctx, rows, {binding.customer_id: customer_permissions})
    for task in rows:
        preview_url = None; material_title = None; blocked = None; publication = None
        publication_image = task_images[task.id]
        try:
            publication = await media.publication_for_task(db, task)
            _, payload, _ = await _post_payload(db, ctx, binding, task.id, task.revision)
            media_items = payload.get("media") or []
            # The capability URL is never a browser preview or a task DTO.
            preview_url = media_items[0]["sourceUrl"] if media_items and publication_image is None else None
            material_title = task.material_title if preview_url or publication_image else None
        except HTTPException as exc:
            blocked = str(exc.detail)
        output.append({"id": task.id, "title": task.title, "content": task.content, "revision": task.revision,
                       "publication": publication, "timezone": task.timezone,
                       "material_id": task.material_id if preview_url or publication_image else None, "material_title": material_title,
                       "has_public_image": bool(preview_url or publication_image and not blocked), "preview_image_url": preview_url,
                       "preview_image_path": publication_image["preview_path"] if publication_image else None,
                       "image_version_id": publication_image["id"] if publication_image else None,
                       "image_sha256": publication_image["image_sha256"] if publication_image else None,
                       "publication_image": publication_image, "publish_blocked_reason": blocked, "can_return": ctx.owner})
    return {"items": output, "total": len(output)}


def _reply_result(action, data):
    if data.get("comment") != (action.payload or {}).get("comment"):
        action.status = "unknown"; action.message = "Google 当前回复尚未匹配，请老板核对；系统不会重新发送"; return
    state = str(data.get("reviewReplyState") or "")
    action.provider_state = state or None
    if state == "APPROVED": action.status = "succeeded"; action.message = "Google 已确认评论回复通过审核"
    elif state == "REJECTED": action.status = "rejected"; action.message = "Google 未批准此回复，请检查内容政策和门店状态"
    else: action.status = "accepted"; action.message = "Google 已保存回复，公开审核状态尚待确认，请稍后查询"


def _post_result(action, data, location):
    name = data.get("name", "")
    if not isinstance(name, str) or not name.startswith(location + "/localPosts/") or not provider.POST.fullmatch(name):
        action.status = "unknown"; action.message = "Google 返回了未能核实的帖子编号，请查询结果"; return
    action.provider_name = name
    state = str(data.get("state") or ""); action.provider_state = state or None
    action.provider_url = provider.public_result_url(data.get("searchUrl"))
    if state == "LIVE": action.status = "succeeded"; action.message = "Google 已确认帖子上线"
    elif state == "REJECTED": action.status = "rejected"; action.message = "Google 拒绝发布，请检查内容政策和门店状态"
    else: action.status = "accepted"; action.message = "Google 已接收，尚未确认公开上线，请稍后查询"


async def _reserve(db, ctx, binding_id, kind, request_id, payload, *, target_name=None, task_id=None, expected_revision=None, expected_version=None, approval_id=None):
    request_id = media._key(request_id)
    fingerprint = digest({"binding_id": binding_id, "kind": kind, "payload": payload, "target": target_name, "task_id": task_id, "expected_revision": expected_revision, "expected_version": expected_version, "approval_id": approval_id})
    async with write(db):
        binding, _, _ = await _binding(db, ctx, binding_id, action="reply" if kind == "review_reply" else "publish", lock=True)
        old = await db.scalar(select(Action).where(Action.actor_id == ctx.identity, Action.request_id == request_id))
        if old:
            if old.fingerprint != fingerprint: raise HTTPException(409, "同一请求编号对应不同操作，请先核对原结果")
            return old.id, False
        await _expire_payloads(db)
        if kind == "post_publish":
            await _post_payload(db, ctx, binding, task_id, expected_revision)
            duplicate = await db.scalar(select(Action).where(Action.task_id == task_id, Action.kind == kind, Action.status.in_(("pending", "unknown", "accepted", "succeeded"))).limit(1))
            if duplicate: raise HTTPException(409, "此任务已有发布请求，请先查询原发布结果，避免重复发帖")
        else:
            duplicate = await db.scalar(select(Action).where(Action.binding_id == binding_id, Action.target_name == target_name, Action.kind == kind, Action.status.in_(("pending", "unknown"))).limit(1))
            if duplicate: raise HTTPException(409, "此评论已有结果待确认的回复，请先查询，避免覆盖")
        row = Action(binding_id=binding_id, customer_id=binding.customer_id, kind=kind, request_id=request_id, fingerprint=fingerprint,
                     actor_id=ctx.identity, actor_name=ctx.user.name or str(ctx.identity), task_id=task_id, target_name=target_name, approval_id=approval_id, payload=payload,
                     status="pending", message="已登记请求，正在向 Google 提交", created_at=now(), updated_at=now())
        db.add(row); await db.flush(); identity = row.id
    return identity, True


async def _sync_schedule_result(db, action):
    # The durable provider result is authoritative. A definite rejection may
    # permit a new, explicitly reviewed schedule; unknown is never retried.
    from models.google_business import GoogleBusinessSchedule as Schedule
    await db.execute(update(Schedule).where(Schedule.action_id == action.id).values(
        status=action.status, message=action.message, updated_at=now(), revision=Schedule.revision + 1)
        .execution_options(synchronize_session=False))


async def _not_dispatched(db, user, action_id, message):
    """Internal failure fence, never an API that can cancel another user's send."""
    async with write(db):
        row = await db.scalar(select(Action).where(Action.id == action_id, Action.actor_id == media._identity(user)).with_for_update().execution_options(populate_existing=True))
        if row and row.status == "pending" and row.dispatch_started_at is None:
            row.status = "failed"; row.message = message; row.updated_at = now()


async def _dispatch(db, user, action_id, *, expected_revision=None, expected_version=None, schedule_id=None):
    # A durable reservation exists before this function. No replay enters here;
    # even a crashed process leaves a fenced action for GET-only reconciliation.
    try:
        ctx = await context(db, user)
        row = await db.get(Action, action_id)
        if not row or row.actor_id != ctx.identity: raise HTTPException(404, "操作记录不存在")
        binding, connection, _ = await _binding(db, ctx, row.binding_id, action="reply" if row.kind == "review_reply" else "publish")
        kind, binding_id, connection_id, target_name = row.kind, row.binding_id, connection.id, row.target_name
        current_review = None
        if kind == "review_reply":
            current_review = await _read_provider(db, user, connection_id, "review", target_name, binding_id=binding_id)
    except HTTPException:
        await _not_dispatched(db, user, action_id, "提交前授权或 Google 状态已变更，本请求未向 Google 发送")
        raise
    denial = None
    snapshot = None
    output = None
    async with write(db):
        row = await db.scalar(select(Action).where(Action.id == action_id).with_for_update().execution_options(populate_existing=True))
        try:
            ctx = await context(db, user)
            binding, connection, _ = await _binding(db, ctx, row.binding_id, action="reply" if row.kind == "review_reply" else "publish", lock=True)
        except HTTPException as exc:
            if row.status == "pending" and row.dispatch_started_at is None:
                row.status = "failed"; row.message = "授权已变更，本请求未向 Google 发送"; row.updated_at = now()
            denial = exc
        if denial is None:
            if row.status != "pending" or row.dispatch_started_at is not None:
                output = await action_data_with_image(db, row, ctx)
            else:
                try:
                    if row.kind == "review_reply":
                        if current_review is None or current_review.get("name") != row.target_name or review_version(current_review) != expected_version:
                            raise HTTPException(409, "评论或回复已被更新，请重新读取后编辑")
                        from services.google_business_ai import ensure_reply_approval
                        await ensure_reply_approval(db, ctx, binding, current_review, (row.payload or {}).get("comment", ""), approval_id=row.approval_id)
                    else:
                        if schedule_id is not None:
                            from services.google_business_scheduler import enabled
                            if not enabled(): raise HTTPException(409, "自动发布调度已关闭，本次不会提交")
                            from models.google_business import GoogleBusinessSchedule as Schedule
                            scheduled = await db.get(Schedule, schedule_id, populate_existing=True)
                            if (not scheduled or scheduled.status != "dispatching" or scheduled.action_id != row.id or scheduled.operator_id != ctx.identity or
                                    binding.primary_operator_id != ctx.identity or scheduled.task_id != row.task_id or scheduled.task_revision != expected_revision or scheduled.payload_fingerprint != digest(row.payload)):
                                raise HTTPException(409, "排期、主运营或内容版本已变化，本次不会发布")
                        dispatch_task, current_payload, _ = await _post_payload(db, ctx, binding, row.task_id, expected_revision)
                        if current_payload != row.payload: raise HTTPException(409, "运营任务素材已更新，请重新审核")
                    # This short committed point defines an already-dispatched
                    # request. Revocation after it cannot retract external HTTP,
                    # but it fences all later requests and all response access.
                    row.dispatch_started_at = now(); row.updated_at = row.dispatch_started_at
                    if row.kind == "post_publish":
                        from services import media_publication_images as images
                        approval = await db.scalar(select(MediaOperationEvent).where(MediaOperationEvent.task_id == dispatch_task.id,
                            MediaOperationEvent.action == "approve", MediaOperationEvent.after_status == "ready")
                            .order_by(MediaOperationEvent.revision.desc()).limit(1))
                        await images.activate_delivery(db, ctx, binding, dispatch_task, approval.snapshot if approval else {}, row)
                    row.message = "已开始向 Google 提交；如需撤销，请先核对本次实际结果"
                    snapshot = {"id": row.id, "marker": iso(row.dispatch_started_at), "fingerprint": row.fingerprint, "kind": row.kind,
                                "payload": dict(row.payload), "target_name": row.target_name, "location_name": binding.location_name,
                                "connection_id": connection.id, "original_token": connection.token_encrypted,
                                "connection": SimpleNamespace(active=connection.active, needs_reconnect=connection.needs_reconnect, token_encrypted=connection.token_encrypted)}
                except HTTPException as exc:
                    row.status = "failed"; row.message = str(exc.detail); row.updated_at = now()
                    output = await action_data_with_image(db, row, ctx)
    if denial is not None: raise denial
    if snapshot is None: return output
    # Never hold an application DB transaction while awaiting Google. An
    # unrelated financial write must remain possible during a slow PUT/POST.
    result_state = SimpleNamespace(payload=snapshot["payload"], status="unknown", provider_name=None, provider_state=None,
                                   provider_url=None, message="提交结果待确认，请查询原请求；系统不会重复发送")
    provider_error = None
    try:
        client = provider.GoogleClient(snapshot["connection"])
        if snapshot["kind"] == "review_reply":
            result = await client.reply(snapshot["target_name"], snapshot["payload"])
            _reply_result(result_state, result)
        else:
            result = await client.publish(snapshot["location_name"], snapshot["payload"])
            _post_result(result_state, result, snapshot["location_name"])
    except provider.ProviderError as exc:
        provider_error = exc
        result_state.status = "unknown" if exc.uncertain else "failed"
        result_state.message = "提交结果待确认，请查询原请求；系统不会重复发送" if exc.uncertain else MESSAGES.get(exc.code, MESSAGES["provider_unavailable"])
    except HTTPException:
        result_state.status = "failed"; result_state.message = "连接配置已变更，本次未向 Google 提交"
    except Exception:
        # Unknown transport/response failure cannot authorize another write.
        result_state.status = "unknown"; result_state.message = "提交结果待确认，请查询原请求；系统不会重复发送"
    denial = None
    async with write(db):
        row = await db.scalar(select(Action).where(Action.id == snapshot["id"]).with_for_update().execution_options(populate_existing=True))
        if not row or row.fingerprint != snapshot["fingerprint"] or iso(row.dispatch_started_at) != snapshot["marker"]:
            raise HTTPException(409, "Google 操作记录已变化，请重新读取原请求")
        if row.status in {"pending", "unknown", "accepted"}:
            for field in ("status", "provider_name", "provider_state", "provider_url", "message"):
                setattr(row, field, getattr(result_state, field))
            row.updated_at = now()
            if row.status == "succeeded" and row.confirmed_at is None: row.confirmed_at = now()
            await _sync_schedule_result(db, row)
        connection = await db.get(Connection, snapshot["connection_id"], populate_existing=True)
        if connection and connection.active and connection.token_encrypted == snapshot["original_token"]:
            if snapshot["connection"].token_encrypted != snapshot["original_token"]:
                connection.token_encrypted = snapshot["connection"].token_encrypted
            if provider_error and provider_error.code == "reconnect_required":
                connection.needs_reconnect = True; connection.last_error = provider_error.code
        try:
            ctx = await context(db, user)
            await _binding(db, ctx, row.binding_id, action="reply" if row.kind == "review_reply" else "publish", lock=True)
            output = await action_data_with_image(db, row, ctx)
        except HTTPException as exc:
            # Keep the real platform result for the owner, but never reveal it
            # through an invitation that was revoked while HTTP was in flight.
            denial = exc
    if denial is not None: raise denial
    return output


async def reply(db, user, binding_id, *, request_id, review_name, expected_version, reply, approval_id=None):
    ctx = await context(db, user); provider.require_config()
    binding, _, _ = await _binding(db, ctx, binding_id, action="reply")
    if not provider.REVIEW.fullmatch(review_name) or not review_name.startswith(binding.location_name + "/reviews/"): raise HTTPException(422, "评论不属于此 Google 门店")
    value = reply.strip()
    if not value or len(value.encode("utf-8")) > 4096: raise HTTPException(422, "Google 回复最多 4096 UTF-8 字节，请缩短后提交")
    identity, fresh = await _reserve(db, ctx, binding_id, "review_reply", request_id, {"comment": value}, target_name=review_name, expected_version=expected_version, approval_id=approval_id)
    if not fresh: return await action(db, user, identity)
    return await _dispatch(db, user, identity, expected_version=expected_version)


async def publish(db, user, binding_id, *, request_id, task_id, expected_revision):
    ctx = await context(db, user); provider.require_config()
    binding, _, _ = await _binding(db, ctx, binding_id, action="publish")
    _, payload, _ = await _post_payload(db, ctx, binding, task_id, expected_revision)
    identity, fresh = await _reserve(db, ctx, binding_id, "post_publish", request_id, payload, task_id=task_id, expected_revision=expected_revision)
    if not fresh: return await action(db, user, identity)
    return await _dispatch(db, user, identity, expected_revision=expected_revision)


async def action(db, user, action_id):
    ctx = await context(db, user)
    row = await db.get(Action, action_id)
    if not row or row.kind not in {"review_reply", "post_publish"}: raise HTTPException(404, "Google 操作记录不存在")
    await _binding(db, ctx, row.binding_id)
    return await action_data_with_image(db, row, ctx)


async def request_action(db, user, request_id):
    ctx = await context(db, user); request_id = media._key(request_id)
    row = await db.scalar(select(Action).where(Action.actor_id == ctx.identity, Action.request_id == request_id, Action.kind.in_(("review_reply", "post_publish"))))
    if not row: raise HTTPException(404, "尚未查到此请求，请保留原请求编号并稍后再查")
    await _binding(db, ctx, row.binding_id)
    return await action_data_with_image(db, row, ctx)


async def actions(db, user, binding_id):
    ctx = await context(db, user)
    await _binding(db, ctx, binding_id)
    rows = (await db.execute(select(Action).where(Action.binding_id == binding_id, Action.kind.in_(("review_reply", "post_publish"))).order_by(Action.id.desc()).limit(50))).scalars().all()
    return {"items": [await action_data_with_image(db, row, ctx) for row in rows]}


async def reconcile(db, user, action_id):
    ctx = await context(db, user); provider.require_config()
    row = await db.get(Action, action_id)
    if not row or row.kind not in {"review_reply", "post_publish"}: raise HTTPException(404, "Google 操作记录不存在")
    binding, connection, _ = await _binding(db, ctx, row.binding_id, action="reply" if row.kind == "review_reply" else "publish")
    if row.status not in {"pending", "unknown", "accepted"}: return await action_data_with_image(db, row, ctx)
    snapshot = {"kind": row.kind, "status": row.status, "provider_name": row.provider_name, "target_name": row.target_name,
                "updated_at": iso(row.updated_at), "created_at": iso(row.created_at), "payload": dict(row.payload or {}), "binding_id": row.binding_id,
                "connection_id": connection.id, "location_name": binding.location_name}
    result = None; read_error = None
    if snapshot["payload"]:
        if snapshot["kind"] == "review_reply": method, argument = "review", snapshot["target_name"]
        elif snapshot["provider_name"]: method, argument = "post", snapshot["provider_name"]
        else: method, argument = "posts", snapshot["location_name"]
        try:
            result = await _read_provider(db, user, snapshot["connection_id"], method, argument, binding_id=snapshot["binding_id"])
        except HTTPException as exc:
            if exc.status_code != 503: raise
            read_error = str(exc.detail)
    async with write(db):
        ctx = await context(db, user)
        row = await db.scalar(select(Action).where(Action.id == action_id).with_for_update().execution_options(populate_existing=True))
        binding, connection, _ = await _binding(db, ctx, row.binding_id, action="reply" if row.kind == "review_reply" else "publish", lock=True)
        if connection.id != snapshot["connection_id"]: raise HTTPException(409, "门店连接已变更，请重新查询")
        # A late read must not downgrade a newer terminal or reconciled result.
        if row.status not in {"pending", "unknown", "accepted"} or (row.status, row.provider_name, iso(row.updated_at)) != (snapshot["status"], snapshot["provider_name"], snapshot["updated_at"]):
            return await action_data_with_image(db, row, ctx)
        if not snapshot["payload"]:
            row.status = "unknown"; row.message = "操作已超过内容保留期，请老板到 Google 后台人工核对"
        elif read_error:
            row.message = read_error
        elif snapshot["kind"] == "review_reply":
            if result.get("name") != snapshot["target_name"]:
                row.message = "Google 返回的评论编号未能核实，请老板核对"
            else: _reply_result(row, result.get("reviewReply") or {})
        elif snapshot["provider_name"]:
            if result.get("name") != snapshot["provider_name"]:
                row.message = "Google 返回的帖子编号未能核实，请老板核对"
            else: _post_result(row, result, binding.location_name)
        else:
            matches = []
            for item in result.get("localPosts", []):
                try: created = datetime.fromisoformat(str(item.get("createTime", "")).replace("Z", "+00:00"))
                except (ValueError, TypeError): continue
                if abs((aware(created) - datetime.fromisoformat(snapshot["created_at"])).total_seconds()) <= 600 and all(item.get(k) == v for k, v in snapshot["payload"].items()): matches.append(item)
            # Similar content and time are candidates only. Google create has no
            # idempotency token; a lost provider ID never permits a blind retry.
            row.status = "unknown"
            row.message = "发现相近的 Google 帖子，请老板在 Google 后台核对；系统不会自动认领或重复发布" if matches else "尚未找到可核实的 Google 帖子，请老板核对；系统不会重复发布"
        row.updated_at = now()
        if row.status == "succeeded" and row.confirmed_at is None: row.confirmed_at = now()
        await _sync_schedule_result(db, row)
        output = await action_data_with_image(db, row, ctx)
    return output
