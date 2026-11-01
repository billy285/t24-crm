"""Bounded, local-only merchant projection over existing operating permissions.

This module does not refresh providers, approve content, dispatch publications,
change grants, or persist a cache. Native workspaces remain authoritative for
exact preview and every mutation. Cached interaction references are not a full
provider inbox and disappear when their existing authority or lifetime ends.
"""
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import json
import os
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from models.customers import Customers
from models.employees import Employees
from models.media_operations import MediaOperationTask as Task
from services import media_operations as media, media_planning as planning
from services.customer_permissions import customer_permissions_for_rows
from services.customers import CustomersService
from services.role_permissions import normalized_role
from services.schema_readiness import tables_available, SchemaUnavailableError

CUSTOMER_CAP = 1000
SOURCE_CAP = 500
BINDING_CAP = 200
VIEWS = {"overview", "calendar", "review", "inbox"}
PUBLIC_KINDS = {"post_publish", "review_reply"}


def now(): return datetime.now(timezone.utc)
def iso(value): return media._iso(value)
def digest(value): return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
def aware(value): return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


async def context(db, user):
    ctx = await media.context(db, user)
    actor = await db.get(Employees, ctx.identity, populate_existing=True)
    if not actor or actor.status not in {"active", "probation"} or normalized_role(SimpleNamespace(role=actor.role)) != normalized_role(user):
        raise HTTPException(403, "当前员工身份已失效，请重新登录")
    return ctx


def _platform(value):
    if value is not None and value not in dict(media.PLATFORMS):
        raise HTTPException(422, "请选择支持的平台")
    return value


def _source(key, state="ready", message=""):
    return {"key": key, "state": state, "message": message}


async def _customers(db, ctx, customer_id=None, q=None):
    query = select(Customers).order_by(Customers.id)
    scope = CustomersService._scope_filter_for_user(ctx.user, module="delivery")
    if scope is not None: query = query.where(scope)
    if customer_id is not None:
        # Direct selection must not silently turn a denied customer into an
        # empty all-merchant view.
        await media._customer(db, ctx, customer_id)
        query = query.where(Customers.id == customer_id)
    if q:
        query = query.where(Customers.business_name.ilike("%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%", escape="\\"))
    candidates = list((await db.scalars(query.limit(CUSTOMER_CAP + 1))).all())
    truncated = len(candidates) > CUSTOMER_CAP
    candidates = candidates[:CUSTOMER_CAP]
    permissions = await customer_permissions_for_rows(db, ctx.user, candidates, config=ctx.config) if candidates else {}
    rows = {r.id: r for r in candidates if permissions[r.id]["modules"]["delivery"]["read"] and (ctx.owner or permissions[r.id]["explicit"])}
    return rows, {k: permissions[k] for k in rows}, truncated


async def _limited(db, query):
    values = list((await db.scalars(query.limit(SOURCE_CAP + 1))).all())
    return values[:SOURCE_CAP], len(values) > SOURCE_CAP


def _row(kind, record, customer, platform, *, title="", content="", status="", at=None,
         basis="record_created", revision=None, version=None, binding=None, navigation=None,
         timezone_name=None, review=False):
    return {"id": kind + ":" + str(record.id), "kind": kind, "customer_id": customer.id,
        "customer_name": customer.business_name, "platform": platform, "title": title or "未命名内容",
        "content": content if isinstance(content, str) else "", "status": status, "at": iso(at),
        "time_basis": basis, "timezone": timezone_name, "revision": revision, "version": version,
        "source_id": record.id, "binding_id": binding.id if binding is not None else None,
        "binding_revision": binding.revision if binding is not None else None,
        "account_label": (getattr(binding, "title", None) or getattr(binding, "asset_name", None)) if binding is not None else None,
        "review_eligible": review, "navigation": navigation or {"workspace": "tasks", "task_id": record.id}}


async def _tasks(db, ctx, customers, permissions, start, end, platform):
    query = select(Task).where(Task.customer_id.in_(customers), Task.due_at >= start, Task.due_at < end).order_by(Task.due_at, Task.id)
    if not ctx.owner: query = query.where(Task.assignee_id == ctx.identity)
    if platform: query = query.where(Task.platform == platform)
    records, truncated = await _limited(db, query)
    items = []
    for record in records:
        data = media._data(record, ctx, permissions[record.customer_id])
        items.append(_row("task", record, customers[record.customer_id], record.platform, title=record.title,
            content=record.content, status=record.status, at=record.due_at, basis="task_due",
            revision=record.revision, timezone_name=record.timezone, review=data["permissions"]["can_review"]))
    return items, truncated


async def _google(db, ctx, customers, start, end, platform, *, maps_only=False):
    if platform and platform != "google_business": return [], {}, _source("google", message="当前平台筛选不包含 Google"), False
    from models.google_business import GoogleBusinessBinding as Binding, GoogleBusinessConnection as Connection, GoogleBusinessSchedule as Schedule, GoogleBusinessAction as Action, GoogleBusinessAIDraft as Draft
    from services import google_business as g
    if not await tables_available(db, g.TABLES): return [], {}, _source("google", "missing", "Google 本地记录尚不可用；尚需在门店同步评论"), True
    # All checks below are local. In particular binding_data/status are not
    # reused because those native APIs may probe provider capabilities.
    candidates = select(Binding).join(Connection, Binding.connection_id == Connection.id).where(Binding.customer_id.in_(customers), Binding.active.is_(True), Connection.active.is_(True)).order_by(Binding.id)
    if ctx.owner: candidates = candidates.where(Connection.owner_id == ctx.identity)
    else:
        from models.google_business import GoogleBusinessGrant as Grant
        candidates = candidates.join(Grant, Grant.binding_id == Binding.id).where(Grant.employee_id == ctx.identity, (Grant.can_reply.is_(True) | Grant.can_publish.is_(True)))
    raw = list((await db.scalars(candidates.limit(BINDING_CAP + 1))).all())
    truncated = len(raw) > BINDING_CAP
    bindings = {}
    for candidate in raw[:BINDING_CAP]:
        try:
            binding, _, _ = await g._binding(db, ctx, candidate.id)
            bindings[binding.id] = binding
        except HTTPException as exc:
            if exc.status_code not in {403, 404, 409}: raise
    if not bindings: return [], {}, _source("google", "missing", "当前范围没有已授权 Google 门店；尚需在门店同步评论"), truncated
    source = _source("google", message="仅本地已保存草稿、排期及操作记录；完整评论尚需在门店同步")
    if maps_only: return [], bindings, source, truncated
    items = []
    if await tables_available(db, {Schedule.__tablename__}):
        query = select(Schedule).join(Task, Task.id == Schedule.task_id).join(Binding, Binding.id == Schedule.binding_id).where(
            Schedule.binding_id.in_(bindings), Task.customer_id == Binding.customer_id, Task.platform == "google_business",
            Schedule.planned_at >= start, Schedule.planned_at < end).order_by(Schedule.planned_at, Schedule.id)
        if not ctx.owner:
            query = query.where(Schedule.task_id.in_(select(Task.id).where(Task.assignee_id == ctx.identity)))
        schedules, cut = await _limited(db, query); truncated |= cut
        for row in schedules:
            b = bindings[row.binding_id]
            status = row.status
            if row.action_id:
                submitted = await db.get(Action, row.action_id, populate_existing=True)
                if submitted and submitted.binding_id == b.id and submitted.task_id == row.task_id and submitted.kind == "post_publish":
                    status = submitted.status
                else: status = "unknown"
            # Content frozen by the existing publication approval is presented
            # only in its native preview, never reconstructed from today's task.
            items.append(_row("google_schedule", row, customers[b.customer_id], "google_business", title="Google 帖子排期",
                status=status, at=row.planned_at, basis="scheduled_publish", revision=row.revision, binding=b,
                timezone_name=row.timezone, navigation={"workspace": "google", "binding_id": b.id, "schedule_id": row.id, "task_id": row.task_id}))
    else: truncated = True
    query = select(Action).where(Action.binding_id.in_(bindings), Action.kind.in_(PUBLIC_KINDS), Action.created_at >= start, Action.created_at < end).order_by(Action.created_at, Action.id)
    actions, cut = await _limited(db, query); truncated |= cut
    for row in actions:
        b = bindings[row.binding_id]
        data = g.action_data(row, ctx)
        items.append(_row("google_action", row, customers[b.customer_id], "google_business", title="Google 评论回复" if row.kind == "review_reply" else "Google 帖子发布",
            content=data["content"], status=row.status, at=row.created_at, binding=b,
            navigation={"workspace": "google", "binding_id": b.id, "action_id": row.id}))
    if await tables_available(db, {Draft.__tablename__}):
        query = select(Draft).where(Draft.binding_id.in_(bindings), Draft.created_at >= start, Draft.created_at < end,
            Draft.expires_at > now(), Draft.status == "generated").order_by(Draft.created_at, Draft.id)
        if not ctx.owner: query = query.where(Draft.actor_id == ctx.identity)
        drafts, cut = await _limited(db, query); truncated |= cut
        for row in drafts:
            b = bindings[row.binding_id]
            if not isinstance(row.review_name, str) or not row.review_name.startswith(b.location_name + "/reviews/"): continue
            items.append(_row("google_reply_draft", row, customers[b.customer_id], "google_business", title="Google 待核对回复草稿",
                content=row.reply_text, status="approved" if row.approved_at and row.approved_by_id and row.approved_reply_hash == g.hash_text(row.reply_text) else "draft", at=row.created_at,
                version=row.review_version, binding=b, navigation={"workspace": "google", "binding_id": b.id, "draft_id": row.id}))
    else: truncated = True
    return items, bindings, source, truncated


async def _meta(db, ctx, customers, start, end, platform, *, maps_only=False):
    if not ctx.owner: return [], {}, _source("meta", "locked", "Facebook / Instagram 独立运营记录仅老板可见"), False
    if platform and platform not in {"facebook", "instagram"}: return [], {}, _source("meta", message="当前平台筛选不包含 Facebook / Instagram"), False
    from models.meta_operations import MetaOperationsBinding as Binding, MetaOperationsCredential as Credential, MetaOperationsDraft as Draft, MetaOperationsAction as Action, MetaOperationsSchedule as Schedule, MetaOperationsTarget as Target
    from services import meta_operations as ops, meta_operations_provider as provider
    if not await tables_available(db, ops.TABLES): return [], {}, _source("meta", "missing", "独立 Meta 运营记录尚不可用"), True
    opctx = await ops.context(db, ctx.user)
    query = select(Binding).where(Binding.owner_id == ctx.identity, Binding.customer_id.in_(customers), Binding.active.is_(True)).order_by(Binding.id)
    if platform: query = query.where(Binding.platform == platform)
    raw = list((await db.scalars(query.limit(BINDING_CAP + 1))).all()); truncated = len(raw) > BINDING_CAP
    bindings = {}
    for candidate in raw[:BINDING_CAP]:
        try:
            b = await ops._binding(db, opctx, candidate.id)
            if b.source_binding_id != b.id: continue
            credential = await db.get(Credential, b.credential_id, populate_existing=True)
            # Validate config, decryption, exact scopes and expiry locally;
            # never call provider capabilities or asset enumeration here.
            _, scopes = provider.OpsClient(credential.token_encrypted).access()
            granted = credential.granted_scopes
            if not isinstance(granted, list) or len(granted) > 100 or not all(isinstance(x, str) for x in granted) or len(granted) != len(set(granted)) or set(granted) != set(scopes): continue
            bindings[b.id] = b
        except (HTTPException, provider.OpsProviderError, AttributeError):
            continue
    if not bindings: return [], {}, _source("meta", "missing", "尚无有效独立运营授权；暂停或过期账号的互动快照不展示"), truncated
    source = _source("meta", message="仅当前有效授权下的限时互动快照；完整互动请进入门店刷新")
    if maps_only: return [], bindings, source, truncated
    items = []
    for model, kind in ((Draft, "meta_draft"), (Schedule, "meta_schedule"), (Action, "meta_action")):
        column = model.planned_at if model is Schedule else (model.updated_at if model is Draft else model.created_at)
        query = select(model).where(model.owner_id == ctx.identity, model.binding_id.in_(bindings), column >= start, column < end).order_by(column, model.id)
        records, cut = await _limited(db, query); truncated |= cut
        for row in records:
            b = bindings[row.binding_id]
            snap = row.submitted_snapshot if model in {Schedule, Action} else None
            if model is Action and (row.binding_revision != b.revision or row.connection_revision != b.connection_revision): continue
            nav = {"workspace": "meta", "binding_id": b.id, "draft_id": row.id if model is Draft else row.draft_id}
            if model is Schedule: nav["schedule_id"] = row.id
            if model is Action: nav["action_id"] = row.id
            content = row.content if model is Draft else (snap.get("content", "") if isinstance(snap, dict) else "")
            title = row.title if model is Draft else (snap.get("title", "") if isinstance(snap, dict) else "")
            items.append(_row(kind, row, customers[b.customer_id], b.platform, title=title or "Meta 运营记录", content=content,
                status=row.status, at=getattr(row, "planned_at", None) if model is Schedule else column_value(row, model),
                basis="scheduled_publish" if model is Schedule else "record_created", revision=row.revision,
                binding=b, timezone_name=getattr(row, "timezone", None), navigation=nav))
    # The provider cache can contain several reads of one external object.
    # Take the newest valid snapshot, then validate the opaque parent chain.
    query = select(Target).where(Target.owner_id == ctx.identity, Target.binding_id.in_(bindings), Target.expires_at > now()).order_by(Target.created_at.desc(), Target.id.desc())
    targets, cut = await _limited(db, query); truncated |= cut
    seen = set()
    for row in targets:
        b = bindings[row.binding_id]
        if row.binding_revision != b.revision or row.kind not in {"post", "comment"}: continue
        snap = row.snapshot
        if not isinstance(snap, dict) or snap.get("external_id") != row.external_id or ops.digest(snap) != row.version: continue
        if row.kind == "comment":
            parent = await db.get(Target, row.parent_ref, populate_existing=True) if row.parent_ref else None
            if not parent or parent.owner_id != ctx.identity or parent.binding_id != b.id or parent.binding_revision != b.revision or parent.kind != "post" or aware(parent.expires_at) <= now() or parent.external_id != row.parent_external_id or snap.get("post_external_id") != parent.external_id: continue
            if not isinstance(parent.snapshot, dict) or parent.snapshot.get("external_id") != parent.external_id or ops.digest(parent.snapshot) != parent.version: continue
        key = (b.id, row.kind, row.external_id)
        if key in seen: continue
        seen.add(key)
        # An unknown platform timestamp stays explicitly record_created. It is
        # never invented as a publication time for the calendar.
        created = provider._timestamp(snap.get("created_at"))
        instant = datetime.fromisoformat(created) if created else aware(row.created_at)
        if not start <= instant < end: continue
        nav = {"workspace": "meta", "binding_id": b.id, "target_ref": row.id}
        if row.kind == "comment": nav["post_ref"] = row.parent_ref
        items.append(_row("meta_" + row.kind, row, customers[b.customer_id], b.platform,
            title="Facebook / Instagram 评论快照" if row.kind == "comment" else "Facebook / Instagram 帖子快照",
            content=snap.get("content", ""), status="snapshot", at=instant,
            basis="platform_created" if created else "record_created", version=row.version, binding=b, navigation=nav))
    return items, bindings, source, truncated


def column_value(row, model):
    return row.updated_at if model.__name__ == "MetaOperationsDraft" else row.created_at


async def _optional(db, key, factory):
    try:
        # A failed optional SQL read must not poison the other local sources on
        # PostgreSQL. No business objects are added or flushed by this service.
        async with db.begin_nested(): return await factory()
    except (SQLAlchemyError, SchemaUnavailableError):
        return [], {}, _source(key, "error", "此平台本地记录暂时无法读取，请进入门店重试"), True
    except HTTPException as exc:
        if exc.status_code not in {403, 404, 409, 503}: raise
        return [], {}, _source(key, "locked", "当前账号或连接状态未开放此平台记录"), True


async def _gather(db, ctx, customers, permissions, start, end, platform):
    tasks, truncated = await _tasks(db, ctx, customers, permissions, start, end, platform)
    google, gb, gs, cut = await _optional(db, "google", lambda: _google(db, ctx, customers, start, end, platform)); truncated |= cut
    meta, mb, ms, cut = await _optional(db, "meta", lambda: _meta(db, ctx, customers, start, end, platform)); truncated |= cut
    by_customer = {b.customer_id: b for b in gb.values()}
    for row in tasks:
        if row["platform"] == "google_business" and row["customer_id"] in by_customer:
            b = by_customer[row["customer_id"]]
            row.update(binding_id=b.id, binding_revision=b.revision, account_label=b.title)
    return tasks + google + meta, gb, mb, [_source("tasks", message="仅本人任务或老板可查看的任务；日期为内部完成期限"), gs, ms], truncated


def _paginate(items, *, ctx, scope, sources, cursor, limit):
    if type(limit) is not int or not 1 <= limit <= 100: raise HTTPException(422, "分页数量应为 1—100")
    fingerprint = digest({"items": items, "sources": sources})
    expected = {"actor": ctx.identity, "scope": scope, "dataset": fingerprint}
    offset = 0
    key = os.environ.get("JWT_SECRET_KEY")
    if cursor:
        try:
            if not isinstance(key, str) or len(key) < 32 or not isinstance(cursor, str) or len(cursor) > 6000: raise ValueError()
            encoded, signature = cursor.split(".")
            raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            calculated = hmac.new(key.encode(), b"media-workspace-v1\0" + raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, calculated): raise ValueError()
            value = json.loads(raw)
            if set(value) != {*expected, "offset", "expires"} or any(value[k] != v for k, v in expected.items()) or type(value["offset"]) is not int or not 0 < value["offset"] < len(items) or type(value["expires"]) is not int or value["expires"] <= now().timestamp(): raise ValueError()
            offset = value["offset"]
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise HTTPException(409, "分页范围或权限已变化，请重新读取第一页") from None
    following = offset + limit
    next_cursor = None
    if following < len(items):
        if not isinstance(key, str) or len(key) < 32: raise HTTPException(503, "安全分页配置暂不可用，请缩小门店范围")
        raw = json.dumps({**expected, "offset": following, "expires": int((now() + timedelta(minutes=15)).timestamp())}, sort_keys=True, separators=(",", ":")).encode()
        next_cursor = base64.urlsafe_b64encode(raw).decode().rstrip("=") + "." + hmac.new(key.encode(), b"media-workspace-v1\0" + raw, hashlib.sha256).hexdigest()
    return items[offset:following], next_cursor


async def merchants(db, user, *, q=None, platform=None, cursor=None, limit=50):
    ctx = await context(db, user); platform = _platform(platform)
    q = q.strip() if isinstance(q, str) else None
    if q and len(q) > 100: raise HTTPException(422, "搜索内容过长")
    customers, permissions, truncated = await _customers(db, ctx, q=q)
    # Merchant choices derive from the authorized portfolio plus task platform
    # associations, not a provider request for each merchant.
    query = select(Task.customer_id, Task.platform, Task.timezone).where(Task.customer_id.in_(customers)).distinct().order_by(Task.customer_id, Task.platform, Task.timezone)
    if not ctx.owner: query = query.where(Task.assignee_id == ctx.identity)
    pairs = list((await db.execute(query.limit(CUSTOMER_CAP * 6 + 1))).all())
    pair_cut = len(pairs) > CUSTOMER_CAP * 6; truncated |= pair_cut
    platforms = {k: set() for k in customers}
    zones = {k: set() for k in customers}
    for identity, value, zone in pairs[:CUSTOMER_CAP * 6]:
        if value in dict(media.PLATFORMS): platforms[identity].add(value)
        if isinstance(zone, str) and zone: zones[identity].add(zone)
    # No interaction/content queries are needed to discover current authorized
    # native bindings; maps_only avoids reading hundreds of cached targets.
    instant = now()
    _, gb, gs, cut = await _optional(db, "google", lambda: _google(db, ctx, customers, instant, instant, platform, maps_only=True)); truncated |= cut
    _, mb, ms, cut = await _optional(db, "meta", lambda: _meta(db, ctx, customers, instant, instant, platform, maps_only=True)); truncated |= cut
    for b in gb.values(): platforms[b.customer_id].add("google_business")
    for b in mb.values(): platforms[b.customer_id].add(b.platform)
    operators = {}
    for binding in gb.values():
        if not binding.primary_operator_id or binding.lifecycle != "active": continue
        employee = await db.get(Employees, binding.primary_operator_id, populate_existing=True)
        if employee and employee.status in {"active", "probation"}:
            operators[binding.customer_id] = employee.name
    items = [{"id": r.id, "name": r.business_name, "platforms": sorted(platforms[r.id]),
        "can_create": bool(ctx.can_create and permissions[r.id]["modules"]["delivery"]["write"]),
        "can_edit": bool(ctx.can_edit and permissions[r.id]["modules"]["delivery"]["write"]),
        "region": ", ".join(x for x in (r.city, r.state) if isinstance(x, str) and x.strip()) or None if permissions[r.id]["modules"]["basic"]["read"] else None,
        "industry": r.industry if permissions[r.id]["modules"]["basic"]["read"] else None,
        "timezone": next(iter(zones[r.id])) if not pair_cut and len(zones[r.id]) == 1 else None,
        "primary_operator_name": operators.get(r.id)} for r in customers.values()
        if not platform or platform in platforms[r.id]]
    sources = [_source("tasks", message="仅当前已授权商家与任务平台"), gs, ms]
    page, following = _paginate(items, ctx=ctx, scope={"q": q, "platform": platform, "view": "merchants"}, sources=sources, cursor=cursor, limit=limit)
    return {"items": page, "next_cursor": following, "total": len(items), "partial": bool(truncated or following), "sources": sources, "observed_at": iso(now())}


async def workspace(db, user, *, start, end, customer_id=None, platform=None, view="overview", cursor=None, limit=50):
    ctx = await context(db, user); start, end = planning.window(start, end, maximum=366); platform = _platform(platform)
    if view not in VIEWS: raise HTTPException(422, "请选择有效工作视图")
    customers, permissions, truncated = await _customers(db, ctx, customer_id)
    rows, _, _, sources, cut = await _gather(db, ctx, customers, permissions, start, end, platform); truncated |= cut
    rows.sort(key=lambda r: (r["at"] or "", r["id"]), reverse=True)
    summary = {"tasks": sum(r["kind"] == "task" for r in rows),
        "drafts": sum(r["kind"] in {"meta_draft", "google_reply_draft"} and r["status"] == "draft" or r["kind"] == "task" and r["status"] == "draft" for r in rows),
        "in_review": sum(r["kind"] == "task" and r["status"] == "in_review" for r in rows),
        "ready": sum(r["kind"] == "task" and r["status"] == "ready" for r in rows),
        "scheduled": sum(r["kind"] in {"google_schedule", "meta_schedule"} and r["status"] == "scheduled" for r in rows),
        "blocked": sum(r["status"] in {"blocked", "failed", "missed", "rejected"} for r in rows),
        "unknown": sum(r["status"] in {"unknown", "pending", "accepted"} for r in rows),
        "inbox": sum(r["kind"] in {"meta_comment", "google_reply_draft"} for r in rows),
        "review_candidates": sum(r["review_eligible"] for r in rows)}
    if view == "review": rows = [r for r in rows if r["review_eligible"] or r["kind"] in {"meta_draft", "google_reply_draft"}]
    elif view == "inbox": rows = [r for r in rows if r["kind"] in {"meta_comment", "google_reply_draft"}]
    # Calendar includes internal deadlines with an explicit task_due basis so
    # the UI can place them in a separate preparation list.
    elif view == "calendar": rows = [r for r in rows if r["kind"] in {"task", "google_schedule", "meta_schedule", "meta_post"}]
    scope = {"customer_id": customer_id, "platform": platform, "view": view}
    period = {"start": iso(start), "end": iso(end)}
    page, following = _paginate(rows, ctx=ctx, scope={**scope, **period}, sources=sources, cursor=cursor, limit=limit)
    return {"items": page, "next_cursor": following, "total": len(rows),
        "partial": bool(truncated or following or view == "inbox"), "sources": sources, "observed_at": iso(now()),
        "scope": scope, "range": period, "summary": summary, "capabilities": {"is_owner": ctx.owner, "meta_owner_only": True}}
