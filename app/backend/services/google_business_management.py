"""Owner portfolio, isolated delegation and approved CRM schedules. No ACL writes."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import HTTPException
from sqlalchemy import select, update, func, or_
from models.customers import Customers
from models.employees import Employees
from models.google_business import (GoogleBusinessBinding as Binding, GoogleBusinessConnection as Connection,
    GoogleBusinessGrant as Grant, GoogleBusinessAction as Action, GoogleBusinessManagementRequest as ManagementRequest,
    GoogleBusinessAssignmentPreview as Preview, GoogleBusinessSchedule as Schedule)
from models.media_operations import MediaOperationTask as Task
from services import google_business as g

LIVE_SCHEDULES = ('scheduled', 'dispatching', 'accepted', 'unknown')


def instant(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None: raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError): raise HTTPException(422, '时间必须包含时区偏移')


def window(start, end, days):
    start, end = instant(start), instant(end)
    if not start < end or end - start > timedelta(days=days): raise HTTPException(422, '请选择有效的时间范围')
    return start, end


async def owned_binding(db, ctx, identity, *, lock=False):
    query = select(Binding).join(Connection, Binding.connection_id == Connection.id).where(Binding.id == identity, Connection.owner_id == ctx.identity).execution_options(populate_existing=True)
    if lock: query = query.with_for_update()
    result = await db.scalar(query)
    if not result: raise HTTPException(404, '该商家未绑定到你的 Google 连接')
    return result


async def cancel_binding_schedules(db, identity, message="商家已暂停或停止，原排期已取消"):
    await db.execute(update(Schedule).where(Schedule.binding_id == identity, Schedule.status == 'scheduled')
        .values(status='cancelled', message=message, updated_at=g.now(), revision=Schedule.revision + 1).execution_options(synchronize_session=False))


async def remember(db, ctx, request_id, kind, payload, result=None):
    key = g.media._key(request_id); fingerprint = g.digest({'kind': kind, 'payload': payload})
    old = await db.scalar(select(ManagementRequest).where(ManagementRequest.owner_id == ctx.identity, ManagementRequest.request_id == key))
    if old:
        if old.kind != kind or old.fingerprint != fingerprint: raise HTTPException(409, '相同请求编号对应不同管理操作')
        return old.result
    if result is not None:
        db.add(ManagementRequest(owner_id=ctx.identity, request_id=key, kind=kind, fingerprint=fingerprint, result=result, created_at=g.now()))
    return None


async def portfolio(db, user, *, q=None, lifecycle='all', skip=0, limit=50):
    ctx = await g.context(db, user, owner=True)
    options = await g.media.options(db, user)
    assignees = []
    for candidate in options['assignees']:
        employee = await db.get(Employees, candidate['id'])
        if employee and (candidate['id'] == ctx.identity or g.normalized_role(SimpleNamespace(role=employee.role)) != 'super_admin'): assignees.append(candidate)
    bindings = (await db.scalars(select(Binding).join(Connection, Binding.connection_id == Connection.id).where(Connection.owner_id == ctx.identity))).all()
    by_customer = {row.customer_id: row for row in bindings}
    foreign = set((await db.scalars(select(Binding.customer_id).join(Connection, Binding.connection_id == Connection.id).where(Connection.owner_id != ctx.identity))).all())
    summary = {name: 0 for name in ('unbound', 'active', 'paused', 'stopped')}
    items = []
    for customer in (await db.scalars(select(Customers).order_by(Customers.business_name, Customers.id))).all():
        if customer.id in foreign: continue
        binding = by_customer.get(customer.id)
        state = ('stopped' if not binding.active else binding.lifecycle) if binding else 'unbound'
        if not binding and customer.status != 'closed': continue
        connection = await db.get(Connection, binding.connection_id) if binding else None
        row = {'customer_id': customer.id, 'customer_name': customer.business_name, 'customer_status': customer.status,
            'industry': customer.industry or '', 'region': customer.state or customer.city or '', 'cooperation_eligible': customer.status == 'closed',
            'cooperation_reason': None if customer.status == 'closed' else '客户当前不是合作已成交状态，请先核对客户状态',
            'binding_id': binding.id if binding else None, 'revision': binding.revision if binding else None, 'lifecycle': state,
            'primary_operator_id': binding.primary_operator_id if binding else None, 'primary_operator_name': binding.primary_operator_name if binding else None,
            'connection_id': connection.id if connection else None, 'connection_needs_reconnect': bool(connection and (connection.needs_reconnect or not connection.active)),
            'location_name': binding.location_name if binding else None,
            'eligible_assignee_ids': [item['id'] for item in assignees if customer.id in item.get('eligible_customer_ids', [])]}
        if q and q.strip().casefold() not in customer.business_name.casefold(): continue
        summary[state] += 1
        if lifecycle == 'all' or lifecycle == state: items.append(row)
    from services.google_business_scheduler import configuration
    return {'items': items[skip:skip + limit], 'total': len(items), 'summary': summary, 'assignees': assignees, 'scheduler': configuration()}


async def lifecycle(db, user, binding_id, *, request_id, expected_revision, action, reason):
    ctx = await g.context(db, user, owner=True)
    payload = {'binding_id': binding_id, 'expected_revision': expected_revision, 'action': action, 'reason': reason}
    if action not in {'pause', 'stop', 'resume'} or not reason or len(reason.strip()) < 3: raise HTTPException(422, '请填写至少3字的操作原因')
    prior = await remember(db, ctx, request_id, 'lifecycle', payload)
    if prior is not None: return prior
    binding = await owned_binding(db, ctx, binding_id)
    if action == 'resume':
        location_name, connection_id = binding.location_name, binding.connection_id
        data = await g._read_provider(db, user, connection_id, 'locations')
        if not any(row['location_name'] == location_name for row in data['items']): raise HTTPException(409, '原门店已不在授权列表，请先重新连接并核对')
    async with g.write(db):
        ctx = await g.context(db, user, owner=True)
        old = await remember(db, ctx, request_id, 'lifecycle', payload)
        if old is not None: return old
        binding = await owned_binding(db, ctx, binding_id, lock=True)
        if binding.revision != expected_revision: raise HTTPException(409, '商家配置已更新，请刷新后重试')
        if action == 'resume':
            customer = await db.get(Customers, binding.customer_id, populate_existing=True)
            if not customer or customer.status != 'closed': raise HTTPException(409, '请先确认客户已恢复合作状态')
            if binding.active and binding.lifecycle == 'active': raise HTTPException(409, '商家已在运营中')
        if action == 'pause' and (not binding.active or binding.lifecycle != 'active'): raise HTTPException(409, '只能暂停正在运营的商家')
        if action == 'stop' and not binding.active: raise HTTPException(409, '该商家已经停止，请刷新归档状态')
        binding.lifecycle = {'pause': 'paused', 'stop': 'stopped', 'resume': 'active'}[action]
        binding.active = action != 'stop'; binding.lifecycle_reason = reason.strip(); binding.revision += 1
        binding.primary_operator_id = None; binding.primary_operator_name = None
        await db.execute(update(Grant).where(Grant.binding_id == binding_id).values(can_reply=False, can_publish=False, updated_at=g.now()))
        await cancel_binding_schedules(db, binding_id)
        await g._audit(db, ctx, binding, 'lifecycle_' + action, {'reason': reason.strip()})
        result = g.binding_data(binding, {'can_read': True, 'can_reply': action == 'resume', 'can_publish': action == 'resume', 'can_manage': True})
        await remember(db, ctx, request_id, 'lifecycle', payload, result)
    return result


async def eligibility(db, ctx, binding, employee_id):
    employee = await db.get(Employees, employee_id, populate_existing=True)
    if employee and employee_id != ctx.identity and g.normalized_role(SimpleNamespace(role=employee.role)) == 'super_admin': return '其他老板账号不能作为此连接的主运营，请选择运营员工'
    if not binding.active or binding.lifecycle != 'active': return '商家已暂停或停止'
    customer = await db.get(Customers, binding.customer_id, populate_existing=True)
    if not customer or customer.status != 'closed': return '客户当前不是合作已成交状态'
    connection = await db.get(Connection, binding.connection_id, populate_existing=True)
    if not connection or not connection.active or connection.needs_reconnect: return 'Google 连接需要老板重新授权'
    try:
        await g.media._assignee(db, ctx, customer, employee_id)
    except HTTPException as exc: return str(exc.detail)
    return None


async def preview_assignment(db, user, *, binding_ids, employee_id, can_reply, can_publish):
    ctx = await g.context(db, user, owner=True)
    if not binding_ids or len(binding_ids) > 100 or len(set(binding_ids)) != len(binding_ids): raise HTTPException(422, '请选择1—100个不同商家')
    if not (can_reply or can_publish): raise HTTPException(422, '请至少选择一项 Google 操作权限')
    items = []
    async with g.write(db):
        for identity in binding_ids:
            binding = await owned_binding(db, ctx, identity, lock=True)
            reason = await eligibility(db, ctx, binding, employee_id)
            items.append({'binding_id': identity, 'customer_id': binding.customer_id, 'customer_name': binding.customer_name,
                'revision': binding.revision, 'eligible': reason is None, 'reason': reason,
                'customer_permissions_url': '/customers?detail=' + str(binding.customer_id)})
        row = Preview(id=str(uuid4()), owner_id=ctx.identity, employee_id=employee_id, can_reply=can_reply, can_publish=can_publish,
            snapshot=items, created_at=g.now(), expires_at=g.now() + timedelta(minutes=10))
        db.add(row)
    return {'preview_id': row.id, 'expires_at': g.iso(row.expires_at), 'employee_id': employee_id, 'items': items,
        'eligible_count': sum(item['eligible'] for item in items), 'ineligible_count': sum(not item['eligible'] for item in items)}


async def apply_assignment(db, user, *, request_id, preview_id):
    ctx = await g.context(db, user, owner=True)
    payload = {'preview_id': g.media._key(preview_id)}
    async with g.write(db):
        old = await remember(db, ctx, request_id, 'assignment', payload)
        if old is not None: return old
        preview = await db.get(Preview, preview_id, populate_existing=True)
        if not preview or preview.owner_id != ctx.identity: raise HTTPException(404, '分配预览不存在')
        if preview.applied_request_id: raise HTTPException(409, '此预览已经执行，请读取原请求结果')
        if g.aware(preview.expires_at) < g.now(): raise HTTPException(409, '预览已过期，请重新预览')
        items = []
        for before in preview.snapshot:
            binding = await owned_binding(db, ctx, before['binding_id'], lock=True)
            reason = before['reason'] if not before['eligible'] else None
            if reason is None and binding.revision != before['revision']: reason = '商家配置已更新，请重新预览'
            if reason is None: reason = await eligibility(db, ctx, binding, preview.employee_id)
            if reason is None:
                employee = await db.get(Employees, preview.employee_id)
                row = await db.scalar(select(Grant).where(Grant.binding_id == binding.id, Grant.employee_id == preview.employee_id).with_for_update())
                if not row:
                    row = Grant(binding_id=binding.id, employee_id=preview.employee_id, granted_by_id=ctx.identity); db.add(row)
                row.can_reply = preview.can_reply; row.can_publish = preview.can_publish; row.updated_at = g.now(); row.granted_by_id = ctx.identity
                if binding.primary_operator_id != preview.employee_id or not preview.can_publish:
                    await cancel_binding_schedules(db, binding.id, message="主运营或发布权限已变更，原排期已取消")
                binding.primary_operator_id = preview.employee_id; binding.primary_operator_name = employee.name; binding.revision += 1
                await g._audit(db, ctx, binding, 'primary_assigned', {'employee_id': preview.employee_id, 'can_reply': preview.can_reply, 'can_publish': preview.can_publish, 'preview_id': preview.id})
            items.append({'binding_id': binding.id, 'applied': reason is None, 'reason': reason, 'customer_permissions_url': before['customer_permissions_url']})
        result = {'request_id': request_id, 'applied_count': sum(item['applied'] for item in items), 'skipped_count': sum(not item['applied'] for item in items), 'items': items}
        preview.applied_request_id = request_id
        await remember(db, ctx, request_id, 'assignment', payload, result)
    return result


def schedule_data(row):
    return {key: getattr(row, key) for key in ('id', 'revision', 'binding_id', 'task_id', 'timezone', 'status', 'message', 'action_id')} | {'planned_at': g.iso(row.planned_at)}


async def schedule(db, user, binding_id, *, request_id, task_id, expected_revision, planned_at, timezone):
    ctx = await g.context(db, user); request_id = g.media._key(request_id); at = instant(planned_at)
    try: ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError): raise HTTPException(422, '请选择有效商家时区')
    async with g.write(db):
        binding, connection, _ = await g._binding(db, ctx, binding_id, action='publish', lock=True)
        task, payload, _ = await g._post_payload(db, ctx, binding, task_id, expected_revision)
        operator = binding.primary_operator_id
        if operator is None or task.assignee_id != operator: raise HTTPException(409, '请先分配主运营，并确保任务由该运营负责')
        if not ctx.owner and ctx.identity != operator: raise HTTPException(403, '仅主运营可管理此排期')
        employee = await db.get(Employees, operator, populate_existing=True)
        operator_user = SimpleNamespace(id=str(operator), name=employee.name, role=employee.role) if employee else None
        if not operator_user: raise HTTPException(409, '主运营账号已失效')
        operator_ctx = await g.context(db, operator_user)
        await g._binding(db, operator_ctx, binding_id, action='publish', lock=True)
        fingerprint = g.digest(payload)
        old = await db.scalar(select(Schedule).where(Schedule.request_id == request_id))
        if old:
            if (old.binding_id, old.task_id, old.task_revision, old.payload_fingerprint, g.aware(old.planned_at), old.timezone, old.created_by_id) != (binding_id, task_id, expected_revision, fingerprint, at, timezone, ctx.identity):
                raise HTTPException(409, '相同请求编号对应不同排期')
            return schedule_data(old)
        if at <= g.now() or at > g.now() + timedelta(days=366): raise HTTPException(422, '排期须为未来一年内的时间，不能自动补发历史内容')
        duplicate = await db.scalar(select(Schedule.id).where(Schedule.task_id == task_id, Schedule.status.in_(LIVE_SCHEDULES)))
        existing_action = await db.scalar(select(Action.id).where(Action.task_id == task_id, Action.kind == 'post_publish', Action.status.in_(('pending', 'unknown', 'accepted', 'succeeded'))))
        if duplicate or existing_action: raise HTTPException(409, '此任务已有排期或发布请求，请先查询原结果')
        row = Schedule(binding_id=binding_id, task_id=task_id, task_revision=expected_revision, payload_fingerprint=fingerprint,
            operator_id=operator, owner_id=connection.owner_id, request_id=request_id, planned_at=at, timezone=timezone, status='scheduled',
            revision=1, message='已保存CRM排期；实际自动发布取决于独立调度开关', created_by_id=ctx.identity, created_at=g.now(), updated_at=g.now())
        db.add(row); await db.flush()
        await g._audit(db, ctx, binding, 'schedule_created', {'schedule_id': row.id, 'planned_at': g.iso(at), 'task_id': task_id})
        result = schedule_data(row)
    return result


async def cancel_schedule(db, user, identity, expected_revision):
    ctx = await g.context(db, user)
    async with g.write(db):
        row = await db.get(Schedule, identity, populate_existing=True)
        if not row: raise HTTPException(404, '排期不存在')
        binding, _, _ = await g._binding(db, ctx, row.binding_id)
        if not ctx.owner and (row.operator_id != ctx.identity or binding.primary_operator_id != ctx.identity): raise HTTPException(403, '仅老板或当前主运营可取消')
        if row.status == 'cancelled': return schedule_data(row)
        if row.revision != expected_revision: raise HTTPException(409, '排期已更新，请重新读取')
        if row.status not in {'scheduled', 'blocked', 'missed'} or row.action_id is not None: raise HTTPException(409, '排期已提交或结果待确认，请查询原发布结果')
        row.status = 'cancelled'; row.revision += 1; row.updated_at = g.now(); row.message = '已取消，恢复商家不会自动恢复本排期'
        await g._audit(db, ctx, binding, 'schedule_cancelled', {'schedule_id': row.id})
        return schedule_data(row)


async def calendar(db, user, *, start, end, binding_id=None):
    ctx = await g.context(db, user); start, end = window(start, end, 93)
    query = select(Task, Binding).join(Binding, Binding.customer_id == Task.customer_id).join(Connection, Binding.connection_id == Connection.id).where(Task.platform == 'google_business', Task.due_at >= start, Task.due_at < end)
    if ctx.owner: query = query.where(Connection.owner_id == ctx.identity)
    else: query = query.where(Task.assignee_id == ctx.identity)
    if binding_id is not None: query = query.where(Binding.id == binding_id)
    # Scheduled publication may differ from internal deadline; include either.
    scheduled_tasks = select(Schedule.task_id).where(Schedule.planned_at >= start, Schedule.planned_at < end)
    query = select(Task, Binding).join(Binding, Binding.customer_id == Task.customer_id).join(Connection, Binding.connection_id == Connection.id).where(Task.platform == 'google_business', or_((Task.due_at >= start) & (Task.due_at < end), Task.id.in_(scheduled_tasks)))
    query = query.where(Connection.owner_id == ctx.identity) if ctx.owner else query.where(Task.assignee_id == ctx.identity)
    if binding_id is not None: query = query.where(Binding.id == binding_id)
    items = []
    for task, binding in (await db.execute(query.order_by(Task.due_at).limit(500))).all():
        if not ctx.owner:
            try: await g._binding(db, ctx, binding.id)
            except HTTPException as exc:
                if exc.status_code in {403, 404}: continue
                raise
        schedules = (await db.scalars(select(Schedule).where(Schedule.task_id == task.id).order_by(Schedule.id.desc()))).all()
        row = schedules[0] if schedules else None
        if row and row.action_id:
            action = await db.get(Action, row.action_id)
            if action and action.status != row.status: projected = schedule_data(row) | {'status': action.status, 'message': action.message}
            else: projected = schedule_data(row)
        else: projected = schedule_data(row) if row else None
        blocked = None
        try:
            if row and row.status in LIVE_SCHEDULES: raise HTTPException(409, '此任务已有排期或结果待确认')
            if binding.primary_operator_id is None or task.assignee_id != binding.primary_operator_id: raise HTTPException(409, '请先分配主运营并核对任务负责人')
            if not ctx.owner and ctx.identity != binding.primary_operator_id: raise HTTPException(403, '仅主运营可以排期')
            employee = await db.get(Employees, binding.primary_operator_id, populate_existing=True)
            if not employee: raise HTTPException(409, '主运营账号已失效')
            operator_ctx = await g.context(db, SimpleNamespace(id=str(employee.id), role=employee.role, name=employee.name))
            await g._binding(db, operator_ctx, binding.id, action='publish')
            await g._post_payload(db, ctx, binding, task.id, task.revision)
            prior_action = await db.scalar(select(Action.id).where(Action.task_id == task.id, Action.kind == 'post_publish', Action.status.in_(('pending', 'unknown', 'accepted', 'succeeded'))).limit(1))
            if prior_action: raise HTTPException(409, '此任务已有发布请求，请核对原结果')
        except HTTPException as exc: blocked = str(exc.detail)
        items.append({'can_schedule': blocked is None, 'schedule_blocked_reason': blocked, 'task_id': task.id, 'title': task.title, 'customer_id': task.customer_id, 'customer_name': task.customer_name,
            'binding_id': binding.id, 'assignee_id': task.assignee_id, 'assignee_name': task.assignee_name, 'status': task.status,
            'due_at': g.iso(task.due_at), 'timezone': task.timezone, 'revision': task.revision, 'schedule': projected})
    from services.google_business_scheduler import configuration
    return {'items': items, 'scheduler': configuration(), 'from': g.iso(start), 'to': g.iso(end)}


async def management_request(db, user, request_id):
    ctx = await g.context(db, user); key = g.media._key(request_id)
    if ctx.owner:
        row = await db.scalar(select(ManagementRequest).where(ManagementRequest.owner_id == ctx.identity, ManagementRequest.request_id == key))
        if row: return {'request_id': key, 'kind': row.kind, 'result': row.result}
    query = select(Schedule).where(Schedule.request_id == key)
    query = query.where(Schedule.owner_id == ctx.identity) if ctx.owner else query.where(Schedule.created_by_id == ctx.identity)
    row = await db.scalar(query)
    if not row: raise HTTPException(404, '管理请求尚未登记')
    if not ctx.owner: await g._binding(db, ctx, row.binding_id)
    return {'request_id': key, 'kind': 'schedule', 'result': schedule_data(row)}


async def statistics(db, user, *, start, end, employee_id=None, binding_id=None):
    ctx = await g.context(db, user, owner=True); start, end = window(start, end, 366)
    bindings = (await db.scalars(select(Binding).join(Connection, Binding.connection_id == Connection.id).where(Connection.owner_id == ctx.identity))).all()
    ids = [row.id for row in bindings if binding_id is None or row.id == binding_id]
    names = {row.id: row.customer_name for row in bindings}
    columns = ('reply_succeeded', 'post_succeeded', 'pending', 'accepted', 'unknown', 'failed', 'rejected')
    totals = {name: 0 for name in (*columns, 'draft', 'in_review', 'ready', 'completed', 'blocked')}; employees = {}; records = []; fallback = 0
    query = select(Action).where(Action.binding_id.in_(ids), Action.kind.in_(('review_reply', 'post_publish')))
    if employee_id is not None: query = query.where(Action.actor_id == employee_id)
    for row in (await db.scalars(query.order_by(Action.id.desc()))).all():
        at = (row.confirmed_at or row.updated_at) if row.status == 'succeeded' else row.created_at
        if not start <= g.aware(at) < end: continue
        item = employees.setdefault(row.actor_id, {'employee_id': row.actor_id, 'employee_name': row.actor_name, **{name: 0 for name in columns}})
        field = ('reply_succeeded' if row.kind == 'review_reply' else 'post_succeeded') if row.status == 'succeeded' else row.status
        if field in totals: totals[field] += 1; item[field] += 1
        if row.status == 'succeeded' and row.confirmed_at is None: fallback += 1
        if len(records) < 100: records.append((await g.action_data_with_image(db, row, ctx)) | {'customer_name': names[row.binding_id]})
    task_query = select(Task).where(Task.customer_id.in_([row.customer_id for row in bindings if row.id in ids]), Task.platform == 'google_business', Task.due_at >= start, Task.due_at < end)
    if employee_id is not None: task_query = task_query.where(Task.assignee_id == employee_id)
    for task in (await db.scalars(task_query)).all(): totals[task.status] += 1
    return {'from': g.iso(start), 'to': g.iso(end), 'totals': totals, 'employees': list(employees.values()), 'records': records,
        'legacy_success_time_fallback_count': fallback, 'basis': 'provider_confirmation_and_internal_tasks_separate'}
