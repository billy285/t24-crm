"""Owner-only Meta connection phase. Never publishes or modifies shared ACLs."""
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

from models.customers import Customers
from models.employees import Employees
from models.meta_business import MetaBusinessConnection as Connection, MetaBusinessOAuthState as OAuthState, MetaBusinessAsset as Asset, MetaBusinessBinding as Binding, MetaBusinessRequest as Request
from services import media_operations as media
from services import meta_business_provider as provider
from services.customer_permissions import customer_permissions_for_rows
from services.customers import CustomersService
from services.role_permissions import normalized_role
from services.schema_readiness import require_tables

TABLES = {"meta_business_connections", "meta_business_oauth_states", "meta_business_assets", "meta_business_bindings", "meta_business_requests"}
COOKIE = "__Secure-t24_meta_oauth"
LOCK = int.from_bytes(b"T24META1", "big")
MESSAGES = {"reconnect_required": "Meta 授权已失效，请老板重新连接", "access_denied": "Meta 未开放所需资产或权限，请老板核对", "quota_limited": "Meta 请求额度暂时不足，请稍后读取", "invalid_response": "Meta 返回的资产信息暂无法核实", "provider_unavailable": "Meta 暂时无法连接，请稍后读取", "listing_too_large": "Meta 资产较多，本次尚未完整读取，请分批连接"}


def now(): return datetime.now(timezone.utc)
def aware(value): return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
def iso(value): return aware(value).isoformat() if value else None
def digest(value): return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
def hash_text(value): return hashlib.sha256(str(value).encode()).hexdigest()


async def context(db, user, *, owner=True, lock=False):
    ctx = await media.context(db, user)
    query = select(Employees).where(Employees.id == ctx.identity).execution_options(populate_existing=True)
    if lock: query = query.with_for_update()
    employee = await db.scalar(query)
    if not employee or employee.status not in {"active", "probation"} or normalized_role(SimpleNamespace(role=employee.role)) != normalized_role(user):
        raise HTTPException(403, "当前员工身份已失效，请重新登录")
    await require_tables(db, TABLES)
    if owner and not ctx.owner: raise HTTPException(403, "此阶段仅老板可以连接与绑定 Meta 账号")
    return ctx


@asynccontextmanager
async def write(db):
    try:
        if db.get_bind().dialect.name == "sqlite": await db.execute(text("UPDATE meta_business_requests SET id=id WHERE 0"))
        elif db.get_bind().dialect.name == "postgresql": await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK})
        yield
        await db.commit()
    except (DBAPIError, IntegrityError):
        await db.rollback()
        raise HTTPException(409, "Meta 连接资料正在更新，请读取原结果后再操作") from None
    except BaseException:
        await db.rollback()
        raise


async def _connection(db, ctx, connection_id, *, lock=False, usable=True):
    query = select(Connection).where(Connection.id == connection_id, Connection.owner_id == ctx.identity).execution_options(populate_existing=True)
    if lock: query = query.with_for_update()
    row = await db.scalar(query)
    if not row or (usable and (not row.active or row.needs_reconnect or not row.token_encrypted)):
        raise HTTPException(404, "Meta 连接不存在、已断开或需要重新授权")
    return row


def connection_data(row):
    return {"id": row.id, "label": row.label, "active": row.active, "needs_reconnect": row.needs_reconnect,
            "revision": row.revision, "connected_at": iso(row.connected_at), "last_error": MESSAGES.get(row.last_error) if row.last_error else None,
            "capability_observations": ["Meta 已授予权限：" + scope for scope in row.granted_scopes or []]}


def binding_data(row):
    return {"id": row.id, "customer_id": row.customer_id, "customer_name": row.customer_name,
            "connection_id": row.connection_id, "platform": row.platform, "asset_name": row.asset_name,
            "asset_username": row.asset_username, "active": row.active, "revision": row.revision,
            "publishing_implemented": False, "comments_implemented": False}


async def status(db, user):
    ctx = await context(db, user, owner=False)
    values, missing = provider.settings()
    result = {"enabled": provider.enabled(), "configured": False, "setup_missing": [], "is_owner": ctx.owner,
              "connections": [], "bindings": [], "phase": "connection", "publishing_implemented": False,
              "comments_implemented": False, "capability_observations": [], "authorization": None}
    if not ctx.owner: return result
    result.update(configured=not missing, setup_missing=missing, authorization=provider.authorization_description(values) if not missing else None)
    result["connections"] = [connection_data(row) for row in (await db.scalars(select(Connection).where(Connection.owner_id == ctx.identity).order_by(Connection.id.desc()).limit(100))).all()]
    for row in (await db.scalars(select(Binding).where(Binding.owner_id == ctx.identity).order_by(Binding.customer_name, Binding.id).limit(1000))).all():
        try: await media._customer(db, ctx, row.customer_id)
        except HTTPException as exc:
            if exc.status_code in {403, 404}: continue
            raise
        result["bindings"].append(binding_data(row))
    return result


async def options(db, user):
    ctx = await context(db, user)
    query = select(Customers).where(Customers.status == "closed")
    scope = CustomersService._scope_filter_for_user(user, module="delivery")
    if scope is not None: query = query.where(scope)
    rows = (await db.scalars(query.order_by(Customers.business_name, Customers.id).limit(500))).all()
    permissions = await customer_permissions_for_rows(db, user, rows, config=ctx.config)
    return {"customers": [{"id": row.id, "name": row.business_name} for row in rows if permissions[row.id]["modules"]["delivery"]["read"]]}


async def _invalidate(db, connection_id):
    await db.execute(update(Asset).where(Asset.connection_id == connection_id).values(active=False).execution_options(synchronize_session=False))
    await db.execute(update(Binding).where(Binding.connection_id == connection_id, Binding.active.is_(True))
        .values(active=False, revision=Binding.revision + 1, updated_at=now()).execution_options(synchronize_session=False))


async def _expire_flows(db):
    await db.execute(update(OAuthState).where(OAuthState.expires_at < now(), OAuthState.flow_encrypted != "")
        .values(flow_encrypted="", consumed=True).execution_options(synchronize_session=False))


def _flow(row):
    if row.consumed or aware(row.expires_at) <= now() or not row.flow_encrypted:
        raise HTTPException(409, "本次 Meta 授权已使用或已过期，请先读取连接状态后重新授权")
    try: data = provider.decrypt(row.flow_encrypted)
    except provider.ProviderError: raise HTTPException(409, "授权请求加密配置已变化，请重新核对连接状态") from None
    if set(data) != {"state", "cookie", "configuration"} or data["configuration"] != provider.configuration_fingerprint():
        raise HTTPException(409, "Meta 连接配置已变化，请重新核对授权范围")
    return {"authorization_url": provider.authorize_url(data["state"]), "expires_in": max(1, int((aware(row.expires_at) - now()).total_seconds()))}, data["cookie"]


async def oauth_start(db, user, *, request_id, reconnect_connection_id=None):
    await context(db, user)
    provider.require_config(); key = media._key(request_id)
    fingerprint = digest({"reconnect_connection_id": reconnect_connection_id, "configuration": provider.configuration_fingerprint()})
    async with write(db):
        ctx = await context(db, user, lock=True)
        old = await db.scalar(select(OAuthState).where(OAuthState.owner_id == ctx.identity, OAuthState.request_id == key).execution_options(populate_existing=True))
        if old:
            if old.fingerprint != fingerprint: raise HTTPException(409, "同一授权请求编号对应不同连接或范围")
            return _flow(old)
        await _expire_flows(db)
        target = await _connection(db, ctx, reconnect_connection_id, lock=True, usable=False) if reconnect_connection_id is not None else None
        if target is None and (await db.scalar(select(func.count()).select_from(Connection).where(Connection.owner_id == ctx.identity, Connection.active.is_(True)))) >= 20:
            raise HTTPException(409, "请先断开不再使用的 Meta 连接")
        state, cookie = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
        row = OAuthState(owner_id=ctx.identity, request_id=key, fingerprint=fingerprint, state_hash=hash_text(state), cookie_hash=hash_text(cookie),
            flow_encrypted=provider.encrypt({"state": state, "cookie": cookie, "configuration": provider.configuration_fingerprint()}),
            reconnect_connection_id=target.id if target else None, expected_revision=target.revision if target else None,
            expires_at=now() + timedelta(minutes=10), consumed=False, created_at=now())
        db.add(row); await db.flush(); result = _flow(row)
    return result


async def oauth_request(db, user, request_id):
    ctx = await context(db, user); key = media._key(request_id); provider.require_config()
    row = await db.scalar(select(OAuthState).where(OAuthState.owner_id == ctx.identity, OAuthState.request_id == key))
    if row is None: raise HTTPException(404, "尚未找到本次授权请求，可保留原编号重新确认")
    return _flow(row)


async def oauth_callback(db, state, cookie, code):
    provider.require_config()
    if not all(isinstance(x, str) and 1 <= len(x) <= bound for x, bound in ((state, 200), (cookie, 200), (code, 4096))):
        raise HTTPException(400, "Meta 授权验证失败，请重新连接")
    async with write(db):
        row = await db.scalar(select(OAuthState).where(OAuthState.state_hash == hash_text(state)).with_for_update().execution_options(populate_existing=True))
        if not row or not hmac.compare_digest(row.cookie_hash, hash_text(cookie)): raise HTTPException(400, "Meta 授权验证失败")
        _flow(row)
        owner = await db.get(Employees, row.owner_id, populate_existing=True)
        if not owner or owner.status not in {"active", "probation"} or normalized_role(SimpleNamespace(role=owner.role)) != "super_admin":
            raise HTTPException(403, "老板账号已失效，请重新登录")
        actor = SimpleNamespace(id=str(owner.id), role=owner.role, name=owner.name)
        ctx = await context(db, actor, lock=True)
        owner_id, reconnect_id, expected_revision = row.owner_id, row.reconnect_connection_id, row.expected_revision
        configuration = provider.configuration_fingerprint()
        if reconnect_id is not None:
            original = await _connection(db, ctx, reconnect_id, lock=True, usable=False)
            if original.revision != expected_revision: raise HTTPException(409, "原连接已变化，本次授权不能覆盖较新的操作")
        row.consumed = True; row.flow_encrypted = ""
    # No DB transaction is held during either token exchange or token inspection.
    tokens = await provider.MetaClient().exchange(code)
    async with write(db):
        ctx = await context(db, actor, lock=True)
        if ctx.identity != owner_id: raise HTTPException(403, "授权身份已变化")
        if provider.configuration_fingerprint() != configuration or tokens.get("configuration") != configuration:
            raise HTTPException(409, "Meta 连接配置已变化，本次不会保存旧授权")
        if reconnect_id is not None:
            connection = await _connection(db, ctx, reconnect_id, lock=True, usable=False)
            if connection.revision != expected_revision: raise HTTPException(409, "原连接已变化，本次不会覆盖新状态")
            await _invalidate(db, connection.id)
            connection.token_encrypted = provider.encrypt(tokens); connection.granted_scopes = tokens.get("observed_scopes", [])
            connection.active = True; connection.needs_reconnect = False
            connection.last_error = None; connection.connected_at = now(); connection.revision += 1
        else:
            if (await db.scalar(select(func.count()).select_from(Connection).where(Connection.owner_id == owner_id, Connection.active.is_(True)))) >= 20:
                raise HTTPException(409, "请先断开不再使用的 Meta 连接")
            connection = Connection(owner_id=owner_id, label="Meta 商家连接", token_encrypted=provider.encrypt(tokens), granted_scopes=tokens.get("observed_scopes", []), active=True,
                needs_reconnect=False, revision=1, connected_at=now())
            db.add(connection); await db.flush(); connection.label = "Meta 商家连接 #" + str(connection.id)
    return True


async def _read_assets(db, user, connection_id):
    ctx = await context(db, user)
    connection = await _connection(db, ctx, connection_id)
    revision, token = connection.revision, connection.token_encrypted
    configuration = provider.configuration_fingerprint()
    await db.commit()
    failure = None; result = None
    try: result = await provider.MetaClient(token).assets()
    except provider.ProviderError as exc: failure = exc
    async with write(db):
        ctx = await context(db, user, lock=True)
        connection = await _connection(db, ctx, connection_id, lock=True)
        if connection.revision != revision or connection.token_encrypted != token or provider.configuration_fingerprint() != configuration:
            raise HTTPException(409, "Meta 连接或配置已更新，请重新读取资产")
        if failure:
            connection.last_error = failure.code if failure.code in MESSAGES else "provider_unavailable"
            if failure.code in {"reconnect_required", "access_denied"}:
                connection.needs_reconnect = True; await _invalidate(db, connection.id)
        else: connection.last_error = None
    if failure: raise HTTPException(503, MESSAGES.get(failure.code, MESSAGES["provider_unavailable"]))
    return result, revision


def asset_data(row):
    return {"asset_ref": row.id, "platform": row.platform, "name": row.name, "username": row.username,
            "linked_page_name": row.linked_page_name, "capability_observations": row.observations,
            "publishing_implemented": False, "comments_implemented": False}


async def assets(db, user, connection_id):
    result, revision = await _read_assets(db, user, connection_id)
    output = []
    async with write(db):
        ctx = await context(db, user, lock=True); connection = await _connection(db, ctx, connection_id, lock=True)
        if connection.revision != revision: raise HTTPException(409, "连接已变化，请重新读取")
        await db.execute(update(Asset).where(Asset.connection_id == connection_id).values(active=False).execution_options(synchronize_session=False))
        for item in result["items"]:
            row = Asset(id=uuid4().hex, connection_id=connection_id, connection_revision=revision, platform=item["platform"],
                external_id=item["external_id"], page_id=item["page_id"], name=item["name"], username=item.get("username"),
                linked_page_name=item.get("linked_page_name"), observations=item.get("observations", []), active=True, expires_at=now() + timedelta(minutes=20))
            db.add(row); output.append(asset_data(row))
    return {"items": output, "truncated": result["truncated"]}


async def _request_result(db, ctx, request_id):
    row = await db.scalar(select(Request).where(Request.owner_id == ctx.identity, Request.request_id == request_id))
    if row is None: return None, None
    binding = await db.scalar(select(Binding).where(Binding.id == row.binding_id, Binding.owner_id == ctx.identity).execution_options(populate_existing=True))
    if binding is None: raise HTTPException(404, "原绑定记录不存在")
    await media._customer(db, ctx, binding.customer_id)
    return row, binding


async def request_result(db, user, request_id):
    ctx = await context(db, user); _, binding = await _request_result(db, ctx, media._key(request_id))
    if binding is None: raise HTTPException(404, "尚未找到本次绑定请求，请保留原请求编号")
    return binding_data(binding)


async def bind(db, user, *, request_id, customer_id, connection_id, asset_ref):
    key = media._key(request_id)
    if not isinstance(asset_ref, str) or not re.fullmatch(r"[a-f0-9]{32}", asset_ref): raise HTTPException(422, "请选择本次读取到的 Meta 资产")
    fingerprint = digest({"customer_id": customer_id, "connection_id": connection_id, "asset_ref": asset_ref})
    ctx = await context(db, user)
    old, binding = await _request_result(db, ctx, key)
    if old:
        if old.fingerprint != fingerprint: raise HTTPException(409, "同一请求编号对应不同绑定")
        return binding_data(binding)
    selected = await db.get(Asset, asset_ref, populate_existing=True)
    connection = await _connection(db, ctx, connection_id)
    if not selected or selected.connection_id != connection_id or selected.connection_revision != connection.revision or not selected.active or aware(selected.expires_at) <= now():
        raise HTTPException(409, "资产选择已过期或连接已变化，请重新读取")
    frozen = {name: getattr(selected, name) for name in ("platform", "external_id", "page_id")}
    result, revision = await _read_assets(db, user, connection_id)
    live = next((x for x in result["items"] if all(x[k] == value for k, value in frozen.items())), None)
    if live is None: raise HTTPException(409, "此资产已不在当前 Meta 授权列表中，请重新读取")
    async with write(db):
        ctx = await context(db, user, lock=True); connection = await _connection(db, ctx, connection_id, lock=True)
        selected = await db.get(Asset, asset_ref, populate_existing=True)
        if connection.revision != revision or not selected or not selected.active or selected.connection_revision != revision or aware(selected.expires_at) <= now():
            raise HTTPException(409, "资产选择或连接已变化，请重新读取")
        customer, _ = await media._customer(db, ctx, customer_id, write=True)
        customer = await db.scalar(select(Customers).where(Customers.id == customer_id).with_for_update().execution_options(populate_existing=True))
        if customer is None or customer.status != "closed": raise HTTPException(409, "仅绑定仍在合作的已成交客户")
        old, binding = await _request_result(db, ctx, key)
        if old:
            if old.fingerprint != fingerprint: raise HTTPException(409, "同一请求编号对应不同绑定")
            return binding_data(binding)
        existing = await db.scalar(select(Binding.id).where(Binding.active.is_(True),
            ((Binding.customer_id == customer_id) & (Binding.platform == frozen["platform"])) |
            ((Binding.platform == frozen["platform"]) & (Binding.external_id == frozen["external_id"]))).with_for_update().limit(1))
        if existing is not None: raise HTTPException(409, "此客户或平台资产已有有效绑定，请先断开并核对归属")
        # A later explicit binding creates a fresh history row. Old requests
        # remain attached to their inactive row and can never restore access.
        binding = Binding(owner_id=ctx.identity, customer_id=customer_id, customer_name=customer.business_name, connection_id=connection_id,
            connection_revision=revision, platform=frozen["platform"], external_id=frozen["external_id"], page_id=frozen["page_id"],
            asset_name=live["name"], asset_username=live.get("username"), active=True, revision=1, created_at=now(), updated_at=now())
        db.add(binding); await db.flush()
        db.add(Request(owner_id=ctx.identity, request_id=key, fingerprint=fingerprint, binding_id=binding.id, created_at=now()))
        output = binding_data(binding)
    return output


async def disconnect_binding(db, user, binding_id, expected_revision):
    async with write(db):
        ctx = await context(db, user, lock=True)
        row = await db.scalar(select(Binding).where(Binding.id == binding_id, Binding.owner_id == ctx.identity).with_for_update().execution_options(populate_existing=True))
        if not row: raise HTTPException(404, "Meta 绑定不存在")
        await media._customer(db, ctx, row.customer_id)
        if row.revision != expected_revision: raise HTTPException(409, "绑定状态已变化，请重新读取")
        if row.active: row.active = False; row.revision += 1; row.updated_at = now()
        output = binding_data(row)
    return output


async def disconnect_connection(db, user, connection_id, expected_revision):
    async with write(db):
        ctx = await context(db, user, lock=True); row = await _connection(db, ctx, connection_id, lock=True, usable=False)
        repeated = not row.active and row.token_encrypted is None and row.revision == expected_revision + 1
        if row.revision != expected_revision and not repeated: raise HTTPException(409, "连接版本已变化，请读取实际状态后重新确认")
        if row.active or row.token_encrypted:
            await _invalidate(db, row.id); row.active = False; row.token_encrypted = None; row.needs_reconnect = False; row.revision += 1
        output = {"disconnected": True, "connection_id": row.id, "revision": row.revision}
    return output
