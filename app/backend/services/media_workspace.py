"""Complete, local-only merchant projection over existing operating permissions.

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
from zoneinfo import ZoneInfo

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

# A database fetch size, never a maximum number of merchants/source records.
# All batches are consumed before totals or a signed response page are made.
READ_BATCH_SIZE = 200
VIEWS = {"overview", "calendar", "review", "inbox"}
PUBLIC_KINDS = {"post_publish", "review_reply"}
FILTERS = {"all", "attention", "review", "unassigned", "no_schedule"}


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
    rows, permissions = {}, {}
    stream = await db.stream_scalars(query.execution_options(yield_per=READ_BATCH_SIZE))
    async for candidates in stream.partitions(READ_BATCH_SIZE):
        current = await customer_permissions_for_rows(db, ctx.user, candidates, config=ctx.config)
        for row in candidates:
            if current[row.id]["modules"]["delivery"]["read"] and (ctx.owner or current[row.id]["explicit"]):
                rows[row.id] = row
                permissions[row.id] = current[row.id]
    return rows, permissions, False


async def _records(db, query):
    """Traverse the complete filtered SQL result using bounded database fetches.

    Native authority/opaque snapshot validation is still applied before a row
    enters the merged projection. A SQL UNION must not bypass those checks.
    """
    values = []
    stream = await db.stream_scalars(query.execution_options(yield_per=READ_BATCH_SIZE))
    async for batch in stream.partitions(READ_BATCH_SIZE): values.extend(batch)
    return values, False


async def _tuples(db, query):
    values = []
    stream = await db.stream(query.execution_options(yield_per=READ_BATCH_SIZE))
    async for batch in stream.partitions(READ_BATCH_SIZE): values.extend(batch)
    return values


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
    records, truncated = await _records(db, query)
    items = []
    for record in records:
        data = media._data(record, ctx, permissions[record.customer_id])
        item = _row("task", record, customers[record.customer_id], record.platform, title=record.title,
            content=record.content, status=record.status, at=record.due_at, basis="task_due",
            revision=record.revision, timezone_name=record.timezone, review=data["permissions"]["can_review"])
        item.update(assignee_id=record.assignee_id, assignee_name=record.assignee_name)
        items.append(item)
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
    raw, truncated = await _records(db, candidates)
    bindings = {}
    # The candidate query already enforces active binding + connection and
    # exact Google grants for staff. _customers applied the same explicit
    # delivery-read check as media._customer. Validate connection owners in
    # bulk rather than making four native _binding reads for every merchant.
    connections, _ = await _records(db, select(Connection).where(Connection.id.in_({r.connection_id for r in raw})))
    owners, _ = await _records(db, select(Employees).where(Employees.id.in_({r.owner_id for r in connections})))
    valid_owners = {r.id for r in owners if r.status in {"active", "probation"} and normalized_role(SimpleNamespace(role=r.role)) == "super_admin"}
    valid_connections = {r.id for r in connections if r.active and r.owner_id in valid_owners and (not ctx.owner or r.owner_id == ctx.identity)}
    for candidate in raw:
        if candidate.connection_id in valid_connections: bindings[candidate.id] = candidate
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
        schedules, cut = await _records(db, query); truncated |= cut
        submitted_rows, _ = await _records(db, select(Action).where(Action.id.in_({r.action_id for r in schedules if r.action_id})))
        submitted_actions = {r.id: r for r in submitted_rows}
        for row in schedules:
            b = bindings[row.binding_id]
            status = row.status
            if row.action_id:
                submitted = submitted_actions.get(row.action_id)
                if submitted and submitted.binding_id == b.id and submitted.task_id == row.task_id and submitted.kind == "post_publish":
                    status = submitted.status
                else: status = "unknown"
            # Content frozen by the existing publication approval is presented
            # only in its native preview, never reconstructed from today's task.
            item = _row("google_schedule", row, customers[b.customer_id], "google_business", title="Google 帖子排期",
                status=status, at=row.planned_at, basis="scheduled_publish", revision=row.revision, binding=b,
                timezone_name=row.timezone, navigation={"workspace": "google", "binding_id": b.id, "schedule_id": row.id, "task_id": row.task_id})
            item.update(assignee_id=row.operator_id, assignee_name=None)
            items.append(item)
    else: truncated = True
    query = select(Action).where(Action.binding_id.in_(bindings), Action.kind.in_(PUBLIC_KINDS), Action.created_at >= start, Action.created_at < end).order_by(Action.created_at, Action.id)
    actions, cut = await _records(db, query); truncated |= cut
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
        drafts, cut = await _records(db, query); truncated |= cut
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
    raw, truncated = await _records(db, query)
    bindings = {}
    for candidate in raw:
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
        records, cut = await _records(db, query); truncated |= cut
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
    from models.media_monthly_workflow import MediaMonthlyWorkflow as MonthlyWorkflow
    if await tables_available(db, {MonthlyWorkflow.__tablename__}):
        packets = (await db.scalars(select(MonthlyWorkflow).where(MonthlyWorkflow.owner_id == ctx.identity, MonthlyWorkflow.customer_id.in_(customers)))).all()
        monthly_drafts = {ref["draft_id"]: packet for packet in packets if packet.snapshot.get("platform") in {"facebook", "instagram"} for ref in packet.task_refs if "draft_id" in ref}
        items = [r for r in items if r["kind"] != "meta_draft" or r["source_id"] not in monthly_drafts]
        for r in items:
            packet = monthly_drafts.get(r["navigation"].get("draft_id"))
            if packet:
                r["navigation"] = {"workspace": "monthly", "run_id": packet.run_id, "platform": r["platform"], "month": packet.snapshot.get("source", {}).get("month")}
    # The provider cache can contain several reads of one external object.
    # Take the newest valid snapshot, then validate the opaque parent chain.
    query = select(Target).where(Target.owner_id == ctx.identity, Target.binding_id.in_(bindings), Target.expires_at > now()).order_by(Target.created_at.desc(), Target.id.desc())
    targets, cut = await _records(db, query); truncated |= cut
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


async def _monthly(db, ctx, customers, start, end, platform, view):
    if not ctx.owner:
        return [], {}, _source("monthly", "locked", "月度草稿当前仅由老板核对，不开放额外员工权限"), False
    if not customers or view == "inbox":
        return [], {}, _source("monthly", message="当前范围不包含可查看的月度草稿"), False
    from services import media_monthly as monthly
    if not await tables_available(db, monthly.TABLES):
        return [], {}, _source("monthly", "missing", "月度草稿准备尚未启用"), False
    rows = await monthly.workspace_rows(db, ctx.user, customer_ids=list(customers), start=start, end=end, view=view, platform=platform)
    # A batch's editorial month is persisted on its exact run. Its creation
    # timestamp, display title and UTC query boundary are not that month.
    # In particular a Beijing November range starts on October31 in UTC.
    identities = {r["source_id"] for r in rows if r["kind"] == "monthly_run" and type(r.get("source_id")) is int}
    metadata = await _tuples(db, select(monthly.Run.id, monthly.Run.customer_id, monthly.Run.month).where(
        monthly.Run.owner_id == ctx.identity, monthly.Run.customer_id.in_(customers), monthly.Run.id.in_(identities))) if identities else []
    months = {(identity, customer): _review_month(month) for identity, customer, month in metadata}
    verified, incomplete = [], False
    for row in rows:
        if row["kind"] == "monthly_run":
            month = months.get((row.get("source_id"), row.get("customer_id")))
            if month is None:
                incomplete = True
                continue  # No guessed month or wrong-month navigation target.
            row = row | {"review_month": month}
        verified.append(row)
    message = "部分月度批次的月份资料待核对，请进入原月度计划检查" if incomplete else "月度日期为建议发布时间；采用为任务和内部审核均不会自动公开发布"
    return verified, {}, _source("monthly", "error" if incomplete else "ready", message), incomplete


async def _gather(db, ctx, customers, permissions, start, end, platform, view="overview"):
    tasks, truncated = await _tasks(db, ctx, customers, permissions, start, end, platform)
    google, gb, gs, cut = await _optional(db, "google", lambda: _google(db, ctx, customers, start, end, platform)); truncated |= cut
    meta, mb, ms, cut = await _optional(db, "meta", lambda: _meta(db, ctx, customers, start, end, platform)); truncated |= cut
    monthly, _, monthly_source, cut = await _optional(db, "monthly", lambda: _monthly(db, ctx, customers, start, end, platform, view)); truncated |= cut
    by_customer = {b.customer_id: b for b in gb.values()}
    for row in tasks:
        if row["platform"] == "google_business" and row["customer_id"] in by_customer:
            b = by_customer[row["customer_id"]]
            row.update(binding_id=b.id, binding_revision=b.revision, account_label=b.title)
    return tasks + google + meta + monthly, gb, mb, [_source("tasks", message="仅本人任务或老板可查看的任务；日期为内部完成期限"), gs, ms, monthly_source], truncated


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


def _summary(rows):
    return {"tasks": sum(r["kind"] == "task" for r in rows),
        "drafts": sum(r["kind"] in {"meta_draft", "google_reply_draft", "task"} and r["status"] == "draft" for r in rows),
        "in_review": sum(r["kind"] == "task" and r["status"] == "in_review" for r in rows),
        "ready": sum(r["kind"] == "task" and r["status"] == "ready" for r in rows),
        "scheduled": sum(r["kind"] in {"google_schedule", "meta_schedule"} and r["status"] == "scheduled" for r in rows),
        "blocked": sum(r["status"] in {"blocked", "failed", "missed", "rejected"} for r in rows),
        "unknown": sum(r["status"] in {"unknown", "pending", "accepted"} for r in rows),
        "inbox": sum(r["kind"] in {"meta_comment", "google_reply_draft"} for r in rows),
        "review_candidates": sum(r["review_eligible"] for r in rows)}


def _filters(status, operator_id):
    if status not in FILTERS: raise HTTPException(422, "请选择有效的商家工作筛选")
    if operator_id is not None and (type(operator_id) is not int or operator_id < 1):
        raise HTTPException(422, "请选择有效的主要运营")


def _period(start, end):
    if (start is None) != (end is None): raise HTTPException(422, "请同时提供开始和结束日期")
    if start is None:
        start = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start + timedelta(days=32)).replace(day=1)
    return planning.window(start, end, maximum=366)


def _review_row(row):
    return row["review_eligible"] or row["kind"] in {"meta_draft", "google_reply_draft", "monthly_run"}


async def _upcoming(db, ctx, gb, mb):
    """Exact saved future queues, independent of the selected reporting month.

    These are not a provider-wide content audit. Already dispatched, cancelled
    and merely suggested times never count as upcoming scheduled coverage.
    """
    from models.google_business import GoogleBusinessSchedule as GSchedule, GoogleBusinessBinding as GBinding
    from models.meta_operations import MetaOperationsSchedule as MSchedule
    values, complete = [], True
    if gb:
        if await tables_available(db, {GSchedule.__tablename__}):
            query = select(GSchedule).join(Task, Task.id == GSchedule.task_id).join(GBinding, GBinding.id == GSchedule.binding_id).where(
                GSchedule.binding_id.in_(gb), GSchedule.status == "scheduled", GSchedule.action_id.is_(None), GSchedule.planned_at >= now(),
                Task.customer_id == GBinding.customer_id, Task.platform == "google_business").order_by(GSchedule.planned_at, GSchedule.id)
            if not ctx.owner: query = query.where(Task.assignee_id == ctx.identity)
            records, _ = await _records(db, query)
            values.extend({"customer_id": gb[r.binding_id].customer_id, "at": aware(r.planned_at), "timezone": r.timezone} for r in records)
        else: complete = False
    if mb:
        if await tables_available(db, {MSchedule.__tablename__}):
            records, _ = await _records(db, select(MSchedule).where(MSchedule.owner_id == ctx.identity, MSchedule.binding_id.in_(mb),
                MSchedule.status == "scheduled", MSchedule.action_id.is_(None), MSchedule.planned_at >= now()).order_by(MSchedule.planned_at, MSchedule.id))
            values.extend({"customer_id": mb[r.binding_id].customer_id, "at": aware(r.planned_at), "timezone": r.timezone} for r in records)
        else: complete = False
    return values, complete


async def _portfolio(db, ctx, customers, permissions, rows, gb, mb, *, platform, complete):
    platforms = {k: set() for k in customers}; zones = {k: set() for k in customers}
    pairs = select(Task.customer_id, Task.platform, Task.timezone).where(Task.customer_id.in_(customers)).distinct().order_by(Task.customer_id, Task.platform, Task.timezone)
    if not ctx.owner: pairs = pairs.where(Task.assignee_id == ctx.identity)
    for identity, value, zone in await _tuples(db, pairs):
        if value in dict(media.PLATFORMS): platforms[identity].add(value)
        if isinstance(zone, str) and zone: zones[identity].add(zone)
    for b in gb.values(): platforms[b.customer_id].add("google_business")
    for b in mb.values(): platforms[b.customer_id].add(b.platform)
    identities = {b.primary_operator_id for b in gb.values() if b.primary_operator_id}
    identities.update(r.get("assignee_id") for r in rows if r.get("assignee_id"))
    people, _ = await _records(db, select(Employees).where(Employees.id.in_(identities), Employees.status.in_({"active", "probation"})))
    people = {r.id: r for r in people}
    active_google = {b.id: b for b in gb.values() if b.lifecycle == "active" and customers[b.customer_id].status == "closed"}
    active_meta = {b.id: b for b in mb.values() if customers[b.customer_id].status == "closed"}
    primary = {b.customer_id: people[b.primary_operator_id] for b in active_google.values() if b.primary_operator_id in people}
    google_customers = {b.customer_id for b in active_google.values()}
    connected_customers = google_customers | {b.customer_id for b in active_meta.values()}
    from models.google_business import GoogleBusinessConnection as Connection
    reconnect = set()
    if gb:
        connections, _ = await _records(db, select(Connection).where(Connection.id.in_({b.connection_id for b in gb.values()}), Connection.needs_reconnect.is_(True)))
        reconnect = {b.customer_id for b in gb.values() if b.connection_id in {r.id for r in connections}}
    try:
        async with db.begin_nested():
            future, queues_complete = await _upcoming(db, ctx, active_google, active_meta)
    except (SQLAlchemyError, SchemaUnavailableError):
        future, queues_complete = [], False
    complete = bool(complete and queues_complete)
    by_customer = {k: [] for k in customers}; future_by_customer = {k: [] for k in customers}
    for row in rows: by_customer[row["customer_id"]].append(row)
    for row in future: future_by_customer[row["customer_id"]].append(row)
    instant = now(); horizon = instant + timedelta(days=7)
    items = []
    for customer in customers.values():
        if platform and platform not in platforms[customer.id]: continue
        records = by_customer[customer.id]; summary = _summary(records)
        overdue = sum(r["kind"] == "task" and r["status"] not in {"completed"} and r["at"] and datetime.fromisoformat(r["at"]) < instant for r in records)
        waiting = sum(r["kind"] == "task" and r["status"] == "in_review" or r["kind"] in {"meta_draft", "google_reply_draft"} and r["status"] == "draft" or r["kind"] == "monthly_run" and r["status"] in {"prepared", "reviewed", "generated", "schedule_prepared"} for r in records)
        upcoming = future_by_customer[customer.id]
        next_publication = min(upcoming, key=lambda r: r["at"]) if upcoming else None
        operator = primary.get(customer.id)
        operating = "not_cooperating" if customer.status != "closed" else "active" if customer.id in connected_customers else "pending_connection" if complete else "unknown"
        assignment = "assigned" if operator else "unassigned" if customer.id in google_customers else "not_applicable"
        issues = []
        if operating == "active" and customer.id in reconnect: issues.append({"code": "authorization", "label": "Google 需要重新授权", "severity": "high"})
        if summary["blocked"]: issues.append({"code": "blocked", "label": f"{summary['blocked']} 条受阻或失败记录", "severity": "high"})
        if summary["unknown"]: issues.append({"code": "result_unknown", "label": f"{summary['unknown']} 条执行结果待核对", "severity": "high"})
        if waiting: issues.append({"code": "review", "label": f"{waiting} 项待审核或确认", "severity": "medium"})
        if overdue and operating != "not_cooperating": issues.append({"code": "overdue", "label": f"{overdue} 项任务已逾期", "severity": "medium"})
        if assignment == "unassigned": issues.append({"code": "unassigned", "label": "尚未指定 Google 主要运营", "severity": "medium"})
        if not complete: issues.append({"code": "source_unavailable", "label": "部分本地来源尚未完整读取", "severity": "medium"})
        next_seven = sum(instant <= value["at"] < horizon for value in upcoming)
        if complete and operating == "active" and not next_seven: issues.append({"code": "no_schedule", "label": "未来7天暂无已保存排期", "severity": "info"})
        items.append({"id": customer.id, "name": customer.business_name, "platforms": sorted(platforms[customer.id]),
            "can_create": bool(ctx.can_create and permissions[customer.id]["modules"]["delivery"]["write"]),
            "can_edit": bool(ctx.can_edit and permissions[customer.id]["modules"]["delivery"]["write"]),
            "region": (", ".join(x for x in (customer.city, customer.state) if isinstance(x, str) and x.strip()) or None) if permissions[customer.id]["modules"]["basic"]["read"] else None,
            "industry": customer.industry if permissions[customer.id]["modules"]["basic"]["read"] else None,
            "timezone": next(iter(zones[customer.id])) if len(zones[customer.id]) == 1 else None,
            "cooperation_status": customer.status if permissions[customer.id]["modules"]["basic"]["read"] else None,
            "operating_state": operating, "assignment_state": assignment,
            "primary_operator_id": operator.id if operator else None, "primary_operator_name": operator.name if operator else None,
            "in_review": waiting, "blocked": summary["blocked"], "overdue": overdue, "scheduled": summary["scheduled"],
            "next_publish_at": iso(next_publication["at"]) if next_publication else None,
            "next_publish_timezone": next_publication["timezone"] if next_publication else None,
            "next_7_days_count": next_seven if complete and operating == "active" else None,
            "coverage_state": "not_applicable" if operating == "not_cooperating" else "not_connected" if operating == "pending_connection" else "scheduled" if next_seven else "none_saved" if complete else "unknown",
            "data_state": "complete" if complete else "partial", "issues": issues})
    summary = {"merchants": len(items), "attention": sum(any(x["severity"] != "info" for x in r["issues"]) for r in items),
        "review": sum(r["in_review"] > 0 for r in items), "unassigned": sum(r["assignment_state"] == "unassigned" for r in items),
        "no_schedule": sum(r["coverage_state"] == "none_saved" for r in items)}
    operators = {}
    for identity, employee in people.items():
        if not ctx.owner and identity != ctx.identity: continue
        operators[identity] = {"id": identity, "name": employee.name, "merchants": 0, "tasks": 0, "in_review": 0, "overdue": 0, "blocked": 0, "completed": 0, "scheduled": 0}
    selected = {r["id"] for r in items}
    for row in items:
        if row["primary_operator_id"] in operators: operators[row["primary_operator_id"]]["merchants"] += 1
    for row in rows:
        if row["customer_id"] not in selected or row.get("assignee_id") not in operators: continue
        operator = operators[row["assignee_id"]]
        if row["kind"] == "task":
            operator["tasks"] += 1
            for key in ("in_review", "blocked", "completed"):
                operator[key] += int(row["status"] == key)
            operator["overdue"] += int(row["status"] != "completed" and bool(row["at"]) and datetime.fromisoformat(row["at"]) < instant)
        elif row["kind"] == "google_schedule" and row["status"] == "scheduled": operator["scheduled"] += 1
    return {"items": items, "summary": summary, "exceptions": [r for r in items if any(x["severity"] != "info" for x in r["issues"])],
        "operators": sorted(operators.values(), key=lambda r: (-r["overdue"], -r["tasks"], r["id"])),
        "sources_complete": complete, "source_mode": "local_saved", "observed_at": iso(instant)}


def _queue_month(start, end):
    local = start.astimezone(ZoneInfo("Asia/Shanghai")); through = end.astimezone(ZoneInfo("Asia/Shanghai"))
    if (local.day, local.hour, local.minute, local.second, local.microsecond) != (1, 0, 0, 0, 0): return None
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    if (through.year, through.month, through.day, through.hour, through.minute, through.second, through.microsecond) != (year, month, 1, 0, 0, 0, 0): return None
    return local.strftime("%Y-%m")


async def _work_queues(db, ctx, customers, permissions, items, rows, gb, mb, start, end, *, complete, platform=None):
    """Bulk local preparation checks. Not a publication/permission authority."""
    from models.media_monthly import MediaMonthlyProfile as Profile, MediaMonthlyRun as Run, MediaMonthlyItem as Item
    from models.media_monthly_workflow import MediaMonthlyWorkflow as Workflow
    from models.media_publication_images import MediaPublicationImage as Image
    from services import media_publication_images as publication_images
    from models.customer_materials import Customer_materials as Material
    from models.customer_menu_items import Customer_menu_items as Menu
    from services import media_monthly as monthly
    month = _queue_month(start, end); profiles, runs, entries, workflows = {}, {}, {}, {}
    owner_data = ctx.owner and await tables_available(db, monthly.TABLES | {Workflow.__tablename__})
    if owner_data:
        profiles = {r.customer_id: r for r in (await _records(db, select(Profile).where(Profile.owner_id == ctx.identity, Profile.customer_id.in_(customers))))[0]}
        if month:
            for run in (await _records(db, select(Run).where(Run.owner_id == ctx.identity, Run.customer_id.in_(customers), Run.month == month, Run.status != "archived").order_by(Run.id.desc())))[0]:
                if platform and monthly.run_platform(run) != platform: continue
                runs.setdefault((run.customer_id, monthly.run_platform(run)), run)
            ids = {r.id for r in runs.values()}
            for entry in (await _records(db, select(Item).where(Item.run_id.in_(ids))))[0]: entries.setdefault(entry.run_id, []).append(entry)
            workflows = {r.run_id: r for r in (await _records(db, select(Workflow).where(Workflow.owner_id == ctx.identity, Workflow.run_id.in_(ids), Workflow.customer_id.in_(customers))))[0]}
    material_customers = {identity for identity in customers if permissions[identity]["modules"]["materials"]["read"]}
    mats, menus, source_materials, fixed_images, sources_ok = {}, {}, {}, {}, True
    if await tables_available(db, {Material.__tablename__, Menu.__tablename__}):
        for material in (await _records(db, select(Material).where(Material.customer_id.in_(material_customers), Material.visibility == "team")))[0]:
            mats.setdefault(material.customer_id, set()).add(material.id); source_materials[material.id] = material
        for identity, menu_id in await _tuples(db, select(Menu.customer_id, Menu.id).where(Menu.customer_id.in_(material_customers), Menu.status == "active")):
            menus.setdefault(identity, set()).add(menu_id)
    else: sources_ok = False
    if ctx.owner and await tables_available(db, {Image.__tablename__}):
        for image in (await _records(db, select(Image).where(Image.customer_id.in_(material_customers), Image.revoked_at.is_(None))))[0]:
            material = source_materials.get(image.material_id)
            if material and image.customer_id == material.customer_id and image.source_fingerprint == publication_images.source_fingerprint(material) and not monthly._quality(image):
                fixed_images[image.id] = image
    records = {identity: [] for identity in customers}
    for row in rows: records[row["customer_id"]].append(row)
    for item in items:
        identity = item["id"]; current = records[identity]; customer = customers[identity]
        queue_platforms = sorted(set(item["platforms"]) & {"google_business", "facebook", "instagram"})
        queue_platform = platform or ("google_business" if "google_business" in queue_platforms else queue_platforms[0] if queue_platforms else None)
        profile = monthly.effective_profile(profiles.get(identity), queue_platform) if queue_platform else None; run = runs.get((identity, queue_platform)); workflow = workflows.get(run.id) if run else None
        target = None; rule_ok = False
        if profile and month:
            try: target = len(monthly.slots(month, profile.rules)); rule_ok = True
            except HTTPException: pass
        tasks = {r["id"]: r for r in current if r["kind"] == "task"}
        prepared = sum(r["status"] in {"draft", "in_review", "ready", "completed"} for r in tasks.values())
        reviewing = sum(r["status"] == "in_review" for r in tasks.values())
        scheduled = len({r["navigation"].get("task_id", r["id"]) for r in current if r["kind"] in {"google_schedule", "meta_schedule"} and r["status"] in {"scheduled", "dispatching", "pending", "processing", "accepted"}})
        published = len({r["navigation"].get("task_id", r["id"]) for r in current if r["kind"] in {"google_schedule", "meta_schedule", "meta_post"} and r["status"] == "succeeded"})
        basis = "authorized_records"; batch = entries.get(run.id, []) if run else []
        if run:
            basis = "monthly_plan"; target = len(run.snapshot.get("slots", [])) or target
            prepared = len(batch)
            task_ids = {ref["task_id"] for ref in workflow.task_refs if "task_id" in ref} if workflow else {entry.task_id for entry in batch if entry.task_id}
            reviewing = len(batch) if workflow and workflow.status == "prepared" else sum(r["navigation"].get("task_id") in task_ids and r["kind"] == "task" and r["status"] == "in_review" for r in current)
            schedule_ids = {ref["schedule_id"] for ref in workflow.schedule_refs} if workflow else set()
            monthly_schedules = [r for r in current if r["kind"] in {"google_schedule", "meta_schedule"} and r["source_id"] in schedule_ids and r["platform"] == queue_platform]
            scheduled = sum(r["status"] in {"scheduled", "dispatching", "pending", "processing", "accepted"} for r in monthly_schedules)
            published = sum(r["status"] == "succeeded" for r in monthly_schedules)
        checks = []
        def check(key, label, state): checks.append({"key": key, "label": label, "state": state})
        active = customer.status == "closed"
        check("cooperation", "合作中" if active else "非合作客户，仅保留历史", "ready" if active else "blocked")
        check("account", "平台已连接，发布前仍需核对授权" if item["operating_state"] == "active" else "请连接当前平台账号", "ready" if item["operating_state"] == "active" else "unknown" if not complete else "missing")
        if identity in material_customers:
            check("materials", f"已有{len(mats.get(identity, []))}项共享素材，实际图片需逐项核对" if mats.get(identity) else "尚无共享素材", "ready" if mats.get(identity) else "missing" if sources_ok else "unknown")
        else: check("materials", "素材需由有权限的同事核对", "unknown")
        if ctx.owner and queue_platform in item["platforms"]:
            if "google_business" in item["platforms"] and platform in {None, "google_business"}:
                check("operator", "Google主要运营已指定" if item["assignment_state"] == "assigned" else "请老板指定Google主要运营", "ready" if item["assignment_state"] == "assigned" else "missing")
            check("rules", "月度频率与时区已保存" if rule_ok else "请选择整月并确认本商家频率与时区", "ready" if rule_ok else "missing" if owner_data else "unknown")
            images_ok = bool(profile and profile.images and all(choice.get("image_version_id") in fixed_images and fixed_images[choice["image_version_id"]].customer_id == identity and fixed_images[choice["image_version_id"]].material_id == choice.get("material_id") for choice in profile.images))
            check("images", "固定图片版本已保存，发布前仍需核验实际图片" if images_ok else "请确认合格的固定图片版本", "ready" if images_ok else "missing" if sources_ok else "unknown")
            facts_ok = bool(profile and profile.public_facts and profile.public_facts.get("public_name") and profile.public_facts.get("location") and profile.public_facts.get("highlights"))
            check("facts", "公开事实已保存" if facts_ok else "请确认公开店名、位置和卖点", "ready" if facts_ok else "missing" if owner_data else "unknown")
            menu_ok = bool(profile and (profile.rules.get("generic_mode") is True or profile.menu_item_ids and set(profile.menu_item_ids).issubset(menus.get(identity, set()))))
            check("menu", "菜单或仅公开事实模式已确认" if menu_ok else "请核对所选菜单或明确仅公开事实模式", "ready" if menu_ok else "missing" if sources_ok else "unknown")
        if run:
            check("batch", "已有本月批次，请继续原批次" if run.status not in {"unknown", "generating", "failed"} else "原生成结果需先核对，不会重复新建", "blocked" if run.status in {"unknown", "generating", "failed"} else "ready")
        if item.get("blocked") or item.get("overdue"): check("exceptions", "先处理失败、受阻或逾期记录", "blocked")
        if not complete or not sources_ok: check("sources", "本地资料尚未完整读取", "unknown")
        readiness = "not_applicable" if not active else "blocked" if any(c["state"] == "blocked" for c in checks) else "unknown" if any(c["state"] == "unknown" for c in checks) else "needs_setup" if any(c["state"] == "missing" for c in checks) else "ready"
        can_monthly = bool(ctx.owner and active and queue_platform in item["platforms"] and owner_data and permissions[identity]["modules"]["delivery"]["write"] and permissions[identity]["modules"]["materials"]["read"])
        if not active: action = {"kind": "content", "label": "查看历史内容"}
        elif can_monthly and run: action = {"kind": "monthly", "label": "继续本月清单", "run_id": run.id, "platform": queue_platform, "month": run.month if run else month}
        elif item["operating_state"] != "active": action = {"kind": "accounts", "label": "核对平台账号"}
        elif not mats.get(identity) and identity in material_customers: action = {"kind": "materials", "label": "补齐共享素材"}
        elif can_monthly: action = {"kind": "monthly", "label": "准备本月内容" if rule_ok else "设置月度规则", "platform": queue_platform, "month": run.month if run else month}
        elif reviewing: action = {"kind": "review", "label": "查看待审核内容"}
        else: action = {"kind": "content", "label": "查看授权工作内容"}
        progress = []
        for candidate_platform in queue_platforms:
            if platform and candidate_platform != platform: continue
            candidate_run = runs.get((identity, candidate_platform)); candidate_flow = workflows.get(candidate_run.id) if candidate_run else None
            candidate_profile = monthly.effective_profile(profiles.get(identity), candidate_platform)
            candidate_target = None
            if candidate_profile and month:
                try: candidate_target = len(monthly.slots(month, candidate_profile.rules))
                except HTTPException: pass
            candidate_batch = entries.get(candidate_run.id, []) if candidate_run else []
            candidate_refs = {r["schedule_id"] for r in candidate_flow.schedule_refs} if candidate_flow else set()
            candidate_schedules = [r for r in current if r["platform"] == candidate_platform and r["kind"] in {"google_schedule", "meta_schedule"} and (not candidate_run or r["source_id"] in candidate_refs)]
            candidate_status = candidate_flow.status if candidate_flow else candidate_run.status if candidate_run else "needs_setup"
            progress.append({"platform": candidate_platform, "month": candidate_run.month if candidate_run else month, "run_id": candidate_run.id if candidate_run else None, "status": candidate_status,
                "target": len(candidate_run.snapshot.get("slots", [])) if candidate_run else candidate_target,
                "prepared": len(candidate_batch), "in_review": len(candidate_batch) if candidate_flow and candidate_flow.status == "prepared" else 0,
                "schedule_prepared": sum(r["status"] == "prepared" for r in candidate_schedules),
                "scheduled": sum(r["status"] in {"scheduled", "dispatching", "pending", "processing", "accepted"} for r in candidate_schedules),
                "published": sum(r["status"] == "succeeded" for r in candidate_schedules),
                "can_prepare_monthly": bool(ctx.owner and active and owner_data and permissions[identity]["modules"]["delivery"]["write"] and permissions[identity]["modules"]["materials"]["read"])})
        if not platform and len(progress) > 1:
            target = sum(r["target"] or 0 for r in progress) if any(r["target"] is not None for r in progress) else None
            prepared = sum(r["prepared"] for r in progress); reviewing = sum(r["in_review"] for r in progress)
            scheduled = sum(r["scheduled"] for r in progress); published = sum(r["published"] for r in progress)
            basis = "multi_platform_monthly"
            candidates = [r for r in progress if r["can_prepare_monthly"]]
            if candidates:
                priority = {"failed": 0, "unknown": 0, "prepared": 1, "generated": 1, "reviewed": 2, "schedule_prepared": 3, "needs_setup": 4, "scheduled": 5}
                next_platform = min(candidates, key=lambda r: (priority.get(r["status"], 4), r["platform"]))
                label = {"google_business": "Google", "facebook": "Facebook", "instagram": "Instagram"}[next_platform["platform"]]
                action = {"kind": "monthly", "label": "继续" + label + "本月清单" if next_platform["run_id"] else "准备" + label + "本月内容", "platform": next_platform["platform"], "month": next_platform["month"]}
                if next_platform["run_id"]: action["run_id"] = next_platform["run_id"]
        if not platform and any(r["status"] == "needs_setup" for r in progress) and readiness == "ready": readiness = "needs_setup"
        item["work_queue"] = {"platform": platform or (queue_platform if len(progress) <= 1 else None), "platforms": queue_platforms, "platform_progress": progress, "schedule_prepared": sum(r["schedule_prepared"] for r in progress), "month": month, "basis": basis, "target": target if ctx.owner else None,
            "prepared": prepared, "in_review": reviewing, "scheduled": scheduled, "published": published,
            "readiness": readiness, "checks": checks, "next_action": action, "can_prepare_monthly": can_monthly}
    return items


def _matching(items, status, operator_id):
    return [r for r in items if (operator_id is None or r["primary_operator_id"] == operator_id) and (
        status == "all" or status == "attention" and any(i["severity"] != "info" for i in r["issues"]) or
        status == "review" and r["in_review"] > 0 or status == "unassigned" and r["assignment_state"] == "unassigned" or
        status == "no_schedule" and r["coverage_state"] == "none_saved")]


def _calendar_days(rows):
    result = {}
    for row in rows:
        if not row["at"]: continue
        day = datetime.fromisoformat(row["at"]).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
        entry = result.setdefault(day, {"date": day, "total": 0, "scheduled": 0, "suggested": 0, "task_due": 0, "blocked": 0})
        entry["total"] += 1
        entry["scheduled"] += int(row["time_basis"] == "scheduled_publish" and row["status"] == "scheduled")
        entry["suggested"] += int(row["time_basis"] == "proposed_publish")
        entry["task_due"] += int(row["time_basis"] == "task_due")
        entry["blocked"] += int(row["status"] in {"blocked", "failed", "missed", "rejected"})
    return sorted(result.values(), key=lambda r: r["date"])


def _review_month(value):
    if not isinstance(value, str) or len(value) != 7: return None
    try:
        parsed = datetime.strptime(value, "%Y-%m")
        return value if parsed.strftime("%Y-%m") == value else None
    except ValueError:
        return None


def _review_groups(rows, start):
    result = {}
    for row in rows:
        if not _review_row(row): continue
        if row["kind"] == "monthly_run":
            month = _review_month(row.get("review_month"))
            if month is None: continue
        else:
            if not row["at"]: continue
            # Match the workspace date inputs/calendar/focus navigation basis,
            # not the provider timezone or the UTC representation of the row.
            month = datetime.fromisoformat(row["at"]).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")
        entry = result.setdefault((row["customer_id"], month, row["platform"]), {"customer_id": row["customer_id"], "name": row["customer_name"], "month": month, "platform": row["platform"], "total": 0, "in_review": 0, "platforms": set()})
        entry["total"] += 1; entry["in_review"] += int(row["status"] == "in_review"); entry["platforms"].add(row["platform"])
    return [r | {"platforms": sorted(r["platforms"])} for _, r in sorted(result.items())]


async def merchants(db, user, *, q=None, platform=None, customer_id=None, start=None, end=None, status="all", operator_id=None, cursor=None, limit=50):
    ctx = await context(db, user); platform = _platform(platform); _filters(status, operator_id)
    q = q.strip() if isinstance(q, str) else None
    if q and len(q) > 100: raise HTTPException(422, "搜索内容过长")
    start, end = _period(start, end)
    customers, permissions, truncated = await _customers(db, ctx, customer_id, q=q)
    rows, gb, mb, sources, cut = await _gather(db, ctx, customers, permissions, start, end, platform)
    portfolio = await _portfolio(db, ctx, customers, permissions, rows, gb, mb, platform=platform, complete=not(truncated or cut))
    await _work_queues(db, ctx, customers, permissions, portfolio["items"], rows, gb, mb, start, end, complete=portfolio["sources_complete"], platform=platform)
    items = _matching(portfolio["items"], status, operator_id)
    items.sort(key=lambda r: (-sum(i["severity"] == "high" for i in r["issues"]), -sum(i["severity"] == "medium" for i in r["issues"]), r["id"]))
    scope = {"q": q, "platform": platform, "customer_id": customer_id, "view": "merchants", "status": status, "operator_id": operator_id, "start": iso(start), "end": iso(end)}
    page, following = _paginate(items, ctx=ctx, scope=scope, sources=sources, cursor=cursor, limit=limit)
    return {"items": page, "next_cursor": following, "total": len(items), "has_more": bool(following),
        "partial": bool(not portfolio["sources_complete"] or following), "sources_complete": portfolio["sources_complete"],
        "sources": sources, "observed_at": portfolio["observed_at"], "summary": portfolio["summary"], "operators": portfolio["operators"],
        "source_mode": "local_saved", "scope": scope, "range": {"start": iso(start), "end": iso(end)}}


async def workspace(db, user, *, start, end, customer_id=None, platform=None, view="overview", status="all", operator_id=None, cursor=None, limit=50):
    ctx = await context(db, user); start, end = _period(start, end); platform = _platform(platform); _filters(status, operator_id)
    if view not in VIEWS: raise HTTPException(422, "请选择有效工作视图")
    customers, permissions, truncated = await _customers(db, ctx, customer_id)
    # Portfolio decisions use one canonical source view. A monthly batch is
    # one review batch everywhere; suggested calendar slots do not change the
    # merchant's review/exception totals when the user switches tabs.
    rows, gb, mb, sources, cut = await _gather(db, ctx, customers, permissions, start, end, platform, "overview")
    portfolio = await _portfolio(db, ctx, customers, permissions, rows, gb, mb, platform=platform, complete=not(truncated or cut))
    matches = _matching(portfolio.pop("items"), status, operator_id)
    selected = {r["id"] for r in matches}; rows = [r for r in rows if r["customer_id"] in selected]
    portfolio["exceptions"] = [r for r in portfolio["exceptions"] if r["id"] in selected]
    portfolio["filtered_merchants"] = len(matches)
    rows.sort(key=lambda r: (r["at"] or "", r["id"]), reverse=True)
    summary = _summary(rows)
    groups = _review_groups(rows, start)
    if view == "review": rows = [r for r in rows if _review_row(r)]
    elif view == "inbox": rows = [r for r in rows if r["kind"] in {"meta_comment", "google_reply_draft"}]
    elif view == "calendar":
        slots, _, monthly_source, calendar_cut = await _optional(db, "monthly", lambda: _monthly(db, ctx,
            {k: v for k, v in customers.items() if k in selected}, start, end, platform, "calendar"))
        if calendar_cut:
            portfolio["sources_complete"] = False
            sources = [monthly_source if r["key"] == "monthly" else r for r in sources]
        rows = [r for r in rows if r["kind"] in {"task", "google_schedule", "meta_schedule", "meta_post"}] + slots
        rows.sort(key=lambda r: (r["at"] or "", r["id"]), reverse=True)
    days = _calendar_days(rows) if view == "calendar" else []
    scope = {"customer_id": customer_id, "platform": platform, "view": view, "status": status, "operator_id": operator_id}
    period = {"start": iso(start), "end": iso(end)}
    page, following = _paginate(rows, ctx=ctx, scope={**scope, **period}, sources=sources, cursor=cursor, limit=limit)
    return {"items": page, "next_cursor": following, "total": len(rows), "has_more": bool(following),
        "sources_complete": portfolio["sources_complete"], "inbox_complete": False,
        "partial": bool(not portfolio["sources_complete"] or following or view == "inbox"), "sources": sources, "observed_at": iso(now()),
        "scope": scope, "range": period, "summary": summary, "portfolio": portfolio, "calendar_days": days, "review_groups": groups,
        "capabilities": {"is_owner": ctx.owner, "meta_owner_only": True}}
