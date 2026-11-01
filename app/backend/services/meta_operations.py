"""Owner-confirmed PokeCo pilot. No shared permissions, finance or Google writes."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import secrets
from types import SimpleNamespace
import unicodedata
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from models.customers import Customers
from models.employees import Employees
from models.meta_business import MetaBusinessBinding as Binding, MetaBusinessConnection as Connection
from models.meta_operations import (MetaOperationsCredential as Credential, MetaOperationsOAuthState as OAuthState,
    MetaOperationsBinding as OperatingBinding,
    MetaOperationsMedia as Media, MetaOperationsTarget as Target, MetaOperationsDraft as Draft,
    MetaOperationsAction as Action, MetaOperationsSchedule as Schedule, MetaOperationsRequest as OperationRequest)
from services import media_operations as media
from services import meta_business as meta
from services import meta_operations_media as images
from services import meta_operations_provider as provider
from services.role_permissions import normalized_role
from services.schema_readiness import require_tables

TABLES = {"meta_operations_" + name for name in ("credentials", "oauth_states", "bindings", "media", "targets", "drafts", "actions", "schedules", "requests")}
COOKIE = "__Secure-t24_meta_ops_oauth"
LOCK = int.from_bytes(b"T24MOPS1", "big")
PILOT_CUSTOMER_ID = 38
SHA = re.compile(r"[a-f0-9]{64}\Z")
REF = re.compile(r"[a-f0-9]{32}\Z")
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
MEDIA_NOTICE = "仅在逐条确认发布时，向 Meta 开放这份不可变图片副本14天供其读取；持有临时地址者在有效期内也可读取。上传和预览不会公开。"
MESSAGES = {"not_configured": "Meta 运营授权配置尚未完成，可先准备草稿和预览", "execution_disabled": "真实发布和回复尚未启用，可先准备并核对内容",
    "authorization_required": "请老板补充本试点的运营授权", "reconnect_required": "Meta 运营授权已失效，请老板重新授权",
    "access_denied": "Meta 未开放所需账号或权限，请老板核对", "asset_not_authorized": "本次运营授权未包含这个账号",
    "permission_missing": "Meta 当前账号任务权限不足", "quota_limited": "Meta 请求额度暂时不足，请稍后核对原结果",
    "invalid_response": "Meta 返回结果暂无法核实", "provider_unavailable": "Meta 暂时无法连接，请核对原请求结果",
    "unsupported_kind": "此类型尚未开放", "content_invalid": "内容或图片格式不满足平台要求",
    "media_not_ready": "Instagram 图片仍在处理中，请检查并继续原发布", "target_changed": "平台账号或原评论已变化，请重新读取并确认"}


def now(): return datetime.now(timezone.utc)
def aware(value): return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
def iso(value): return aware(value).isoformat() if value else None
def digest(value): return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
def hash_text(value): return hashlib.sha256(str(value).encode()).hexdigest()


async def context(db, user):
    ctx = await meta.context(db, user)
    await require_tables(db, TABLES)
    return ctx


@asynccontextmanager
async def write(db):
    try:
        if db.get_bind().dialect.name == "sqlite": await db.execute(text("UPDATE meta_operations_requests SET id=id WHERE 0"))
        elif db.get_bind().dialect.name == "postgresql": await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK})
        yield
        await db.commit()
    except (DBAPIError, IntegrityError):
        await db.rollback()
        raise HTTPException(409, "本次操作正在保存，请保留原请求编号核对结果") from None
    except BaseException:
        await db.rollback(); raise


async def _binding(db, ctx, binding_id, *, lock=False, usable=True):
    query = select(Binding).where(Binding.id == binding_id, Binding.owner_id == ctx.identity).execution_options(populate_existing=True)
    if lock: query = query.with_for_update()
    source = await db.scalar(query)
    if source is None: raise HTTPException(404, "Meta 客户账号不存在或未获授权")
    customer, _ = await media._customer(db, ctx, source.customer_id)
    own_query = select(OperatingBinding).where(OperatingBinding.id == binding_id, OperatingBinding.owner_id == ctx.identity).execution_options(populate_existing=True)
    if lock: own_query = own_query.with_for_update()
    operating = await db.scalar(own_query)
    if operating is not None:
        if any(getattr(source, key) != getattr(operating, key) for key in ("owner_id", "customer_id", "platform", "external_id", "page_id", "connection_id")):
            raise HTTPException(409, "原账号识别信息已被更改，请老板重新核对独立运营归属")
        credential = await db.get(Credential, operating.credential_id, populate_existing=True)
        if usable and (not operating.active or not credential or credential.owner_id != ctx.identity or credential.connection_id != operating.connection_id or
                       not credential.active or credential.needs_reconnect or credential.revision != operating.connection_revision or not credential.token_encrypted):
            raise HTTPException(409, "此独立运营账号已暂停或需要重新授权")
        row = operating
    else:
        if customer.id != PILOT_CUSTOMER_ID: raise HTTPException(409, "本客户尚无老板明确建立的独立运营授权")
        row = source
        connection = await db.scalar(select(Connection).where(Connection.id == row.connection_id, Connection.owner_id == ctx.identity).execution_options(populate_existing=True))
        if usable and (not row.active or not connection or not connection.active or connection.needs_reconnect or
                       connection.revision != row.connection_revision or not connection.token_encrypted):
            raise HTTPException(409, "请先核对只读连接，再为试点建立独立运营授权")
    if usable and (customer.status != "closed" or operating is None and (customer.id != PILOT_CUSTOMER_ID or customer.business_name.strip().casefold() != "pokeco")):
        raise HTTPException(409, "本阶段仅开放仍在合作的 PokeCo 试点")
    return row


async def _credential_revision(db, ctx, binding):
    row = await db.scalar(select(Credential).where(Credential.owner_id == ctx.identity, Credential.connection_id == binding.connection_id).execution_options(populate_existing=True))
    return row.revision if row and row.active and not row.needs_reconnect else None


def _configuration():
    try: return provider.configuration_fingerprint()
    except provider.OpsProviderError: return "not_configured"


def _provider_binding(row):
    # A populate_existing query inside the adapter must not rewrite the caller's
    # expected ORM instance and accidentally turn a stale comparison into self.
    return SimpleNamespace(**{key: getattr(row, key) for key in ("id", "owner_id", "customer_id", "revision", "connection_id",
        "connection_revision", "platform", "external_id", "page_id")}, source_binding_id=getattr(row, "source_binding_id", row.id),
        credential_id=getattr(row, "credential_id", None))


async def binding_data(db, ctx, row):
    from services.meta_operations_scheduler import configuration
    capability = await provider.capabilities(db, ctx.user, _provider_binding(row))
    capability["can_schedule"] = bool(capability["can_publish"] and configuration()["enabled"])
    capability["blocked_reasons"] = [MESSAGES.get(code, MESSAGES["provider_unavailable"]) for code in capability["blocked_reasons"]]
    operating = isinstance(row, OperatingBinding)
    return {"id": row.id, "connection_id": row.connection_id, "customer_id": row.customer_id, "customer_name": row.customer_name,
            "operations_active": bool(operating and row.active), "can_pause": bool(operating and row.active), "paused": bool(operating and not row.active),
            "platform": row.platform, "asset_name": row.asset_name, "revision": row.revision, "capabilities": capability}


async def status(db, user):
    ctx = await context(db, user)
    configured = provider.status()
    from services.meta_operations_scheduler import configuration
    result = {"is_owner": True, "pilot_label": "Pokeco", "write_configured": configured["configured"],
              "setup_missing": configured["setup_missing"], "authorization": configured["authorization"],
              "scheduler": configuration(), "bindings": []}
    ids = set((await db.scalars(select(Binding.id).where(Binding.owner_id == ctx.identity, Binding.customer_id == PILOT_CUSTOMER_ID, Binding.active.is_(True)).limit(1000))).all())
    ids.update((await db.scalars(select(OperatingBinding.id).where(OperatingBinding.owner_id == ctx.identity).limit(1000))).all())
    for identity in sorted(ids):
        try:
            row = await _binding(db, ctx, identity, usable=False)
            customer, _ = await media._customer(db, ctx, row.customer_id)
            if customer.status != "closed" or not isinstance(row, OperatingBinding) and (customer.id != PILOT_CUSTOMER_ID or customer.business_name.strip().casefold() != "pokeco"): continue
            result["bindings"].append(await binding_data(db, ctx, row))
        except HTTPException as exc:
            if exc.status_code not in {403, 404, 409}: raise
    return result


def media_data(row):
    return {"id": row.id, "sha256": row.sha256, "byte_size": row.byte_size, "width": row.width, "height": row.height,
            "preview_path": "/api/v1/meta-operations/media/" + row.id + "/preview", "created_at": iso(row.created_at)}


def draft_data(row):
    return {key: getattr(row, key) for key in ("id", "binding_id", "kind", "title", "content", "media_id", "target_ref", "expected_target_version", "status", "revision", "preview_hash")} | {
        "approved_at": iso(row.approved_at), "created_at": iso(row.created_at), "updated_at": iso(row.updated_at)}


async def action_data(db, row):
    submitted = row.submitted_snapshot or {}
    media_row = await db.get(Media, submitted.get("media_id")) if submitted.get("media_id") else None
    return {"id": row.id, "binding_id": row.binding_id, "draft_id": row.draft_id, "kind": row.kind, "request_id": row.request_id,
        "status": row.status, "revision": row.revision, "message": row.message, "provider_url": row.provider_url,
        "can_continue": row.status == "processing" and row.dispatch_stage == "container_created" or row.status == "pending" and row.dispatch_stage == "reserved",
        "submitted_draft": {key: submitted.get(key) for key in ("kind", "title", "content", "media_id", "target_ref")} | {
            "draft_revision": row.draft_revision, "preview_hash": row.preview_hash},
        "target": {key: submitted.get(key) for key in ("customer_name", "platform", "asset_name")},
        "media": media_data(media_row) if media_row else None, "created_at": iso(row.created_at), "updated_at": iso(row.updated_at)}


def schedule_data(row):
    submitted = row.submitted_snapshot or {}
    return {key: getattr(row, key) for key in ("id", "binding_id", "draft_id", "draft_revision", "preview_hash", "timezone", "status", "revision", "message", "action_id")} | {
        "planned_at": iso(row.planned_at), "created_at": iso(row.created_at),
        "submitted_draft": {key: submitted.get(key) for key in ("kind", "title", "content", "media_id", "target_ref")} | {
            "draft_revision": row.draft_revision, "preview_hash": row.preview_hash},
        "media": submitted.get("media"), "target": {key: submitted.get(key) for key in ("customer_name", "platform", "asset_name")}}


async def workspace(db, user, binding_id):
    ctx = await context(db, user); binding = await _binding(db, ctx, binding_id, usable=False)
    drafts = list((await db.scalars(select(Draft).where(Draft.owner_id == ctx.identity, Draft.binding_id == binding.id).order_by(Draft.updated_at.desc(), Draft.id.desc()).limit(100))).all())
    actions = list((await db.scalars(select(Action).where(Action.owner_id == ctx.identity, Action.binding_id == binding.id).order_by(Action.id.desc()).limit(100))).all())
    schedules = list((await db.scalars(select(Schedule).where(Schedule.owner_id == ctx.identity, Schedule.binding_id == binding.id).order_by(Schedule.id.desc()).limit(100))).all())
    versions = list((await db.scalars(select(Media).where(Media.owner_id == ctx.identity, Media.customer_id == binding.customer_id).order_by(Media.created_at.desc()).limit(50))).all())
    return {"binding": await binding_data(db, ctx, binding), "drafts": [draft_data(x) for x in drafts],
            "actions": [await action_data(db, x) for x in actions], "schedules": [schedule_data(x) for x in schedules], "media": [media_data(x) for x in versions]}


async def _request(db, ctx, request_id, *, kind=None, fingerprint=None):
    row = await db.scalar(select(OperationRequest).where(OperationRequest.owner_id == ctx.identity, OperationRequest.request_id == media._key(request_id)))
    if row and ((kind is not None and row.kind != kind) or (fingerprint is not None and row.fingerprint != fingerprint)):
        raise HTTPException(409, "同一请求编号对应不同内容，请核对原结果")
    return row


def _save_request(db, ctx, request_id, kind, fingerprint, result_id):
    db.add(OperationRequest(owner_id=ctx.identity, request_id=request_id, kind=kind, fingerprint=fingerprint, result_id=str(result_id), created_at=now()))


async def request_result(db, user, request_id):
    ctx = await context(db, user); row = await _request(db, ctx, request_id)
    if row is None: raise HTTPException(404, "尚未找到本次操作，请保留原请求编号")
    if row.kind == "oauth": return {"kind": "oauth", "result": await oauth_request(db, user, request_id)}
    model = {"draft": Draft, "media": Media, "action": Action, "schedule": Schedule}.get(row.kind)
    entity = await db.get(model, row.result_id if row.kind == "media" else int(row.result_id), populate_existing=True) if model else None
    if entity is None or entity.owner_id != ctx.identity: raise HTTPException(404, "原操作记录不存在")
    if row.kind == "media":
        await media._customer(db, ctx, entity.customer_id); result = media_data(entity)
    else:
        await _binding(db, ctx, entity.binding_id, usable=False)
        result = draft_data(entity) if row.kind == "draft" else schedule_data(entity) if row.kind == "schedule" else await action_data(db, entity)
    return {"kind": row.kind, "result": result}


def _content(value, maximum, *, required=False):
    if not isinstance(value, str) or len(value) > maximum or required and not value.strip() or any(unicodedata.category(c).startswith("C") and c not in "\n\r\t" for c in value):
        raise HTTPException(422, "文字为空、过长或含隐藏控制字符")
    return value


async def _target(db, ctx, binding, target_ref, *, kind=None):
    row = await db.get(Target, target_ref, populate_existing=True) if isinstance(target_ref, str) and REF.fullmatch(target_ref) else None
    if not row or row.owner_id != ctx.identity or row.binding_id != binding.id or row.binding_revision != binding.revision or aware(row.expires_at) <= now() or kind and row.kind != kind:
        raise HTTPException(409, "原帖或评论引用已变化，请重新读取")
    return row


async def _image(db, ctx, binding, image_id, *, verify=True):
    if image_id is None: return None
    row = await db.get(Media, image_id, populate_existing=True) if isinstance(image_id, str) and REF.fullmatch(image_id) else None
    if not row or row.owner_id != ctx.identity or row.customer_id != binding.customer_id:
        raise HTTPException(422, "图片与本客户不匹配")
    if verify: await asyncio.to_thread(images.read_image, row)
    return row


async def upload_media(db, user, binding_id, *, request_id, rights_confirmed, body):
    ctx = await context(db, user); binding = await _binding(db, ctx, binding_id)
    key = media._key(request_id)
    if rights_confirmed is not True: raise HTTPException(422, "请确认这是真实且有权使用的商家图片")
    canonical, width, height = await images.prepare_pixels(body)
    sha = hashlib.sha256(canonical).hexdigest(); source = hashlib.sha256(body).hexdigest()
    fingerprint = digest({"binding_id": binding.id, "source_sha256": source, "sha256": sha})
    previous = await _request(db, ctx, key, kind="media", fingerprint=fingerprint)
    if previous: return (await request_result(db, user, key))["result"]
    identity = uuid4().hex; signature = await asyncio.to_thread(images.write_image, identity, canonical)
    async with write(db):
        ctx = await context(db, user); binding = await _binding(db, ctx, binding_id, lock=True)
        previous = await _request(db, ctx, key, kind="media", fingerprint=fingerprint)
        if previous: return (await request_result(db, user, key))["result"]
        row = Media(id=identity, owner_id=ctx.identity, customer_id=binding.customer_id, source_sha256=source, sha256=sha,
                    width=width, height=height, byte_size=len(canonical), file_stat=signature, created_at=now())
        db.add(row); _save_request(db, ctx, key, "media", fingerprint, identity)
    return media_data(row)


async def preview_media(db, user, media_id):
    ctx = await context(db, user)
    row = await db.get(Media, media_id, populate_existing=True) if REF.fullmatch(media_id) else None
    if not row or row.owner_id != ctx.identity: raise HTTPException(404, "图片不存在或未获授权")
    await media._customer(db, ctx, row.customer_id)
    frozen = SimpleNamespace(id=row.id, sha256=row.sha256, byte_size=row.byte_size, file_stat=row.file_stat)
    await db.rollback(); body = await asyncio.to_thread(images.read_image, frozen)
    ctx = await context(db, user); fresh = await db.get(Media, media_id, populate_existing=True)
    if not fresh or fresh.owner_id != ctx.identity or fresh.sha256 != frozen.sha256: raise HTTPException(404, "图片不可读取")
    await media._customer(db, ctx, fresh.customer_id)
    return body


async def _draft(db, ctx, draft_id, *, lock=False):
    query = select(Draft).where(Draft.id == draft_id, Draft.owner_id == ctx.identity).execution_options(populate_existing=True)
    if lock: query = query.with_for_update()
    row = await db.scalar(query)
    if not row: raise HTTPException(404, "内容草稿不存在")
    return row, await _binding(db, ctx, row.binding_id, lock=lock)


async def create_draft(db, user, binding_id, *, request_id, kind, title, content, media_id=None, target_ref=None, expected_target_version=None):
    ctx = await context(db, user); binding = await _binding(db, ctx, binding_id)
    key = media._key(request_id)
    if kind not in {"post", "reply"}: raise HTTPException(422, "请选择帖子或评论回复")
    _content(title, 200, required=True); _content(content, 1000 if kind == "reply" else 5000 if binding.platform == "facebook" else 2200)
    if kind == "reply":
        if media_id is not None or not isinstance(expected_target_version, str) or not SHA.fullmatch(expected_target_version): raise HTTPException(422, "请先读取原评论并核对版本")
        target = await _target(db, ctx, binding, target_ref, kind="comment")
        if target.version != expected_target_version: raise HTTPException(409, "原评论已变化，请重新读取")
    elif target_ref is not None or expected_target_version is not None: raise HTTPException(422, "帖子不能关联评论目标")
    await _image(db, ctx, binding, media_id)
    fingerprint = digest({"binding_id": binding_id, "kind": kind, "title": title, "content": content, "media_id": media_id, "target_ref": target_ref, "expected_target_version": expected_target_version})
    async with write(db):
        ctx = await context(db, user); binding = await _binding(db, ctx, binding_id, lock=True)
        previous = await _request(db, ctx, key, kind="draft", fingerprint=fingerprint)
        if previous: return (await request_result(db, user, key))["result"]
        await _image(db, ctx, binding, media_id)
        if kind == "reply": await _target(db, ctx, binding, target_ref, kind="comment")
        row = Draft(owner_id=ctx.identity, binding_id=binding.id, kind=kind, title=title, content=content, media_id=media_id,
                    target_ref=target_ref, expected_target_version=expected_target_version, status="draft", revision=1, created_at=now(), updated_at=now())
        db.add(row); await db.flush(); _save_request(db, ctx, key, "draft", fingerprint, row.id)
    return draft_data(row)


async def update_draft(db, user, draft_id, *, expected_revision, fields):
    async with write(db):
        ctx = await context(db, user); row, binding = await _draft(db, ctx, draft_id, lock=True)
        if row.revision != expected_revision: raise HTTPException(409, "草稿已变化，请读取最新版本")
        if await db.scalar(select(Action.id).where(Action.draft_id == row.id, Action.status.in_(("pending", "processing", "unknown"))).limit(1)):
            raise HTTPException(409, "此内容有执行中或待核实请求，请先核对原结果")
        title = fields.get("title", row.title); content = fields.get("content", row.content); image_id = fields.get("media_id", row.media_id)
        _content(title, 200, required=True); _content(content, 1000 if row.kind == "reply" else 5000 if binding.platform == "facebook" else 2200)
        if row.kind == "reply" and image_id is not None: raise HTTPException(422, "评论回复不支持图片")
        await _image(db, ctx, binding, image_id)
        row.title = title; row.content = content; row.media_id = image_id; row.status = "draft"; row.revision += 1
        row.preview_hash = None; row.approved_snapshot = None; row.approved_at = None; row.updated_at = now()
        await db.execute(update(Schedule).where(Schedule.draft_id == row.id, Schedule.status.in_(("prepared", "scheduled"))).values(
            status="blocked", revision=Schedule.revision + 1, message="草稿已修改，请重新预览、确认并排期", updated_at=now()).execution_options(synchronize_session=False))
    return draft_data(row)


async def _snapshot(db, ctx, row, binding, *, fresh_reply=True):
    _content(row.content, 1000 if row.kind == "reply" else 5000 if binding.platform == "facebook" else 2200, required=True)
    image = await _image(db, ctx, binding, row.media_id)
    if row.kind == "post" and binding.platform == "instagram":
        if not image: raise HTTPException(422, "Instagram 单图帖子需要先选择真实 JPEG 图片")
        if not 320 <= image.width <= 1440 or not 0.8 <= image.width / image.height <= 1.91:
            raise HTTPException(422, "Instagram 图片宽度需320—1440像素，宽高比需介于4:5与1.91:1")
    reply = None; target = None
    if row.kind == "reply":
        target = await _target(db, ctx, binding, row.target_ref, kind="comment")
        reply = target.snapshot
        if target.version != row.expected_target_version: raise HTTPException(409, "评论版本已变化，请重新读取并创建回复草稿")
        if fresh_reply:
            await db.commit()
            try: reply = await provider.read_comment(db, ctx.user, _provider_binding(binding), target.external_id, target.parent_external_id)
            except provider.OpsProviderError as exc: raise HTTPException(409, MESSAGES.get(exc.code, MESSAGES["provider_unavailable"])) from None
            if digest(reply) != target.version: raise HTTPException(409, "原评论已变化，请重新读取并确认回复")
    snapshot = {"kind": row.kind, "title": row.title, "content": row.content, "media_id": row.media_id, "target_ref": row.target_ref,
        "customer_id": binding.customer_id, "customer_name": binding.customer_name, "platform": binding.platform, "asset_name": binding.asset_name,
        "binding_id": binding.id, "binding_revision": binding.revision, "external_id": binding.external_id, "page_id": binding.page_id,
        "connection_id": binding.connection_id, "connection_revision": binding.connection_revision,
        "credential_revision": await _credential_revision(db, ctx, binding), "ops_configuration": _configuration(),
        "media_sha256": image.sha256 if image else None, "target_version": target.version if target else None,
        "target_external_id": target.external_id if target else None, "target_post_external_id": target.parent_external_id if target else None}
    return snapshot, image, reply


async def preview(db, user, draft_id, expected_revision):
    ctx = await context(db, user); row, binding = await _draft(db, ctx, draft_id)
    if row.revision != expected_revision: raise HTTPException(409, "草稿已更新，请重新读取")
    captured_revision = row.revision
    snapshot, image, reply = await _snapshot(db, ctx, row, binding)
    capability = await provider.capabilities(db, user, _provider_binding(binding))
    fresh, current_binding = await _draft(db, ctx, draft_id)
    fresh_snapshot, _, _ = await _snapshot(db, ctx, fresh, current_binding, fresh_reply=False)
    if fresh.revision != captured_revision or snapshot != fresh_snapshot: raise HTTPException(409, "内容或账号已变化，请重新预览")
    allowed = capability["can_reply" if row.kind == "reply" else "can_publish"]
    return {"draft": draft_data(fresh), "preview_hash": digest(snapshot),
        "target": {key: snapshot[key] for key in ("customer_name", "platform", "asset_name")}, "media": media_data(image) if image else None,
        "reply_to": {key: reply.get(key) for key in ("content", "author_name", "created_at")} | {"version": row.expected_target_version} if reply else None,
        "warnings": [MESSAGES.get(x, MESSAGES["provider_unavailable"]) for x in capability["blocked_reasons"]],
        "ready_for_publish": bool(allowed), "media_delivery_notice": MEDIA_NOTICE if image else None}


async def approve(db, user, draft_id, *, expected_revision, preview_hash):
    # Slow provider reads happen before taking the write lock.
    ctx = await context(db, user); initial, binding = await _draft(db, ctx, draft_id)
    if initial.revision != expected_revision: raise HTTPException(409, "草稿已变化，请重新预览")
    snapshot, _, _ = await _snapshot(db, ctx, initial, binding)
    if digest(snapshot) != preview_hash: raise HTTPException(409, "预览内容或目标已变化，请重新预览")
    async with write(db):
        ctx = await context(db, user); row, binding = await _draft(db, ctx, draft_id, lock=True)
        current, _, _ = await _snapshot(db, ctx, row, binding, fresh_reply=False)
        if row.revision != expected_revision or current != snapshot: raise HTTPException(409, "内容、素材或账号已变化，请重新确认")
        if row.status == "approved" and row.preview_hash == preview_hash and row.approved_snapshot == snapshot:
            return draft_data(row)
        row.status = "approved"; row.preview_hash = preview_hash; row.approved_snapshot = snapshot; row.approved_at = now(); row.revision += 1; row.updated_at = now()
    return draft_data(row)


def _encode_cursor(ctx, binding, kind, cursor, post_ref):
    if cursor is None: return None
    return provider.encrypt({"owner_id": ctx.identity, "binding_id": binding.id, "binding_revision": binding.revision,
        "kind": kind, "post_ref": post_ref, "cursor": cursor, "expires_at": int((now() + timedelta(minutes=20)).timestamp())})


def _decode_cursor(ctx, binding, kind, cursor, post_ref):
    if cursor is None: return None
    if not isinstance(cursor, str) or len(cursor) > 6000: raise HTTPException(422, "分页引用格式不正确")
    try: value = provider.decrypt(cursor)
    except provider.OpsProviderError: raise HTTPException(409, "分页引用已失效，请重新读取第一页") from None
    expected = {"owner_id": ctx.identity, "binding_id": binding.id, "binding_revision": binding.revision, "kind": kind, "post_ref": post_ref}
    if set(value) != {*expected, "cursor", "expires_at"} or any(value.get(k) != v for k, v in expected.items()) or type(value["expires_at"]) is not int or value["expires_at"] <= now().timestamp():
        raise HTTPException(409, "分页引用不属于当前账号或已过期")
    return value["cursor"]


async def read_posts(db, user, binding_id, cursor=None):
    ctx = await context(db, user); binding = await _binding(db, ctx, binding_id)
    continuation = _decode_cursor(ctx, binding, "post", cursor, None)
    revision = binding.revision; connection_revision = binding.connection_revision
    await db.commit()
    try: result = await provider.read_posts(db, user, _provider_binding(binding), continuation)
    except provider.OpsProviderError as exc: raise HTTPException(409, MESSAGES.get(exc.code, MESSAGES["provider_unavailable"])) from None
    items = []
    async with write(db):
        ctx = await context(db, user); binding = await _binding(db, ctx, binding_id, lock=True)
        if binding.revision != revision or binding.connection_revision != connection_revision: raise HTTPException(409, "账号已变化，请重新读取")
        for item in result["items"]:
            row = Target(id=uuid4().hex, owner_id=ctx.identity, binding_id=binding.id, binding_revision=binding.revision,
                kind="post", external_id=item["external_id"], snapshot=item, version=digest(item), expires_at=now() + timedelta(days=7), created_at=now())
            db.add(row); items.append({"target_ref": row.id, "content": item["content"], "created_at": item.get("created_at"), "permalink": item.get("permalink")})
    return {"items": items, "next_cursor": _encode_cursor(ctx, binding, "post", result.get("next_cursor"), None)}


async def read_comments(db, user, binding_id, *, post_ref, cursor=None):
    ctx = await context(db, user); binding = await _binding(db, ctx, binding_id)
    post = await _target(db, ctx, binding, post_ref, kind="post")
    continuation = _decode_cursor(ctx, binding, "comment", cursor, post_ref)
    revision = binding.revision; external = post.external_id
    await db.commit()
    try: result = await provider.read_comments(db, user, _provider_binding(binding), external, continuation)
    except provider.OpsProviderError as exc: raise HTTPException(409, MESSAGES.get(exc.code, MESSAGES["provider_unavailable"])) from None
    items = []
    async with write(db):
        ctx = await context(db, user); binding = await _binding(db, ctx, binding_id, lock=True)
        post = await _target(db, ctx, binding, post_ref, kind="post")
        if binding.revision != revision or post.external_id != external: raise HTTPException(409, "原帖已变化，请重新读取")
        for item in result["items"]:
            version = digest(item)
            row = Target(id=uuid4().hex, owner_id=ctx.identity, binding_id=binding.id, binding_revision=binding.revision,
                kind="comment", external_id=item["external_id"], parent_external_id=external, parent_ref=post_ref, snapshot=item,
                version=version, expires_at=now() + timedelta(days=7), created_at=now())
            db.add(row); items.append({"target_ref": row.id, "post_ref": post_ref, "content": item["content"],
                "author_name": item.get("author_name", ""), "created_at": item.get("created_at"), "version": version})
    return {"items": items, "next_cursor": _encode_cursor(ctx, binding, "comment", result.get("next_cursor"), post_ref)}


async def _approved(db, ctx, draft_id, expected_revision, preview_hash):
    row, binding = await _draft(db, ctx, draft_id, lock=True)
    if row.revision != expected_revision or row.status != "approved" or row.preview_hash != preview_hash or not row.approved_snapshot:
        raise HTTPException(409, "此内容尚未经过当前版本确认，请先预览并确认")
    snapshot, _, _ = await _snapshot(db, ctx, row, binding, fresh_reply=False)
    if snapshot != row.approved_snapshot or digest(snapshot) != preview_hash:
        raise HTTPException(409, "已确认的内容、图片、目标或授权已变化，请重新确认")
    return row, binding, snapshot


async def _reserve(db, user, draft_id, *, request_id, expected_revision, preview_hash, schedule_id=None):
    key = media._key(request_id); fingerprint = digest({"draft_id": draft_id, "expected_revision": expected_revision, "preview_hash": preview_hash})
    ctx = await context(db, user)
    previous = await _request(db, ctx, key, kind="action", fingerprint=fingerprint)
    if previous: return int(previous.result_id), False
    row, binding = await _draft(db, ctx, draft_id)
    from services.media_monthly_meta import authorize_native
    await authorize_native(db, draft_id=draft_id, schedule_id=schedule_id)
    snapshot, _, _ = await _snapshot(db, ctx, row, binding)
    capability = await provider.capabilities(db, user, _provider_binding(binding))
    if not capability["can_reply" if row.kind == "reply" else "can_publish"]:
        raise HTTPException(409, "；".join(MESSAGES.get(x, MESSAGES["provider_unavailable"]) for x in capability["blocked_reasons"]) or "当前账号尚未开放本次操作")
    async with write(db):
        ctx = await context(db, user)
        previous = await _request(db, ctx, key, kind="action", fingerprint=fingerprint)
        if previous: return int(previous.result_id), False
        row, binding, approved = await _approved(db, ctx, draft_id, expected_revision, preview_hash)
        await authorize_native(db, draft_id=draft_id, schedule_id=schedule_id)
        if snapshot != approved: raise HTTPException(409, "内容已变化，请重新预览")
        existing = await db.scalar(select(Action).where(Action.draft_id == row.id, Action.draft_revision == row.revision).limit(1))
        if existing: raise HTTPException(409, "此版本已有平台请求，请检查原操作记录，不能重复发送")
        competing = await db.scalar(select(Schedule).where(Schedule.draft_id == row.id, Schedule.draft_revision == row.revision,
            Schedule.status.in_(("prepared", "scheduled", "dispatching")), Schedule.id != schedule_id if schedule_id is not None else True).limit(1))
        if competing: raise HTTPException(409, "此版本已有排期，请先取消原排期再直接发布")
        payload = {"content": row.content} if row.kind == "post" else {"target_id": snapshot["target_external_id"],
            "post_id": snapshot["target_post_external_id"], "message": row.content, "expected_version": snapshot["target_version"]}
        action = Action(owner_id=ctx.identity, binding_id=binding.id, binding_revision=binding.revision,
            connection_revision=binding.connection_revision, draft_id=row.id, draft_revision=row.revision, kind=row.kind, request_id=key,
            fingerprint=fingerprint, preview_hash=preview_hash, submitted_snapshot=snapshot, payload=payload,
            status="pending", revision=1, dispatch_stage="reserved", message="已登记原请求，尚未开始平台发送", created_at=now(), updated_at=now())
        db.add(action); await db.flush(); _save_request(db, ctx, key, "action", fingerprint, action.id)
    return action.id, True


async def _claimed_action(db, user, action_id, *, expected_stage):
    ctx = await context(db, user)
    row = await db.scalar(select(Action).where(Action.id == action_id, Action.owner_id == ctx.identity).with_for_update().execution_options(populate_existing=True))
    if row is None or row.dispatch_stage != expected_stage: raise HTTPException(409, "原发布请求已开始或已变化，请检查原结果")
    draft, binding, snapshot = await _approved(db, ctx, row.draft_id, row.draft_revision, row.preview_hash)
    from services.media_monthly_meta import authorize_native
    schedule = await db.scalar(select(Schedule).where(Schedule.action_id == row.id).limit(1))
    await authorize_native(db, draft_id=row.draft_id, schedule_id=schedule.id if schedule else None, action=row)
    if snapshot != row.submitted_snapshot or binding.revision != row.binding_revision or binding.connection_revision != row.connection_revision:
        raise HTTPException(409, "原发布的账号、图片或内容已变化")
    return row, binding


async def _record_result(db, action_id, *, result=None, error=None, stage):
    # Record the outcome even if the owner disconnected while the HTTP request
    # was in flight. A later permission failure must not lose a provider ID.
    async with write(db):
        row = await db.scalar(select(Action).where(Action.id == action_id).with_for_update().execution_options(populate_existing=True))
        if row is None or row.dispatch_stage != stage: raise HTTPException(409, "原请求记录已变化，请核对原结果")
        if error is not None:
            row.status = "unknown" if error.uncertain else "failed"
            row.message = "平台执行结果待核实，不会自动再次发送" if error.uncertain else MESSAGES.get(error.code, MESSAGES["provider_unavailable"])
            row.dispatch_stage = "unknown" if error.uncertain else "failed"
        elif isinstance(result, dict) and result.get("status") == "processing" and re.fullmatch(r"[0-9]{1,80}", str(result.get("container_id", ""))):
            row.status = "processing"; row.dispatch_stage = "container_created"
            row.progress = {"container_id": result["container_id"], "stage": "container_created"}
            row.message = "Instagram 已建立原图片容器，尚未发布；请检查并继续原发布"
        elif isinstance(result, dict) and result.get("status") == "published" and re.fullmatch(r"[0-9]{1,80}(?:_[0-9]{1,80})?", str(result.get("external_id", ""))):
            row.status = "succeeded"; row.dispatch_stage = "complete"; row.provider_id = result["external_id"]
            row.provider_url = provider._permalink(result.get("permalink")); row.message = "平台已确认本次发布或回复成功"
        else:
            row.status = "unknown"; row.dispatch_stage = "unknown"; row.message = "平台返回结果暂无法核实，不会自动再次发送"
        row.revision += 1; row.updated_at = now()


async def _dispatch(db, user, action_id):
    async with write(db):
        row, binding = await _claimed_action(db, user, action_id, expected_stage="reserved")
        row.dispatch_started_at = now(); row.dispatch_stage = "initial_started"; row.revision += 1; row.updated_at = now()
        if row.kind == "post" and row.submitted_snapshot.get("media_id"):
            row.delivery_token = secrets.token_urlsafe(32); row.delivery_expires_at = now() + timedelta(days=14)
            row.payload = {**row.payload, "image_url": "https://t24-crm.com/api/v1/meta-operations/delivery/" + row.delivery_token + ".jpg"}
        payload = dict(row.payload); kind = row.kind; target = _provider_binding(binding)
    try:
        result = await provider.dispatch(db, user, target, kind, payload)
    except provider.OpsProviderError as exc:
        await db.rollback(); await _record_result(db, action_id, error=exc, stage="initial_started")
    except BaseException:
        await db.rollback(); await _record_result(db, action_id, error=provider.OpsProviderError(uncertain=True), stage="initial_started")
        raise
    else:
        await db.rollback(); await _record_result(db, action_id, result=result, stage="initial_started")


async def action(db, user, action_id):
    ctx = await context(db, user)
    row = await db.scalar(select(Action).where(Action.id == action_id, Action.owner_id == ctx.identity).execution_options(populate_existing=True))
    if row is None: raise HTTPException(404, "原平台操作不存在")
    await _binding(db, ctx, row.binding_id, usable=False)
    return await action_data(db, row)


async def publish(db, user, draft_id, *, request_id, expected_revision, preview_hash):
    identity, fresh = await _reserve(db, user, draft_id, request_id=request_id, expected_revision=expected_revision, preview_hash=preview_hash)
    if fresh: await _dispatch(db, user, identity)
    return await action(db, user, identity)


async def continue_action(db, user, action_id, *, expected_revision):
    ctx = await context(db, user)
    row = await db.scalar(select(Action).where(Action.id == action_id, Action.owner_id == ctx.identity).execution_options(populate_existing=True))
    if row is None: raise HTTPException(404, "原平台操作不存在")
    if row.revision == expected_revision and row.status == "pending" and row.dispatch_stage == "reserved":
        await db.rollback()
        await _dispatch(db, user, action_id)
        return await action(db, user, action_id)
    if row.revision != expected_revision or row.status != "processing" or row.dispatch_stage != "container_created" or not row.progress:
        raise HTTPException(409, "只有已保存容器、尚未开始发布的原请求可以继续")
    binding = await _binding(db, ctx, row.binding_id)
    progress = dict(row.progress); target = _provider_binding(binding)
    await db.commit()
    try: readiness = await provider.inspect_progress(db, user, target, progress)
    except provider.OpsProviderError as exc: raise HTTPException(409, MESSAGES.get(exc.code, MESSAGES["provider_unavailable"])) from None
    state = readiness.get("status")
    if state == "IN_PROGRESS": return await action(db, user, action_id)
    if state != "FINISHED":
        async with write(db):
            ctx = await context(db, user); current = await db.get(Action, action_id, populate_existing=True, with_for_update=True)
            if current.owner_id != ctx.identity or current.revision != expected_revision or current.dispatch_stage != "container_created": raise HTTPException(409, "原请求已变化")
            current.status = "unknown" if state == "PUBLISHED" else "failed"; current.dispatch_stage = current.status
            current.message = "Meta 显示此容器已发布，请核对原结果，不会再次发送" if state == "PUBLISHED" else "Instagram 容器无法继续，请核对原结果后重新准备内容"
            current.revision += 1; current.updated_at = now()
        return await action(db, user, action_id)
    async with write(db):
        current, binding = await _claimed_action(db, user, action_id, expected_stage="container_created")
        if current.revision != expected_revision or current.status != "processing" or current.progress != progress: raise HTTPException(409, "原图片容器或操作版本已变化")
        current.status = "pending"; current.dispatch_stage = "publish_started"; current.revision += 1; current.updated_at = now(); target = _provider_binding(binding)
    try: result = await provider.publish_container(db, user, target, progress["container_id"])
    except provider.OpsProviderError as exc:
        await db.rollback(); await _record_result(db, action_id, error=exc, stage="publish_started")
    except BaseException:
        await db.rollback(); await _record_result(db, action_id, error=provider.OpsProviderError(uncertain=True), stage="publish_started")
        raise
    else:
        await db.rollback(); await _record_result(db, action_id, result=result, stage="publish_started")
    return await action(db, user, action_id)


def _planned(value, zone):
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
        if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None: raise ValueError()
        at = at.astimezone(timezone.utc); ZoneInfo(zone)
        if at <= now() + timedelta(minutes=1) or at > now() + timedelta(days=366): raise ValueError()
    except (ValueError, TypeError, AttributeError, ZoneInfoNotFoundError):
        raise HTTPException(422, "请选择未来一年内、至少一分钟后的时间，并填写有效时区") from None
    return at


async def prepare_schedule(db, user, draft_id, *, request_id, expected_revision, preview_hash, planned_at, timezone, execute_confirmed=False):
    key = media._key(request_id); at = _planned(planned_at, timezone)
    fingerprint = digest({"draft_id": draft_id, "expected_revision": expected_revision, "preview_hash": preview_hash, "planned_at": iso(at), "timezone": timezone, "execute_confirmed": execute_confirmed})
    ctx = await context(db, user); previous = await _request(db, ctx, key, kind="schedule", fingerprint=fingerprint)
    if previous: return (await request_result(db, user, key))["result"]
    from services.meta_operations_scheduler import configuration
    worker = configuration(); row, binding = await _draft(db, ctx, draft_id)
    from services.media_monthly_meta import authorize_native
    await authorize_native(db, draft_id=draft_id)
    capability = await provider.capabilities(db, user, _provider_binding(binding))
    async with write(db):
        ctx = await context(db, user); previous = await _request(db, ctx, key, kind="schedule", fingerprint=fingerprint)
        if previous: return (await request_result(db, user, key))["result"]
        row, binding, snapshot = await _approved(db, ctx, draft_id, expected_revision, preview_hash)
        if row.kind != "post": raise HTTPException(422, "本阶段仅支持帖子排期，评论回复由老板逐条确认")
        if await db.scalar(select(Schedule.id).where(Schedule.draft_id == row.id, Schedule.draft_revision == row.revision, Schedule.status.in_(("prepared", "scheduled", "dispatching"))).limit(1)):
            raise HTTPException(409, "此版本已有有效排期，请先核对或取消")
        if await db.scalar(select(Action.id).where(Action.draft_id == row.id, Action.draft_revision == row.revision).limit(1)):
            raise HTTPException(409, "此版本已有平台请求，请核对原结果")
        if execute_confirmed is True and not (worker["enabled"] and capability["can_publish"]):
            raise HTTPException(409, "定时执行或账号发布条件已变化，请重新核对；本次不会自动改为准备或发布")
        live = bool(execute_confirmed is True and worker["enabled"] and capability["can_publish"])
        image = await _image(db, ctx, binding, row.media_id)
        entry = Schedule(owner_id=ctx.identity, binding_id=binding.id, draft_id=row.id, draft_revision=row.revision, preview_hash=preview_hash,
            submitted_snapshot={**snapshot, "media": media_data(image) if image else None},
            planned_at=at, timezone=timezone, request_id=key, status="scheduled" if live else "prepared", revision=1,
            message="已逐条确认，等待指定时间执行" if live else "仅保存排期准备，不会自动发布；启用后仍需逐条确认此排期", created_at=now(), updated_at=now())
        db.add(entry); await db.flush(); _save_request(db, ctx, key, "schedule", fingerprint, entry.id)
    return schedule_data(entry)


async def cancel_schedule(db, user, schedule_id, expected_revision):
    async with write(db):
        ctx = await context(db, user); row = await db.scalar(select(Schedule).where(Schedule.id == schedule_id, Schedule.owner_id == ctx.identity).with_for_update().execution_options(populate_existing=True))
        if row is None: raise HTTPException(404, "排期不存在")
        await _binding(db, ctx, row.binding_id, usable=False)
        if row.revision != expected_revision or row.status not in {"prepared", "scheduled", "blocked"}: raise HTTPException(409, "排期已开始或已变化，请核对原执行结果")
        row.status = "cancelled"; row.revision += 1; row.message = "老板已取消本次排期"; row.updated_at = now()
    return schedule_data(row)


async def activate_schedule(db, user, schedule_id, expected_revision):
    from services.meta_operations_scheduler import configuration
    if not configuration()["enabled"]: raise HTTPException(409, "定时执行尚未启用，原排期仍只是准备记录")
    ctx = await context(db, user); row = await db.get(Schedule, schedule_id, populate_existing=True)
    if not row or row.owner_id != ctx.identity: raise HTTPException(404, "排期不存在")
    from services.media_monthly_meta import authorize_native
    await authorize_native(db, draft_id=row.draft_id)
    binding = await _binding(db, ctx, row.binding_id); capability = await provider.capabilities(db, user, _provider_binding(binding))
    if not capability["can_publish"]: raise HTTPException(409, "此账号尚未具备发布条件")
    async with write(db):
        ctx = await context(db, user); row = await db.get(Schedule, schedule_id, populate_existing=True, with_for_update=True)
        if row.owner_id != ctx.identity or row.revision != expected_revision or row.status != "prepared": raise HTTPException(409, "排期已变化，请重新读取")
        _planned(row.planned_at.replace(tzinfo=timezone.utc) if row.planned_at.tzinfo is None else row.planned_at, row.timezone)
        await _approved(db, ctx, row.draft_id, row.draft_revision, row.preview_hash)
        row.status = "scheduled"; row.revision += 1; row.message = "老板已逐条确认此未来排期"; row.updated_at = now()
    return schedule_data(row)


async def _oauth_flow(db, ctx, row):
    if row.consumed or not row.flow_encrypted or aware(row.expires_at) <= now(): raise HTTPException(409, "本次运营授权已使用或过期，请核对状态后重新授权")
    try: value = provider.decrypt(row.flow_encrypted)
    except provider.OpsProviderError: raise HTTPException(409, "运营授权配置已变化，请重新发起") from None
    if set(value) != {"state", "cookie", "configuration"} or value["configuration"] != _configuration():
        raise HTTPException(409, "运营授权范围已变化，请重新核对")
    return {"authorization_url": provider.authorize_url(value["state"]), "expires_in": max(1, int((aware(row.expires_at) - now()).total_seconds()))}, value["cookie"]


async def _oauth_targets(db, ctx, connection_id, *, permitted_ids=None):
    sources = list((await db.scalars(select(Binding).where(Binding.owner_id == ctx.identity, Binding.connection_id == connection_id,
        Binding.customer_id == PILOT_CUSTOMER_ID).order_by(Binding.id).execution_options(populate_existing=True))).all())
    targets = []
    for source in sources:
        if permitted_ids is not None and source.id not in permitted_ids: continue
        operating = await db.get(OperatingBinding, source.id, populate_existing=True)
        if operating is None and not source.active and permitted_ids is None: continue
        row = await _binding(db, ctx, source.id, usable=False)
        customer, _ = await media._customer(db, ctx, row.customer_id)
        if customer.id != PILOT_CUSTOMER_ID or customer.status != "closed" or customer.business_name.strip().casefold() != "pokeco":
            raise HTTPException(409, "本阶段仅开放仍在合作的 PokeCo 试点")
        if operating is None and permitted_ids is None:
            await _binding(db, ctx, source.id)  # Initial prep requires a valid approved source.
        targets.append({"id": row.id, "source_binding_id": source.id, "owner_id": ctx.identity, "customer_id": customer.id,
            "customer_name": customer.business_name, "platform": row.platform, "external_id": row.external_id, "page_id": row.page_id,
            "asset_name": row.asset_name, "asset_username": row.asset_username, "connection_id": connection_id,
            "operating_revision": operating.revision if operating else None})
    if not 1 <= len(targets) <= 2 or len({x["platform"] for x in targets}) != len(targets):
        raise HTTPException(409, "请先核对 PokeCo 唯一的 Facebook 与 Instagram 客户归属")
    return targets


async def oauth_start(db, user, *, request_id, connection_id):
    ctx = await context(db, user); key = media._key(request_id)
    try: provider.require_config()
    except provider.OpsProviderError: raise HTTPException(409, MESSAGES["not_configured"]) from None
    fingerprint = digest({"connection_id": connection_id, "configuration": _configuration()})
    async with write(db):
        ctx = await context(db, user)
        previous = await _request(db, ctx, key, kind="oauth", fingerprint=fingerprint)
        if previous:
            row = await db.get(OAuthState, int(previous.result_id), populate_existing=True)
            return await _oauth_flow(db, ctx, row)
        targets = await _oauth_targets(db, ctx, connection_id)
        credential = await db.scalar(select(Credential).where(Credential.owner_id == ctx.identity, Credential.connection_id == connection_id).with_for_update().execution_options(populate_existing=True))
        await db.execute(update(OAuthState).where(OAuthState.expires_at < now(), OAuthState.flow_encrypted != "").values(consumed=True, flow_encrypted="").execution_options(synchronize_session=False))
        state, cookie = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
        row = OAuthState(owner_id=ctx.identity, request_id=key, fingerprint=fingerprint, state_hash=hash_text(state), cookie_hash=hash_text(cookie),
            flow_encrypted=provider.encrypt({"state": state, "cookie": cookie, "configuration": _configuration()}), connection_id=connection_id,
            connection_revision=credential.revision if credential else 0, expected_credential_revision=credential.revision if credential else None, targets_snapshot=targets,
            expires_at=now() + timedelta(minutes=10), consumed=False, created_at=now())
        db.add(row); await db.flush(); _save_request(db, ctx, key, "oauth", fingerprint, row.id)
        result = await _oauth_flow(db, ctx, row)
    return result


async def oauth_request(db, user, request_id):
    ctx = await context(db, user); key = media._key(request_id)
    row = await db.scalar(select(OAuthState).where(OAuthState.owner_id == ctx.identity, OAuthState.request_id == key))
    if row is None: raise HTTPException(404, "尚未找到本次运营授权请求")
    return (await _oauth_flow(db, ctx, row))[0]


async def oauth_cookie_request(db, user, request_id):
    ctx = await context(db, user); key = media._key(request_id)
    row = await db.scalar(select(OAuthState).where(OAuthState.owner_id == ctx.identity, OAuthState.request_id == key))
    if row is None: raise HTTPException(404, "尚未找到本次运营授权请求")
    return await _oauth_flow(db, ctx, row)


async def oauth_callback(db, state, cookie, code):
    if not all(isinstance(value, str) and 1 <= len(value) <= maximum for value, maximum in ((state, 200), (cookie, 200), (code, 4096))):
        raise HTTPException(400, "Meta 运营授权验证失败")
    try: provider.require_config()
    except provider.OpsProviderError: raise HTTPException(409, MESSAGES["not_configured"]) from None
    async with write(db):
        row = await db.scalar(select(OAuthState).where(OAuthState.state_hash == hash_text(state)).with_for_update().execution_options(populate_existing=True))
        if row is None or not hmac.compare_digest(row.cookie_hash, hash_text(cookie)): raise HTTPException(400, "Meta 运营授权验证失败")
        owner = await db.get(Employees, row.owner_id, populate_existing=True)
        if owner is None or owner.status not in {"active", "probation"} or normalized_role(SimpleNamespace(role=owner.role)) != "super_admin":
            raise HTTPException(403, "老板账号已失效")
        user = SimpleNamespace(id=str(owner.id), role=owner.role, name=owner.name)
        ctx = await context(db, user); await _oauth_flow(db, ctx, row)
        targets = await _oauth_targets(db, ctx, row.connection_id, permitted_ids={x["id"] for x in row.targets_snapshot})
        if targets != row.targets_snapshot: raise HTTPException(409, "运营目标或暂停状态已变化，请重新核对")
        owner_id, connection_id, credential_revision = row.owner_id, row.connection_id, row.expected_credential_revision
        configuration = _configuration(); row.consumed = True; row.flow_encrypted = ""
    tokens = await provider.exchange(code)
    encrypted = provider.encrypt(tokens)
    verified_targets = await provider.verify_assets(encrypted, targets)
    if verified_targets != targets: raise HTTPException(409, "Meta 未返回全部已核对的试点目标，本次不会保存授权")
    async with write(db):
        ctx = await context(db, user)
        current_targets = await _oauth_targets(db, ctx, connection_id, permitted_ids={x["id"] for x in targets})
        if current_targets != targets or configuration != _configuration() or tokens.get("configuration") != configuration:
            raise HTTPException(409, "连接或运营授权范围已变化，本次不会保存旧结果")
        credential = await db.scalar(select(Credential).where(Credential.owner_id == owner_id, Credential.connection_id == connection_id).with_for_update().execution_options(populate_existing=True))
        if (credential.revision if credential else None) != credential_revision: raise HTTPException(409, "运营授权已有较新的操作，本次不会覆盖")
        if credential is None:
            credential = Credential(owner_id=owner_id, connection_id=connection_id, active=True, needs_reconnect=False, revision=1, connected_at=now())
            db.add(credential)
        else: credential.revision += 1
        credential.token_encrypted = encrypted; credential.granted_scopes = tokens.get("observed_scopes", [])
        credential.active = True; credential.needs_reconnect = False; credential.last_error = None; credential.connected_at = now()
        await db.flush()
        for target in verified_targets:
            operating = await db.get(OperatingBinding, target["id"], populate_existing=True, with_for_update=True)
            values = {key: target[key] for key in ("source_binding_id", "owner_id", "customer_id", "customer_name", "platform", "external_id", "page_id", "asset_name", "asset_username", "connection_id")}
            if operating is None:
                operating = OperatingBinding(id=target["id"], **values, credential_id=credential.id, connection_revision=credential.revision,
                    active=True, revision=1, created_at=now(), updated_at=now()); db.add(operating)
            else:
                for key, value in values.items(): setattr(operating, key, value)
                operating.credential_id = credential.id; operating.connection_revision = credential.revision
                operating.active = True; operating.revision += 1; operating.updated_at = now()
        ids = select(Binding.id).where(Binding.owner_id == owner_id, Binding.connection_id == connection_id)
        await db.execute(update(Schedule).where(Schedule.binding_id.in_(ids), Schedule.status.in_(("prepared", "scheduled"))).values(
            status="blocked", revision=Schedule.revision + 1, message="运营授权已变化，请重新核对内容后排期", updated_at=now()).execution_options(synchronize_session=False))
    return True


async def disconnect_binding(db, user, binding_id, expected_revision):
    async with write(db):
        ctx = await context(db, user)
        row = await db.scalar(select(OperatingBinding).where(OperatingBinding.id == binding_id, OperatingBinding.owner_id == ctx.identity).with_for_update().execution_options(populate_existing=True))
        if row is None: raise HTTPException(404, "此账号尚未建立独立运营授权")
        await _binding(db, ctx, binding_id, usable=False)
        if row.revision != expected_revision: raise HTTPException(409, "运营账号状态已变化，请重新读取")
        row.active = False; row.revision += 1; row.updated_at = now()
        await db.execute(update(Schedule).where(Schedule.binding_id == row.id, Schedule.status.in_(("prepared", "scheduled"))).values(
            status="blocked", revision=Schedule.revision + 1, message="老板已暂停此独立运营账号，未来排期不会执行", updated_at=now()).execution_options(synchronize_session=False))
    return await binding_data(db, ctx, row)


async def _delivery_row(db, token):
    denial = HTTPException(404, "图片不存在或投递已失效")
    if not isinstance(token, str) or not TOKEN.fullmatch(token) or not provider.execution_enabled(): raise denial
    try:
        await require_tables(db, TABLES)
        row = await db.scalar(select(Action).where(Action.delivery_token == token))
        if row is None or row.kind != "post" or row.dispatch_started_at is None or row.delivery_expires_at is None or aware(row.delivery_expires_at) <= now() or row.status not in {"pending", "processing", "unknown", "succeeded"}:
            raise denial
        owner = await db.get(Employees, row.owner_id, populate_existing=True)
        if owner is None: raise denial
        actor = SimpleNamespace(id=str(owner.id), role=owner.role, name=owner.name)
        ctx = await context(db, actor); binding = await _binding(db, ctx, row.binding_id)
        if binding.revision != row.binding_revision or binding.connection_revision != row.connection_revision:
            raise denial
        if row.submitted_snapshot.get("ops_configuration") != _configuration() or await _credential_revision(db, ctx, binding) != row.submitted_snapshot.get("credential_revision"):
            raise denial
        image = await _image(db, ctx, binding, row.submitted_snapshot.get("media_id"), verify=False)
        expected = "https://t24-crm.com/api/v1/meta-operations/delivery/" + token + ".jpg"
        if image is None or row.payload.get("image_url") != expected or image.sha256 != row.submitted_snapshot.get("media_sha256"):
            raise denial
        return image
    except HTTPException:
        raise denial from None


async def public_delivery(db, token):
    row = await _delivery_row(db, token)
    frozen = SimpleNamespace(id=row.id, sha256=row.sha256, byte_size=row.byte_size, file_stat=row.file_stat)
    await db.rollback(); body = await asyncio.to_thread(images.read_image, frozen)
    fresh = await _delivery_row(db, token)
    if fresh.id != frozen.id or fresh.sha256 != frozen.sha256 or len(body) != fresh.byte_size:
        raise HTTPException(404, "图片不存在或投递已失效")
    return body
