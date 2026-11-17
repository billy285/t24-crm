"""Let a salesperson prepare a small batch of first calls from one industry."""
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
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
from models.sales_dossiers import SalesDossierHandoff
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
from services.sales_timezones import GROUP_ZONES, VALID_TIMEZONES, sql_contact_timezone, sql_matches_contact_zones, timezone_group
from services.sales_workflow_locks import lock_sales_workflow

BATCH_SIZE = 10
DEFERRED = "industry_deferred"
LABELS = {"restaurant": "餐厅", "beauty": "美业"}
VALID_QUALITY = {"pending", "valid"}
REGIONS = ("eastern", "central", "mountain", "pacific")
REPRESENTATIVE_ZONES = {key: zone for key, zone in zip(REGIONS, (
    "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"))}
# Phone parsing is independent of ownership and protection. Reuse only that pure
# result across inventory reads; contactability and reservations are always live.
_queue_phone_key = lru_cache(maxsize=65536)(phone_match_key)


def _selected_zones(group, window_only, now, start, end):
    if not group and not window_only:
        return None
    zones = GROUP_ZONES[group] if group else set().union(*(GROUP_ZONES[g] for g in REGIONS))
    return {z for z in zones if z in VALID_TIMEZONES and
            (not window_only or start <= now.astimezone(ZoneInfo(z)).hour < end)}


def _pool_fields():
    return {field: getattr(MerchantPool, field) for field in ("country", "state", "city", "address")}



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


async def _batch_state(db, actor, day, industry, now, preserve_task_ids, selected_zones=None):
    rows = (await db.execute(select(SalesDailyDialTasks, SalesLeads).join(
        SalesLeads, SalesLeads.id == SalesDailyDialTasks.lead_id).where(
        SalesDailyDialTasks.sales_employee_id == actor.id, SalesDailyDialTasks.task_date == day,
        SalesDailyDialTasks.status.in_(("completed", "pending"))))).all()
    profiles = (await queue_context(db, [lead for _, lead in rows], day))[0] if selected_zones is not None else {}
    matching_ids = {task.id for task, lead in rows if workbench_industry_group(lead.industry) == industry and
                    (selected_zones is None or contact_queue_context(lead, now=now, profile=profiles.get(lead.id))["timezone"] in selected_zones)}
    pending = sum(lead.assigned_sales_id == actor.id and task.status == "pending" and task.id in matching_ids
                  for task, lead in rows)
    completed = sum(task.status == "completed" for task, _ in rows)
    # Only postpone an untouched first call; the task row and its owner are retained.
    replaceable = (await db.scalars(select(SalesDailyDialTasks).join(
        SalesLeads, SalesLeads.id == SalesDailyDialTasks.lead_id).where(
        SalesDailyDialTasks.sales_employee_id == actor.id, SalesDailyDialTasks.task_date == day,
        SalesLeads.assigned_sales_id == actor.id, SalesDailyDialTasks.status == "pending",
        SalesDailyDialTasks.queue_category == "new", SalesDailyDialTasks.dial_started_at.is_(None),
        SalesDailyDialTasks.completed_activity_id.is_(None), *_untouched_lead(now),
    ).order_by(SalesDailyDialTasks.id.desc()))).all()
    first_calls = sum(task.id in matching_ids for task in replaceable)
    return len(rows), completed, pending, first_calls, [
        task for task in replaceable if task.id not in matching_ids and task.id not in preserve_task_ids
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


def _eligible_pool(db, label, owners):
    from routers.merchant_pool import CLOSED_MARKERS
    return (*_pool_conditions(label, owners), MerchantPool.phone.is_not(None),
            func.lower(func.trim(func.coalesce(MerchantPool.business_status, ""))).notin_(CLOSED_MARKERS),
            quality_status_expression("pool", MerchantPool.id, db.get_bind().dialect.name).in_(VALID_QUALITY))


async def _pool_shortlist(db, label, owners, selected_zones, preferred_zones, count):
    """Page by merchant id until enough guarded row locks are acquired."""
    if count <= 0 or not owners or selected_zones == set():
        return []
    customers, leads = await _number_index(db)
    conditions = _eligible_pool(db, label, owners)
    selected = []
    selected_keys = set()
    # The unrestricted legacy choice prefers the contact window, then can fill
    # remaining slots from other times. Strict choices never cross their window.
    passes = [selected_zones] if selected_zones is not None else [preferred_zones, None]
    for zones in passes:
        if zones == set():
            continue
        conditions_now = list(conditions)
        if zones is not None:
            conditions_now.append(sql_matches_contact_zones(_pool_fields(), zones, source_payload=MerchantPool.raw_payload))
        after_id = 0
        while len(selected) < count:
            rows = (await db.execute(select(MerchantPool.id, MerchantPool.phone, MerchantPool.country)
                .where(*conditions_now, MerchantPool.id > after_id).order_by(MerchantPool.id).limit(128))).all()
            if not rows:
                break
            after_id = rows[-1].id
            eligible = {}
            for row in rows:
                key = _queue_phone_key(row.phone, row.country)
                if key and key not in customers and key not in leads and key not in selected_keys:
                    eligible.setdefault(key, row.id)
            for key in await blocked_phone_keys(db, eligible):
                eligible.pop(key, None)
            if eligible:
                reserved = set(await db.scalars(select(MerchantPool.id).where(
                    MerchantPool.id.in_(eligible.values()), *_pool_conditions(label, owners))
                    .order_by(MerchantPool.id).limit(count - len(selected)).with_for_update(skip_locked=True)))
                for key, ident in eligible.items():
                    if ident in reserved:
                        selected.append(ident)
                        selected_keys.add(key)
            if len(rows) < 128:
                break
        if len(selected) >= count:
            break
    return selected


async def _lead_candidates(db, actor, manager, label, day, now, customer_keys, phone_owners, selected_zones=None):
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
        ~SalesLeads.id.in_(reservations), ~select(SalesDossierHandoff.id).where(
            SalesDossierHandoff.lead_id == SalesLeads.id, SalesDossierHandoff.to_sales_id == actor.id,
            SalesDossierHandoff.status == "pending").exists()).execution_options(populate_existing=True))).all()
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
        if selected_zones is None or context["timezone"] in selected_zones:
            result.append((lead, (lead.assigned_sales_id != actor.id, queue_sort_key(lead, context)), context["timezone"]))
    return sorted(result, key=lambda entry: entry[1])


async def industry_stock(db, user, industry):
    """Read eligible first calls by actual IANA zone; expose aggregate counts only."""
    actor = await active_actor(db, user)
    if actor.role != "sales":
        raise HTTPException(403, "仅销售本人可以查看可领取名单")
    now = datetime.now(timezone.utc)
    day = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
    manager, owners = await _source_owners(db, actor)
    _, start, end = await queue_context(db, [], day)
    customers, leads = await _number_index(db)
    label = LABELS[industry]
    candidates = await _lead_candidates(db, actor, manager, label, day, now, customers, leads)
    counts = Counter(zone for _, _, zone in candidates)
    seen = set()
    if owners:
        zone = sql_contact_timezone(_pool_fields(), source_payload=MerchantPool.raw_payload)["timezone"]
        # Stream only phone, country and IANA. Deduplicate the same phone across
        # sources in the same merchant-id order used by the claim transaction.
        result = await db.stream(select(MerchantPool.phone, MerchantPool.country, zone)
            .where(*_eligible_pool(db, label, owners)).order_by(MerchantPool.id))
        async for part in result.partitions(800):
            offered = []
            for phone, country, zone_name in part:
                key = _queue_phone_key(phone, country)
                if key and key not in seen and key not in customers and key not in leads:
                    seen.add(key)
                    offered.append((key, zone_name))
            blocked = await blocked_phone_keys(db, [key for key, _ in offered])
            counts.update(zone_name for key, zone_name in offered if key not in blocked)
    slots = []
    for group in REGIONS:
        zone_counts = {zone: count for zone, count in counts.items() if timezone_group(zone) == group}
        clocks = sorted({now.astimezone(ZoneInfo(zone)).strftime("%H:%M") for zone in zone_counts}
                        or {now.astimezone(ZoneInfo(REPRESENTATIVE_ZONES[group])).strftime("%H:%M")})
        slots.append({"group": group, "total": sum(zone_counts.values()), "local_times": clocks,
                      "in_window": sum(count for zone, count in zone_counts.items()
                                       if start <= now.astimezone(ZoneInfo(zone)).hour < end)})
    return {"industry": industry, "as_of": now.isoformat(), "contact_start": start,
            "contact_end": end, "zones": slots, "total": sum(counts.values()),
            "in_window": sum(slot["in_window"] for slot in slots)}


async def prepare_industry_batch(db, user, industry, day, quota_reader, preserve_task_ids, *, group=None, window_only=False, batch_size=BATCH_SIZE):
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
    _, start, end = await queue_context(db, [], day)
    zones = _selected_zones(group, window_only, now, start, end)
    pre_total, pre_done, _, pre_first, pre_slots = await _batch_state(db, actor, day, industry, now, preserve_task_ids, zones)
    pre_quota = await quota_reader(db, actor.id, day)
    pre_limit = min(batch_size - pre_first, pre_quota - pre_done,
                    max(0, pre_quota - pre_total) + len(pre_slots))
    shortlist = await _pool_shortlist(db, label, owners, zones, _selected_zones(None, True, now, start, end), max(0, pre_limit))
    await lock_sales_workflow(db, employee_ids=[actor.id])
    actor = await active_actor(db, user)
    manager, owners = await _source_owners(db, actor)
    now = datetime.now(timezone.utc)
    if day != now.astimezone(ZoneInfo("Asia/Shanghai")).date():
        raise HTTPException(409, "日期已切换，请刷新今日拨打")
    _, start, end = await queue_context(db, [], day)
    zones = _selected_zones(group, window_only, now, start, end)
    quota = await quota_reader(db, actor.id, day)
    total, completed, pending, first_calls, slots = await _batch_state(db, actor, day, industry, now, preserve_task_ids, zones)
    free = max(0, quota - total)
    limit = max(0, min(batch_size - first_calls, quota - completed, free + len(slots)))
    chosen = []
    if limit:
        customers, leads = await _number_index(db)
        candidates = await _lead_candidates(db, actor, manager, label, day, now, customers, leads, zones)
        chosen = [lead for lead, _, _ in candidates[:limit]]
        if len(chosen) < limit and shortlist:
            criteria = list(_pool_conditions(label, owners))
            if zones is not None:
                criteria.append(sql_matches_contact_zones(_pool_fields(), zones, source_payload=MerchantPool.raw_payload))
            pool = {row.id: row for row in await db.scalars(select(MerchantPool).where(
                MerchantPool.id.in_(shortlist), *criteria).execution_options(populate_existing=True))}
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
            reason=f"本人领取{label}首拨任务", created_at=now))
    await db.commit()
    if chosen:
        message = f"已安排 {len(chosen)} 家{label}，当前选择下待拨 {pending + len(chosen)} 家"
    elif first_calls >= batch_size:
        message = f"当前选择下已有 {pending} 家{label}待拨"
    elif not limit:
        message = "今日目标已完成或剩余名额已由回访、已开始的任务占用"
    else:
        message = f"当前没有更多可领取的{label}首拨名单"
    return dict(industry=industry, created=len(chosen), replaced=replaced,
                total=total + len(chosen) - replaced, pending_in_industry=pending + len(chosen), message=message)
