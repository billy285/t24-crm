"""Let a salesperson prepare a small batch of first calls from one industry."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_, select

from dependencies.auth import LEGACY_ROLE_ALIASES
from models.customer_contacts import Customer_contacts
from models.customers import Customers
from models.employees import Employees
from models.merchant_pool import MerchantPool
from models.ringcentral_call_records import RingCentralCallRecords
from models.sales_call_activities import SalesCallActivities
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_lead_assignment_logs import SalesLeadAssignmentLogs
from models.sales_lead_enrichments import SalesDialAttempt, SalesLeadEnrichment
from models.sales_leads import SalesLeads
from services.merchant_industries import merchant_industry_filter, workbench_industry_group
from services.merchant_row_locks import lock_merchant_rows
from services.phone_numbers import phone_match_key
from services.prospect_verification import quality_for_many, quality_status_expression
from services.sales_contact_protection import blocked_phone_keys, snapshot_phone_keys
from services.sales_dossiers import active_actor
from services.sales_queue_policy import contact_queue_context, queue_context, queue_sort_key
from services.sales_task_assignment import active_closing_leads
from services.sales_timezones import resolve_contact_timezone
from services.sales_workflow_locks import lock_sales_workflow

BATCH_SIZE = 10
DEFERRED = "industry_deferred"
LABELS = {"restaurant": "餐厅", "beauty": "美业"}
VALID_QUALITY = {"pending", "valid"}


def _untouched_lead(now):
    return (
        SalesLeads.status == "new", SalesLeads.next_follow_up_at.is_(None),
        SalesLeads.last_contact_at.is_(None), SalesLeads.contact_attempt_count == 0,
        SalesLeads.converted_customer_id.is_(None), SalesLeads.is_blacklisted.is_(False),
        SalesLeads.do_not_contact.is_(False),
        SalesLeads.automation_state.notin_(("blocked", "closed", "closing_active", "protected")),
        or_(SalesLeads.cooldown_until.is_(None), SalesLeads.cooldown_until <= now),
        ~SalesLeads.id.in_(active_closing_leads()),
        ~select(SalesCallActivities.id).where(SalesCallActivities.lead_id == SalesLeads.id).exists(),
        ~select(SalesDialAttempt.id).where(SalesDialAttempt.lead_id == SalesLeads.id).exists(),
        ~select(RingCentralCallRecords.id).where(RingCentralCallRecords.lead_id == SalesLeads.id).exists(),
    )


async def _batch_state(db, actor, day, industry, now, preserve_task_ids):
    rows = (await db.execute(select(SalesDailyDialTasks, SalesLeads.industry, SalesLeads.assigned_sales_id).join(
        SalesLeads, SalesLeads.id == SalesDailyDialTasks.lead_id).where(
        SalesDailyDialTasks.sales_employee_id == actor.id, SalesDailyDialTasks.task_date == day,
        SalesDailyDialTasks.status.in_(("completed", "pending"))))).all()
    pending = sum(owner == actor.id and task.status == "pending" and workbench_industry_group(label) == industry
                  for task, label, owner in rows)
    completed = sum(task.status == "completed" for task, _, _ in rows)
    # Only postpone an untouched first call; the task row and its owner are retained.
    replaceable = (await db.scalars(select(SalesDailyDialTasks).join(
        SalesLeads, SalesLeads.id == SalesDailyDialTasks.lead_id).where(
        SalesDailyDialTasks.sales_employee_id == actor.id, SalesDailyDialTasks.task_date == day,
        SalesLeads.assigned_sales_id == actor.id, SalesDailyDialTasks.status == "pending",
        SalesDailyDialTasks.queue_category == "new", SalesDailyDialTasks.dial_started_at.is_(None),
        SalesDailyDialTasks.completed_activity_id.is_(None), *_untouched_lead(now),
    ).order_by(SalesDailyDialTasks.id.desc()))).all()
    other_ids = {task.id for task, label, _ in rows if workbench_industry_group(label) != industry}
    first_calls = sum(task.id not in other_ids for task in replaceable)
    return len(rows), completed, pending, first_calls, [
        task for task in replaceable if task.id in other_ids and task.id not in preserve_task_ids
    ]


async def _source_owners(db, actor):
    managers = (await db.scalars(select(Employees.id).where(
        Employees.role == "sales_manager", Employees.name == actor.supervisor,
        Employees.status.in_(("active", "probation"))))).all() if actor.supervisor else []
    # The current employee schema links supervisors by name; ambiguous matches grant no private pool access.
    manager = managers[0] if len(managers) == 1 else None
    admin_roles = {"admin", "super_admin"} | {alias for alias, role in LEGACY_ROLE_ALIASES.items() if role in {"admin", "super_admin"}}
    admins = set(await db.scalars(select(Employees.id).where(func.lower(func.trim(Employees.role)).in_(admin_roles))))
    return manager, admins | ({manager} if manager is not None else set())


async def _number_index(db):
    """Cover alternate sales contacts too, so a shared number cannot bypass an existing owner."""
    customer_keys = set()
    for query in (select(Customers.phone, Customers.country),
                  select(Customer_contacts.contact_phone, Customers.country).join(Customers, Customers.id == Customer_contacts.customer_id)):
        customer_keys.update(key for phone, country in await db.execute(query) if (key := phone_match_key(phone, country)))
    owners = {}
    query = select(SalesLeads.id, SalesLeads.phone, SalesLeads.country, SalesLeadEnrichment.contacts).outerjoin(
        SalesLeadEnrichment, SalesLeadEnrichment.lead_id == SalesLeads.id)
    for ident, phone, country, contacts in await db.execute(query):
        for key in snapshot_phone_keys({"phone": phone, "contacts": contacts or []}, country):
            owners.setdefault(key, set()).add(ident)
    return customer_keys, owners


def _pool_conditions(label, importer_ids):
    return (MerchantPool.pool_status == "pending", MerchantPool.converted_lead_id.is_(None),
            MerchantPool.existing_customer_id.is_(None), MerchantPool.duplicate_of_id.is_(None),
            MerchantPool.created_by_id.in_(importer_ids), merchant_industry_filter(MerchantPool.industry, label))


async def _pool_shortlist(db, label, owners, day, now, count):
    """Pick locks in merchant -> workflow order, shared with imports and manager dispatch."""
    from routers.merchant_pool import _is_closed
    if count <= 0 or not owners:
        return []
    customers, leads = await _number_index(db)
    quality = quality_status_expression("pool", MerchantPool.id, db.get_bind().dialect.name)
    rows = (await db.execute(select(MerchantPool.id, MerchantPool.phone, MerchantPool.country, MerchantPool.state,
        MerchantPool.city, MerchantPool.address, MerchantPool.business_status).where(
        *_pool_conditions(label, owners), quality.in_(VALID_QUALITY)).order_by(MerchantPool.id))).all()
    _, start, end = await queue_context(db, [], day)
    def time_priority(row):
        zone = resolve_contact_timezone(country=row.country, state=row.state, city=row.city, address=row.address)["timezone"]
        if zone is None:
            return 2
        return 0 if start <= now.astimezone(ZoneInfo(zone)).hour < end else 1
    rows.sort(key=time_priority)
    selected = []
    selected_keys = set()
    for offset in range(0, len(rows), 64):
        batch = [(row.id, phone_match_key(row.phone, row.country)) for row in rows[offset:offset + 64]
                 if not _is_closed(row.business_status)]
        keys = {key for _, key in batch if key and key not in customers and key not in leads}
        allowed = keys - await blocked_phone_keys(db, keys)
        eligible = {}
        for ident, key in batch:
            if key in allowed and key not in selected_keys:
                eligible.setdefault(key, ident)
        if not eligible:
            continue
        # Skip rows being used by another import or seller rather than waiting
        # on their first ten records and overlooking the rest of the inventory.
        priority = case({ident: rank for rank, ident in enumerate(eligible.values())}, value=MerchantPool.id)
        reserved = set(await db.scalars(select(MerchantPool.id).where(
            MerchantPool.id.in_(eligible.values()), *_pool_conditions(label, owners),
        ).order_by(priority).limit(count - len(selected)).with_for_update(skip_locked=True)))
        for key, ident in eligible.items():
            if ident in reserved:
                selected.append(ident)
                selected_keys.add(key)
        if len(selected) == count:
            break
    return selected


async def _lead_candidates(db, actor, manager, label, day, now, customer_keys, phone_owners):
    # A deferred row owned by this salesperson may be restored. Other task rows,
    # including cancellations or another salesperson's work, keep their original meaning.
    reservations = select(SalesDailyDialTasks.lead_id).where(SalesDailyDialTasks.task_date == day,
        or_(SalesDailyDialTasks.sales_employee_id != actor.id, SalesDailyDialTasks.status != DEFERRED))
    team = SalesLeads.team_manager_id.is_(None)
    if manager is not None:
        team = or_(team, SalesLeads.team_manager_id == manager)
    scope = or_(SalesLeads.assigned_sales_id == actor.id, and_(SalesLeads.assigned_sales_id.is_(None), team))
    candidates = (await db.scalars(select(SalesLeads).where(
        *_untouched_lead(now), scope, merchant_industry_filter(SalesLeads.industry, label),
        ~SalesLeads.id.in_(reservations)).execution_options(populate_existing=True))).all()
    quality = await quality_for_many(db, "lead", [lead.id for lead in candidates])
    profiles, start, end = await queue_context(db, candidates, day)
    keys_by_id = {lead.id: set() for lead in candidates}
    for key, ids in phone_owners.items():
        for ident in ids:
            if ident in keys_by_id:
                keys_by_id[ident].add(key)
    suppressed = await blocked_phone_keys(db, {key for keys in keys_by_id.values() for key in keys})
    active_sales = await db.scalar(select(func.count(Employees.id)).where(
        Employees.role == "sales", Employees.status.in_(("active", "probation"))))
    result = []
    for lead in candidates:
        keys = keys_by_id[lead.id]
        if not keys or not phone_match_key(lead.phone, lead.country) or quality[lead.id]["status"] not in VALID_QUALITY:
            continue
        if keys & customer_keys or keys & suppressed or any(phone_owners[key] != {lead.id} for key in keys):
            continue
        if not lead.assigned_sales_id and lead.last_assigned_sales_id == actor.id and lead.rotation_count and active_sales > 1:
            continue
        context = contact_queue_context(lead, now=now, profile=profiles.get(lead.id), start=start, end=end)
        result.append((lead, (lead.assigned_sales_id != actor.id, queue_sort_key(lead, context))))
    return [lead for lead, _ in sorted(result, key=lambda entry: entry[1])]


async def prepare_industry_batch(db, user, industry, day, quota_reader, preserve_task_ids):
    from routers.merchant_pool import _create_sales_lead_from_merchant, _is_closed
    now = datetime.now(timezone.utc)
    if day != now.astimezone(ZoneInfo("Asia/Shanghai")).date():
        raise HTTPException(400, "只能领取今天的任务")
    # SQLite needs a writer reservation before reading. On PostgreSQL lock the
    # short-listed merchant rows first, then the shared workflow and the employee.
    await lock_merchant_rows(db, [])
    actor = await active_actor(db, user)
    if actor.role != "sales":
        raise HTTPException(403, "仅销售本人可以领取行业名单")
    label = LABELS[industry]
    manager, owners = await _source_owners(db, actor)
    pre_total, pre_done, _, pre_first, pre_slots = await _batch_state(db, actor, day, industry, now, preserve_task_ids)
    pre_quota = await quota_reader(db, actor.id, day)
    pre_limit = min(BATCH_SIZE - pre_first, pre_quota - pre_done,
                    max(0, pre_quota - pre_total) + len(pre_slots))
    shortlist = await _pool_shortlist(db, label, owners, day, now, max(0, pre_limit))
    await lock_sales_workflow(db, employee_ids=[actor.id])
    actor = await active_actor(db, user)
    manager, owners = await _source_owners(db, actor)
    quota = await quota_reader(db, actor.id, day)
    total, completed, pending, first_calls, slots = await _batch_state(db, actor, day, industry, now, preserve_task_ids)
    free = max(0, quota - total)
    limit = max(0, min(BATCH_SIZE - first_calls, quota - completed, free + len(slots)))
    chosen = []
    if limit:
        customers, leads = await _number_index(db)
        chosen = (await _lead_candidates(db, actor, manager, label, day, now, customers, leads))[:limit]
        if len(chosen) < limit and shortlist:
            pool = {row.id: row for row in await db.scalars(select(MerchantPool).where(
                MerchantPool.id.in_(shortlist), *_pool_conditions(label, owners)).execution_options(populate_existing=True))}
            qualities = await quality_for_many(db, "pool", pool)
            keys = {ident: phone_match_key(row.phone, row.country) for ident, row in pool.items()}
            unavailable = set(leads) | customers | await blocked_phone_keys(db, {key for key in keys.values() if key})
            for ident in shortlist:
                row = pool.get(ident)
                key = keys.get(ident)
                if not row or not key or key in unavailable or _is_closed(row.business_status) or qualities[ident]["status"] not in VALID_QUALITY:
                    continue
                lead = await _create_sales_lead_from_merchant(db, row, user, actor.id, actor.name,
                    manager if row.created_by_id == manager else None)
                lead.assigned_at = now
                lead.automation_state = "assigned"
                row.isolation_reason = "销售自主领取行业首拨名单"
                chosen.append(lead)
                unavailable.add(key)
                if len(chosen) == limit:
                    break
    replaced = max(0, len(chosen) - free)
    for task in slots[:replaced]:
        task.status = DEFERRED
    for lead in chosen:
        if lead.assigned_sales_id is None:
            lead.assigned_sales_id, lead.assigned_sales_name = actor.id, actor.name
            lead.assigned_at, lead.automation_state = now, "assigned"
        task = await db.scalar(select(SalesDailyDialTasks).where(
            SalesDailyDialTasks.lead_id == lead.id, SalesDailyDialTasks.sales_employee_id == actor.id,
            SalesDailyDialTasks.task_date == day))
        if task is None:
            db.add(SalesDailyDialTasks(sales_employee_id=actor.id, task_date=day, lead_id=lead.id,
                                       queue_category="new", status="pending"))
        else:
            task.status = "pending"
        db.add(SalesLeadAssignmentLogs(lead_id=lead.id, action="industry_pick", to_sales_employee_id=actor.id,
            to_sales_employee_name=actor.name, operated_by_id=actor.id, operated_by_name=actor.name,
            reason=f"本人领取{label}首拨任务"))
    await db.commit()
    if chosen:
        message = f"已安排 {len(chosen)} 家{label}，今日待处理 {pending + len(chosen)} 家{label}"
    elif first_calls >= BATCH_SIZE:
        message = f"今日已有 {pending} 家{label}待处理"
    elif not limit:
        message = "今日目标已完成或剩余名额已由回访、已开始的任务占用"
    else:
        message = f"当前没有更多可领取的{label}首拨名单"
    return dict(industry=industry, created=len(chosen), replaced=replaced,
                total=total + len(chosen) - replaced, pending_in_industry=pending + len(chosen), message=message)
