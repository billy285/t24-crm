"""Explicit, bounded pool dispatch with stateless drift-checked previews.

No scheduler, provider request or outbound call runs here. Existing work keeps
capacity before new pool contacts. Caller owns merchant->workflow locks/commit.
"""
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select

from models.customers import Customers
from models.employees import Employees
from models.merchant_pool import MerchantPool
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_daily_quotas import SalesDailyQuotas
from models.sales_leads import SalesLeads
from models.sales_lead_assignment_logs import SalesLeadAssignmentLogs
from services.merchant_identity import has_concrete_name_and_address
from services.phone_numbers import parse_phone_number, phone_match_key
from services.prospect_verification import quality_for_many
from services.sales_contact_protection import blocked_phone_keys
from services.sales_queue_policy import aware, contact_queue_context, queue_context

BLOCKED_QUALITY = {'invalid_phone', 'not_target', 'closed'}
DONE = {'blocked', 'lost', 'won', 'converted'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def snapshot(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def real_fields(merchant):
    name = has_concrete_name_and_address(SimpleNamespace(business_name=merchant.business_name, address='field'))
    address = has_concrete_name_and_address(SimpleNamespace(business_name='field', address=merchant.address))
    concrete = lambda value: has_concrete_name_and_address(SimpleNamespace(business_name=value, address='field'))
    return sum([name, address, concrete(merchant.city), concrete(merchant.contact_name), concrete(merchant.website)])


async def build_dispatch_plan(db, user, merchant_ids, sales_ids, *, now=None):
    from routers.merchant_pool import _ensure_pool_role, _manager_scope, _resolve_sales_assignee, _is_closed
    _ensure_pool_role(user)
    now = aware(now or datetime.now(timezone.utc))
    today = now.astimezone(ZoneInfo('Asia/Shanghai')).date()
    merchant_ids, sales_ids = sorted(set(merchant_ids)), sorted(set(sales_ids))
    query = select(MerchantPool).where(MerchantPool.id.in_(merchant_ids)).order_by(MerchantPool.id)
    scope = await _manager_scope(db, user)
    if scope is not None:
        query = query.where(scope)
    merchants = (await db.scalars(query.execution_options(populate_existing=True))).all()
    if len(merchants) != len(merchant_ids):
        raise HTTPException(404, '所选商家不存在或不在您的权限范围内')
    for employee_id in sales_ids:
        await _resolve_sales_assignee(db, employee_id, user)
    employees = (await db.scalars(select(Employees).where(Employees.id.in_(sales_ids))
        .order_by(Employees.id).execution_options(populate_existing=True))).all()
    quotas = (await db.scalars(select(SalesDailyQuotas).where(SalesDailyQuotas.sales_employee_id.in_(sales_ids),
        SalesDailyQuotas.target_date == today).execution_options(populate_existing=True))).all()
    quota_by = {row.sales_employee_id: max(0, int(row.target_count)) for row in quotas}
    tasks = (await db.scalars(select(SalesDailyDialTasks).where(SalesDailyDialTasks.sales_employee_id.in_(sales_ids),
        SalesDailyDialTasks.task_date == today, SalesDailyDialTasks.status.in_(['pending', 'completed']))
        .order_by(SalesDailyDialTasks.id).execution_options(populate_existing=True))).all()
    leads = (await db.scalars(select(SalesLeads).where(SalesLeads.assigned_sales_id.in_(sales_ids))
        .order_by(SalesLeads.id).execution_options(populate_existing=True))).all()
    quality = await quality_for_many(db, 'pool', merchant_ids)
    lead_quality = await quality_for_many(db, 'lead', [lead.id for lead in leads])
    today_ids = {task.lead_id for task in tasks}
    used = Counter(task.sales_employee_id for task in tasks)
    load, reserved = Counter(), Counter()
    for lead in leads:
        if lead.status in DONE or lead.is_blacklisted or lead.do_not_contact or lead.converted_customer_id or lead_quality[lead.id]['status'] in BLOCKED_QUALITY:
            continue
        load[lead.assigned_sales_id] += 1
        future = any(value and aware(value) > now for value in (lead.next_follow_up_at, lead.cooldown_until))
        if lead.id not in today_ids and not future:
            reserved[lead.assigned_sales_id] += 1
    capacities = {}
    for employee in employees:
        quota = quota_by.get(employee.id, 100)
        capacities[employee.id] = dict(sales_employee_id=employee.id, salesperson=employee.name,
            quota=quota, today_tasks=used[employee.id], existing_pending_load=load[employee.id],
            reserved_existing=reserved[employee.id], remaining=max(0, quota-used[employee.id]-reserved[employee.id]),
            assigned_count=0, timezones={})
    _, start, end = await queue_context(db, [], today)
    keys = {row.id: phone_match_key(row.phone, row.country) for row in merchants}
    existing_keys = {phone_match_key(phone, country) for phone, country in (await db.execute(select(SalesLeads.phone, SalesLeads.country))).all()}
    existing_keys |= {phone_match_key(phone, country) for phone, country in (await db.execute(select(Customers.phone, Customers.country))).all()}
    suppressed = await blocked_phone_keys(db, {key for key in keys.values() if key})
    contexts, candidates, unassigned = {}, [], []
    for merchant in merchants:
        context = contact_queue_context(SimpleNamespace(country=merchant.country, state=merchant.state, city=merchant.city,
            address=merchant.address, next_follow_up_at=None), now=now, start=start, end=end)
        contexts[merchant.id] = {key: value for key, value in context.items() if key != 'local_time'}
        reason = None
        if merchant.pool_status != 'pending' or merchant.converted_lead_id:
            reason = '已离开待分配池'
        elif quality[merchant.id]['status'] in BLOCKED_QUALITY or _is_closed(merchant.business_status):
            reason = '已核验为无效、非目标或停业'
        elif not parse_phone_number(merchant.phone, merchant.country).is_valid:
            reason = '缺少有效公开电话'
        elif keys[merchant.id] in suppressed:
            reason = '联系方式受禁联保护'
        elif keys[merchant.id] in existing_keys:
            reason = '该联系方式已存在于客户或销售线索'
        if reason:
            unassigned.append(dict(merchant_id=merchant.id, business_name=merchant.business_name, reason=reason))
        else:
            candidates.append((merchant, context, real_fields(merchant)))
    candidates.sort(key=lambda item: (0 if item[1]['in_contact_window'] else 1 if item[1]['in_contact_window'] is False else 2, -item[2], item[0].id))
    assignments, selected_keys = [], set()
    for merchant, context, completeness in candidates:
        available = [row for row in capacities.values() if row['assigned_count'] < row['remaining']]
        reason = '同批次重复联系方式' if keys[merchant.id] in selected_keys else '今日剩余配额已用尽，保留在商家池' if not available else None
        if reason:
            unassigned.append(dict(merchant_id=merchant.id, business_name=merchant.business_name, reason=reason))
            continue
        target = min(available, key=lambda row: (Fraction(row['existing_pending_load']+row['assigned_count'], max(1,row['quota'])),
            Fraction(row['today_tasks']+row['reserved_existing']+row['assigned_count'], max(1,row['quota'])), row['sales_employee_id']))
        target['assigned_count'] += 1
        zone = context['timezone_group']
        target['timezones'][zone] = target['timezones'].get(zone, 0) + 1
        selected_keys.add(keys[merchant.id])
        assignments.append(dict(merchant_id=merchant.id, business_name=merchant.business_name,
            sales_employee_id=target['sales_employee_id'], salesperson=target['salesperson'],
            timezone=context['timezone'], timezone_group=zone, in_contact_window=context['in_contact_window'],
            queue_reason=context['queue_reason'], completeness= completeness, quality_status=quality[merchant.id]['status']))
    plan = dict(target_date=today.isoformat(), selected_count=len(merchants), assigned_count=len(assignments),
        unassigned_count=len(unassigned), assignments=assignments, unassigned=unassigned,
        employees=list(capacities.values()), policy='现有任务与到期待处理线索先占配额；所选商家按当地联系时段、非占位资料完整度排序，再按负载/配额均衡。分配不等于允许立即拨打。')
    fingerprint = dict(version=1, actor=(str(user.id),user.role,user.name), merchants=[snapshot(row) for row in merchants],
        employee_rows=[snapshot(row) for row in employees], quotas=[snapshot(row) for row in sorted(quotas,key=lambda row:row.id)],
        tasks=[snapshot(row) for row in tasks], existing_leads=[snapshot(row) for row in leads], quality=quality,
        lead_quality=lead_quality, contexts=contexts, plan=plan)
    plan['plan_sha256'] = digest(fingerprint)
    return plan


async def apply_dispatch_plan(db, user, merchant_ids, sales_ids, plan_sha256, *, now=None):
    from routers.merchant_pool import _ensure_pool_role, _create_sales_lead_from_merchant
    from services.merchant_row_locks import lock_merchant_rows
    from services.sales_workflow_locks import lock_sales_workflow
    _ensure_pool_role(user)
    try:
        await lock_merchant_rows(db, merchant_ids)
        await lock_sales_workflow(db, employee_ids=sales_ids)
        try:
            plan = await build_dispatch_plan(db, user, merchant_ids, sales_ids, now=now)
        except HTTPException as exc:
            raise HTTPException(409, '权限、商家或销售状态已变化，请重新生成派单预览') from exc
        if plan['plan_sha256'] != plan_sha256:
            raise HTTPException(409, '商家、核验状态、联系时段或销售剩余容量已变化；本次未分配，请重新预览')
        if not plan['assignments']:
            raise HTTPException(409, '没有可安排的商家，请调整销售或剩余配额后重新预览')
        receipts = []
        target_date = datetime.fromisoformat(plan['target_date']).date()
        for item in plan['assignments']:
            merchant = await db.get(MerchantPool, item['merchant_id'])
            lead = await _create_sales_lead_from_merchant(db, merchant, user, item['sales_employee_id'],
                item['salesperson'], int(user.id) if user.role == 'sales_manager' else None)
            lead.assigned_at = aware(now or datetime.now(timezone.utc))
            lead.automation_state = 'assigned'
            db.add(SalesDailyDialTasks(sales_employee_id=item['sales_employee_id'], task_date=target_date,
                lead_id=lead.id, status='pending', queue_category='new'))
            db.add(SalesLeadAssignmentLogs(lead_id=lead.id, action='pool_dispatch', to_sales_employee_id=item['sales_employee_id'],
                to_sales_employee_name=item['salesperson'], reason='主管确认商家池均衡派单；预览 '+plan_sha256,
                operated_by_id=int(user.id), operated_by_name=user.name))
            await db.flush()
            receipts.append(dict(merchant_id=merchant.id, lead_id=lead.id, sales_employee_id=item['sales_employee_id']))
        await db.commit()
        return dict(assigned_count=len(receipts), unassigned_count=plan['unassigned_count'], plan_sha256=plan_sha256, items=receipts)
    except BaseException:
        await db.rollback()
        raise
