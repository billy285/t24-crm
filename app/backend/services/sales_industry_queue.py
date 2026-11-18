"""Let a salesperson prepare today's first calls from one industry."""
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
        SalesDailyDialTasks.status.in_(("completed", "pending")),
        or_(SalesDailyDialTasks.status == "completed", SalesLeads.assigned_sales_id == actor.id))
        .execution_options(populate_existing=True))).all()
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
    first_call_ids = [task.lead_id for task in reversed(replaceable) if task.id in matching_ids]
    return len(rows), completed, pending, first_call_ids, [
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


async def _available_pool_pages(db, label, owners, zones, customers, leads, selected_keys):
    conditions = list(_eligible_pool(db, label, owners))
    if zones is not None:
        conditions.append(sql_matches_contact_zones(_pool_fields(), zones, source_payload=MerchantPool.raw_payload))
    after_id = 0
    while True:
        rows = (await db.execute(select(MerchantPool.id, MerchantPool.phone, MerchantPool.country)
            .where(*conditions, MerchantPool.id > after_id).order_by(MerchantPool.id).limit(128))).all()
        eligible = {}
        for row in rows:
            key = _queue_phone_key(row.phone, row.country)
            if key and key not in customers and key not in leads and key not in selected_keys:
                eligible.setdefault(key, row.id)
        for key in await blocked_phone_keys(db, eligible):
            eligible.pop(key, None)
        if eligible:
            yield eligible
        if len(rows) < 128:
            break
        after_id = rows[-1].id


async def _pool_shortlist(db, label, owners, selected_zones, preferred_zones, count):
    """Page by merchant id until enough guarded row locks are acquired."""
    if count <= 0 or not owners or selected_zones == set():
        return []
    customers, leads = await _number_index(db)
    selected = []
    selected_keys = set()
    # The unrestricted legacy choice prefers the contact window, then can fill
    # remaining slots from other times. Strict choices never cross their window.
    passes = [selected_zones] if selected_zones is not None else [preferred_zones, None]
    for zones in passes:
        if zones == set():
            continue
        async for eligible in _available_pool_pages(db, label, owners, zones, customers, leads, selected_keys):
            reserved = set(await db.scalars(select(MerchantPool.id).where(
                MerchantPool.id.in_(eligible.values()), *_pool_conditions(label, owners))
                .order_by(MerchantPool.id).limit(count - len(selected)).with_for_update(skip_locked=True)))
            for key, ident in eligible.items():
                if ident in reserved:
                    selected.append(ident)
                    selected_keys.add(key)
            if len(selected) >= count:
                return selected
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
    from routers.merchant_pool import _create_sales_leads_from_merchants, _is_closed
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
    pre_total, pre_done, _, pre_first_call_ids, pre_slots = await _batch_state(db, actor, day, industry, now, preserve_task_ids, zones)
    pre_quota = await quota_reader(db, actor.id, day)
    pre_limit = min(batch_size - len(pre_first_call_ids), pre_quota - pre_done,
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
    total, completed, pending, first_call_ids, slots = await _batch_state(db, actor, day, industry, now, preserve_task_ids, zones)
    free = max(0, quota - total)
    needed = max(0, batch_size - len(first_call_ids))
    limit = max(0, min(needed, quota - completed, free + len(slots)))
    chosen = []
    outside_window = False
    if limit:
        customers, leads = await _number_index(db)
        candidates = await _lead_candidates(db, actor, manager, label, day, now, customers, leads)
        chosen = [lead for lead, _, zone in candidates if zones is None or zone in zones][:limit]
        if len(chosen) < limit and shortlist:
            criteria = list(_pool_conditions(label, owners))
            if zones is not None:
                criteria.append(sql_matches_contact_zones(_pool_fields(), zones, source_payload=MerchantPool.raw_payload))
            pool = {row.id: row for row in await db.scalars(select(MerchantPool).where(
                MerchantPool.id.in_(shortlist), *criteria).execution_options(populate_existing=True))}
            qualities = await quality_for_many(db, "pool", pool)
            keys = {ident: phone_match_key(row.phone, row.country) for ident, row in pool.items()}
            unavailable = set(leads) | customers | await blocked_phone_keys(db, {key for key in keys.values() if key})
            assignments = []
            for ident in shortlist:
                row = pool.get(ident)
                key = keys.get(ident)
                if not row or not key or key in unavailable or _is_closed(row.business_status) or qualities[ident]["status"] not in VALID_QUALITY:
                    continue
                assignments.append((row, manager if row.created_by_id == manager else None))
                unavailable.add(key)
                if len(chosen) + len(assignments) == limit:
                    break
            new_leads = await _create_sales_leads_from_merchants(db, assignments, user, actor.id, actor.name)
            for (row, _), lead in zip(assignments, new_leads):
                lead.assigned_at = now
                lead.automation_state = "assigned"
                row.isolation_reason = "销售自主领取行业首拨名单"
                chosen.append(lead)
                leads[keys[row.id]] = {lead.id}
        if window_only and len(chosen) < limit:
            region_zones = GROUP_ZONES[group] if group else set().union(*(GROUP_ZONES[g] for g in REGIONS))
            closed_zones = region_zones - zones
            outside_window = any(zone in closed_zones for _, _, zone in candidates)
            if owners and closed_zones and not outside_window:
                pages = _available_pool_pages(db, label, owners, closed_zones, customers, leads, set())
                outside_window = bool(await anext(pages, None))
    replaced = max(0, len(chosen) - free)
    for task in slots[:replaced]:
        task.status = DEFERRED
    queued_ids = [lead.id for lead in chosen]
    tasks = {task.lead_id: task for task in (await db.scalars(select(SalesDailyDialTasks).where(
        SalesDailyDialTasks.lead_id.in_(queued_ids), SalesDailyDialTasks.sales_employee_id == actor.id,
        SalesDailyDialTasks.task_date == day))).all()} if queued_ids else {}
    for lead in chosen:
        if lead.assigned_sales_id is None:
            lead.assigned_sales_id, lead.assigned_sales_name = actor.id, actor.name
            lead.assigned_at, lead.automation_state = now, "assigned"
        task = tasks.get(lead.id)
        if task is None:
            db.add(SalesDailyDialTasks(sales_employee_id=actor.id, task_date=day, lead_id=lead.id,
                                       queue_category="new", status="pending"))
        else:
            task.status = "pending"
        db.add(SalesLeadAssignmentLogs(lead_id=lead.id, action="industry_pick", to_sales_employee_id=actor.id,
            to_sales_employee_name=actor.name, operated_by_id=actor.id, operated_by_name=actor.name,
            reason=f"本人领取{label}首拨任务", created_at=now))
    await db.commit()
    created = len(queued_ids)
    shortfall = None
    explanation = ""
    if created < limit:
        if outside_window:
            shortfall = "outside_window"
            explanation = f"其余可领取的{label}当前不在当地 {start:02d}:00–{end:02d}:00 的拨打时段"
        else:
            shortfall = "no_stock"
            explanation = f"当前条件下暂无更多可领取的{label}首拨名单"
    elif created < needed:
        shortfall = "quota_full"
        explanation = (f"今日已完成目标 {quota} 家" if completed >= quota and quota > 0 else
                       f"今日目标 {quota} 家，可用首拨名额已用完")
    if created:
        reason = "queued"
        message = f"已加入今日待拨 {created} 家{label}"
        if replaced:
            message += f"，原队列有 {replaced} 家首拨暂缓，仍归你负责"
        if shortfall:
            message += f"。{explanation}"
    elif not needed:
        reason = "already_ready"
        message = f"当前条件下已有 {len(first_call_ids)} 家{label}首拨待处理，本次新增 0 家"
    else:
        reason = shortfall
        message = f"本次新增 0 家。{explanation}"
    return dict(industry=industry, created=created, replaced=replaced, queued_lead_ids=queued_ids,
                ready_lead_ids=first_call_ids[:batch_size] if reason == "already_ready" else [],
                reason=reason, shortfall_reason=shortfall, total=total + created - replaced,
                pending_in_industry=pending + created, message=message)
