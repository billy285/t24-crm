"""Scoped content planning. A plan creates drafts, never approvals or posts."""
from datetime import datetime, timedelta, timezone
from uuid import uuid5, NAMESPACE_URL

from fastapi import HTTPException
from sqlalchemy import func, select

from models.customers import Customers
from models.media_operations import MediaOperationTask as Task
from models.media_planning import MediaContentPlan as Plan, MediaContentPlanTask as Link
from services import media_operations as media
from services.customer_permissions import customer_permissions_for_rows
from services.customers import CustomersService
from services.schema_readiness import require_tables, tables_available

TABLES = {"media_content_plans", "media_content_plan_tasks"}


def window(start, end, maximum=42):
    try:
        start, end = (datetime.fromisoformat(x.replace("Z", "+00:00")) if isinstance(x, str) else x for x in (start, end))
        if any(not isinstance(x, datetime) or x.tzinfo is None or x.utcoffset() is None for x in (start, end)):
            raise ValueError()
        start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
        if not datetime(2000, 1, 1, tzinfo=timezone.utc) <= start < end <= datetime(2101, 1, 1, tzinfo=timezone.utc) or end - start > timedelta(days=maximum):
            raise ValueError()
        return start, end
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise HTTPException(422, f"请选择包含明确时区、前后有效且不超过 {maximum} 天的时间范围")


async def scoped_tasks(db, ctx, customer_id=None):
    query = select(Task).join(Customers, Task.customer_id == Customers.id)
    scope = CustomersService._scope_filter_for_user(ctx.user, module="delivery")
    if scope is not None:
        query = query.where(scope)
    if not ctx.owner:
        # An employee can hold a customer invitation without owning every task.
        query = query.where(Task.assignee_id == ctx.identity)
    if customer_id is not None:
        await media._customer(db, ctx, customer_id)
        query = query.where(Task.customer_id == customer_id)
    return query


async def task_rows(db, ctx, rows):
    if not rows:
        return []
    customers = (await db.scalars(select(Customers).where(Customers.id.in_({r.customer_id for r in rows})))).all()
    permissions = await customer_permissions_for_rows(db, ctx.user, customers, config=ctx.config)
    items = [media._data(row, ctx, permissions[row.customer_id]) for row in rows
             if permissions[row.customer_id]["modules"]["delivery"]["read"] and (ctx.owner or permissions[row.customer_id]["explicit"])]
    await media._add_publications(db, items)
    await media._google_return_permissions(db, items)
    await media._redact_material_references(db, items)
    return items


async def calendar(db, user, *, start, end, customer_id=None, platform=None, skip=0, limit=100):
    ctx = await media.context(db, user)
    start, end = window(start, end)
    if platform is not None and platform not in dict(media.PLATFORMS):
        raise HTTPException(422, "请选择支持的平台")
    query = (await scoped_tasks(db, ctx, customer_id)).where(Task.due_at >= start, Task.due_at < end)
    if platform:
        query = query.where(Task.platform == platform)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await db.scalars(query.order_by(Task.due_at, Task.id).offset(skip).limit(limit))).all()
    return {"items": await task_rows(db, ctx, rows), "total": total, "skip": skip, "limit": limit,
            "from": media._iso(start), "to": media._iso(end), "basis": "task_due_at", "timezone": "Asia/Shanghai"}


async def summary(db, user, *, start, end, customer_id=None):
    ctx = await media.context(db, user)
    start, end = window(start, end, 366)
    query = await scoped_tasks(db, ctx, customer_id)
    ids = query.with_only_columns(Task.id)
    period = select(Task).where(Task.id.in_(ids), Task.due_at >= start, Task.due_at < end)
    status = {name: 0 for name in media.STATUSES}
    platforms = []
    for name, state, count in (await db.execute(select(Task.platform, Task.status, func.count()).where(
            Task.id.in_(period.with_only_columns(Task.id))).group_by(Task.platform, Task.status))).all():
        status[state] += count
        row = next((r for r in platforms if r["platform"] == name), None)
        if row is None:
            row = {"platform": name, **{s: 0 for s in media.STATUSES}}
            platforms.append(row)
        row[state] = count
    completed = await db.scalar(select(func.count()).select_from(Task).where(Task.id.in_(ids), Task.status == "completed",
            Task.completed_at >= start, Task.completed_at < end)) or 0
    overdue = await db.scalar(select(func.count()).select_from(Task).where(Task.id.in_(period.with_only_columns(Task.id)),
            Task.status != "completed", Task.due_at < media.now())) or 0
    by_operator = (await db.execute(select(Task.assignee_id, Task.assignee_name, Task.status, func.count()).where(
            Task.id.in_(period.with_only_columns(Task.id))).group_by(Task.assignee_id, Task.assignee_name, Task.status))).all()
    operators = {}
    for identity, name, state, count in by_operator:
        item = operators.setdefault(identity, {"id": identity, "name": name, **{s: 0 for s in media.STATUSES}})
        item[state] += count
    # Provider outcomes are a separate owner-only metric with existing Google
    # connection scope. They are never inferred from a task's manual completion.
    provider_totals = None
    if ctx.owner and await tables_available(db, {"google_business_actions", "google_business_bindings", "google_business_connections"}):
        from models.google_business import GoogleBusinessAction as Action, GoogleBusinessBinding as Binding, GoogleBusinessConnection as Connection
        binding_ids = select(Binding.id).join(Connection, Binding.connection_id == Connection.id).where(Connection.owner_id == ctx.identity)
        if customer_id is not None:
            binding_ids = binding_ids.where(Binding.customer_id == customer_id)
        provider_totals = {"post_succeeded": 0, "reply_succeeded": 0, "accepted": 0, "pending": 0, "unknown": 0, "rejected": 0, "failed": 0}
        # Confirmed results use confirmed_at; legacy successes lacking it are
        # counted separately and explicitly disclosed with the old updated time.
        fallback = 0
        actions = (await db.scalars(select(Action).where(Action.binding_id.in_(binding_ids),
            Action.kind.in_(("post_publish", "review_reply")),
            ((Action.confirmed_at >= start) & (Action.confirmed_at < end)) |
            ((Action.confirmed_at.is_(None)) & (Action.updated_at >= start) & (Action.updated_at < end))))).all()
        for action in actions:
            field = ("post_succeeded" if action.kind == "post_publish" else "reply_succeeded") if action.status == "succeeded" else action.status
            if field in provider_totals:
                provider_totals[field] += 1
            if action.status == "succeeded" and action.confirmed_at is None:
                fallback += 1
        provider_totals["legacy_time_fallback"] = fallback
    return {"from": media._iso(start), "to": media._iso(end), "status": status, "platforms": platforms,
            "operators": list(operators.values()), "completed_in_period": completed, "overdue": overdue,
            "provider_totals": provider_totals, "basis": "planned_by_due_at_completed_by_completed_at_provider_by_confirmation",
            "is_owner": ctx.owner}


async def _plan_data(db, ctx, plan):
    query = (await scoped_tasks(db, ctx, plan.customer_id)).join(Link, Link.task_id == Task.id).where(Link.plan_id == plan.id)
    rows = (await db.scalars(query.order_by(Task.id))).all()
    items = await task_rows(db, ctx, rows)
    if not items:
        raise HTTPException(404, "内容计划不存在或当前未获授权")
    return {"id": plan.id, "customer_id": plan.customer_id, "customer_name": items[0]["customer_name"], "title": plan.title,
            "brief": plan.brief, "created_at": media._iso(plan.created_at), "items": items}


async def list_plans(db, user, *, customer_id=None, skip=0, limit=20):
    ctx = await media.context(db, user)
    await require_tables(db, TABLES)
    visible = (await scoped_tasks(db, ctx, customer_id)).with_only_columns(Task.id)
    query = select(Plan).where(Plan.id.in_(select(Link.plan_id).where(Link.task_id.in_(visible))))
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await db.scalars(query.order_by(Plan.id.desc()).offset(skip).limit(limit))).all()
    return {"items": [await _plan_data(db, ctx, plan) for plan in rows], "total": total, "skip": skip, "limit": limit,
            "can_create": ctx.can_create}


async def request_result(db, user, request_id):
    ctx = await media.context(db, user)
    await require_tables(db, TABLES)
    key = media._key(request_id)
    row = await db.scalar(select(Plan).where(Plan.created_by_id == ctx.identity, Plan.request_id == key))
    if not row:
        raise HTTPException(404, "本次内容计划尚未登记，请保持原请求编号")
    return await _plan_data(db, ctx, row)


async def create_plan(db, user, *, request_id, customer_id, title, brief, variants, assignee_id=None):
    ctx = await media.context(db, user)
    await require_tables(db, TABLES)
    if not ctx.can_create:
        raise HTTPException(403, "运营新建功能尚未授权")
    key = media._key(request_id)
    title = media._publication_text(title, 200, required=True)
    brief = media._publication_text(brief, 2000, multiline=True)
    if not isinstance(variants, list) or not 1 <= len(variants) <= 6 or len({v.get("platform") for v in variants}) != len(variants):
        raise HTTPException(422, "请为每个平台仅准备一个版本，最多六个平台")
    prepared = []
    for variant in variants:
        values = media._validate_content_fields({**variant, "title": title})
        prepared.append(values)
    fingerprint = media._hash({"customer_id": customer_id, "title": title, "brief": brief,
        "assignee_id": assignee_id or ctx.identity, "variants": prepared})
    async with media._write(db):
        old = await db.scalar(select(Plan).where(Plan.created_by_id == ctx.identity, Plan.request_id == key))
        if old:
            if old.fingerprint != fingerprint:
                raise HTTPException(409, "相同请求编号对应了不同的计划，请先确认原保存结果")
            return await _plan_data(db, ctx, old)
        customer, permissions = await media._customer(db, ctx, customer_id, write=True)
        identity, name = await media._assignee(db, ctx, customer, assignee_id)
        plan = Plan(customer_id=customer.id, title=title, brief=brief, created_by_id=ctx.identity,
                    request_id=key, fingerprint=fingerprint, created_at=media.now())
        db.add(plan)
        await db.flush()
        for values in prepared:
            platform = values["platform"]
            publication = media.normalize_publication(None, platform, values["timezone"])
            task = Task(customer_id=customer.id, customer_name=customer.business_name,
                assignee_id=identity, assignee_name=name, created_by_id=ctx.identity,
                client_request_id=str(uuid5(NAMESPACE_URL, f"t24-content-plan:{ctx.identity}:{key}:{platform}")),
                creation_fingerprint=media._hash({"plan_id": plan.id, **values}), status="draft", revision=1,
                created_at=media.now(), updated_at=media.now(), **values)
            db.add(task)
            await db.flush()
            db.add(Link(task_id=task.id, plan_id=plan.id, platform=platform))
            await media._save_publication(db, task, publication)
            await media._event(db, ctx, task, "create", None)
        await db.flush()
        return await _plan_data(db, ctx, plan)
