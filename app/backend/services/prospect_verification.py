"""Authoritative quality revisions in existing immutable operation logs.

Source imports and arbitrary profile JSON cannot assert a human verification.
Callers of mutation helpers own the transaction. No schema or consent changes.
"""
import json
import re
from copy import deepcopy
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import JSON, String, cast, func, select

from dependencies.auth import normalize_system_role
from models.merchant_pool import MerchantPool
from models.operation_logs import Operation_logs
from models.sales_leads import SalesLeads
from services.phone_numbers import phone_match_key
from services.sales_contact_protection import blocked_phone_keys, contact_protection_summary, PROTECTION_NOTICE
from services.sales_dossiers import active_actor, inherited_access
from services.sales_enrichment import enrichment_read_only_reason

QUALITY_STATUSES = ('pending', 'valid', 'invalid_phone', 'not_target', 'closed')
SOURCE_TYPES = ('public_business_profile', 'recruitment_contact', 'unknown')
QUALITY_ACTION_PREFIX = 'prospect_quality:'


def unpack(value):
    if isinstance(value, dict):
        return deepcopy(value)
    try:
        result = json.loads(value or '{}')
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}


def initial_prospect_quality():
    return {'revision': 0, 'status': 'pending', 'verified_at': None,
            'verified_by_id': None, 'verified_by_name': None, 'method': None, 'notes': '',
            'corrected_fields': {'business_name': None, 'address': None, 'contact_name': None, 'chinese_service': 'unknown'}}


def source_metadata_from_raw(raw_payload, record=None):
    raw = unpack(raw_payload)
    supplied = raw.get('prospect_source')
    supplied = supplied if isinstance(supplied, dict) else {}
    def field(key):
        return (record.get(key) if isinstance(record, dict) else getattr(record, key, None)) if record is not None else None
    label = str(field('data_source') or raw.get('data_source') or raw.get('来源') or '')
    address = str(field('address') or raw.get('address') or raw.get('商家位置') or '')
    name = str(field('business_name') or raw.get('business_name') or raw.get('商家名称') or '')
    source_url = supplied.get('source_url') or raw.get('source_url') or raw.get('evidence_url')
    if not isinstance(source_url, str) or not re.match(r'^https?://[^\s/]+', source_url):
        source_url = None
    source_date = supplied.get('source_date') or raw.get('source_date')
    if not source_date:
        match = re.search(r'广告日期(?:/刷新日)?[：:]\s*(\d{4}-\d{2}-\d{2})', address)
        if not match and '招聘' in label:
            match = re.search(r'(?:^|\|)(\d{4}-\d{2}-\d{2})(?:\||$)', label)
        source_date = match.group(1) if match else None
    try:
        source_date = date.fromisoformat(str(source_date)).isoformat() if source_date else None
    except ValueError:
        source_date = None
    verification_type = supplied.get('verification_type')
    if verification_type not in SOURCE_TYPES:
        verification_type = 'recruitment_contact' if '招聘' in label or '中文招聘来源' in address or ('店名待核验' in name and '招聘' in name) else 'unknown'
    collected = field('collected_at')
    return {'source_url': source_url, 'source_date': source_date, 'verification_type': verification_type,
            'source_label': label or None, 'imported_at': collected.isoformat() if isinstance(collected, datetime) else None}


def _action(kind, entity_id):
    if kind not in {'pool', 'lead'}:
        raise ValueError('Unknown prospect entity kind')
    return f'{QUALITY_ACTION_PREFIX}{kind}:{int(entity_id)}'


def _quality(log, kind, entity_id):
    payload = unpack(log.action_detail)
    after = payload.get('after')
    if payload.get('entity_kind') != kind or payload.get('entity_id') != entity_id or not isinstance(after, dict) or after.get('status') not in QUALITY_STATUSES or type(after.get('revision')) is not int or after['revision'] < 1:
        raise HTTPException(503, '核验修订记录暂不可读取，请联系管理员；本次未修改记录')
    return deepcopy(after)


async def quality_for_many(db, entity_kind, entity_ids):
    ids = sorted({int(value) for value in entity_ids})
    result = {entity_id: initial_prospect_quality() for entity_id in ids}
    if not ids:
        return result
    actions = {_action(entity_kind, entity_id): entity_id for entity_id in ids}
    logs = (await db.scalars(select(Operation_logs).where(Operation_logs.action_type.in_(actions))
                             .order_by(Operation_logs.id.desc()))).all()
    seen = set()
    for log in logs:
        entity_id = actions[log.action_type]
        if entity_id not in seen:
            result[entity_id] = _quality(log, entity_kind, entity_id)
            seen.add(entity_id)
    return result


async def quality_for(db, entity_kind, entity_id):
    return (await quality_for_many(db, entity_kind, [entity_id]))[entity_id]


async def ensure_quality_history_retained(db, entity_kind, entity_ids):
    """Caller holds entity/workflow locks; keep audited IDs from being reused."""
    values = await quality_for_many(db, entity_kind, entity_ids)
    if any(value['revision'] > 0 for value in values.values()):
        raise HTTPException(409, '商家已有人工核验历史，请使用归档保留资料和修订记录，不能永久删除')


async def inherit_pool_quality(db, merchant, lead, actor):
    """Called within the locked assignment transaction; never reads another lead."""
    previous = await quality_for(db, 'pool', merchant.id)
    if not previous['revision'] or (await quality_for(db, 'lead', lead.id))['revision']:
        return
    now = datetime.now(timezone.utc)
    after = deepcopy(previous)
    after['revision'] = 1
    after['origin'] = {'entity_kind': 'pool', 'entity_id': merchant.id, 'revision': previous['revision']}
    payload = {'schema_version': 1, 'entity_kind': 'lead', 'entity_id': lead.id, 'revision': 1,
               'before': initial_prospect_quality(), 'after': after, 'origin': after['origin'],
               'actor': {'id': int(actor.id), 'name': actor.name}, 'created_at': now.isoformat(), 'action': 'inherit_pool_quality'}
    db.add(Operation_logs(user_id=str(actor.id), action_type=_action('lead', lead.id),
                          action_detail=json.dumps(payload, ensure_ascii=False), operator_name=actor.name, created_at=now))
    await db.flush()


def quality_status_expression(entity_kind, id_column, dialect_name):
    """Correlated latest server audit, never client-supplied raw quality JSON."""
    action = f'{QUALITY_ACTION_PREFIX}{entity_kind}:' + cast(id_column, String)
    # Aggregate the quality ledger once. The unindexed legacy log table must
    # not be scanned again for every prospect in a 5,000-record facet query.
    latest_ids = select(Operation_logs.action_type, func.max(Operation_logs.id).label('latest_id')).where(
        Operation_logs.action_type.startswith(f'{QUALITY_ACTION_PREFIX}{entity_kind}:')).group_by(Operation_logs.action_type).cte().prefix_with('MATERIALIZED')
    latest = select(Operation_logs.action_detail).join(latest_ids, latest_ids.c.latest_id == Operation_logs.id).where(
        latest_ids.c.action_type == action).correlate(id_column.table).scalar_subquery()
    status = cast(latest, JSON)['after']['status'].as_string() if dialect_name == 'postgresql' else func.json_extract(latest, '$.after.status')
    return func.coalesce(status, 'pending')


async def authorize_prospect(db, kind, entity_id, user):
    actor = await active_actor(db, user)
    role = normalize_system_role(actor.role)
    model = MerchantPool if kind == 'pool' else SalesLeads
    row = (await db.scalars(select(model).where(model.id == entity_id).execution_options(populate_existing=True))).one_or_none()
    allowed = row is not None
    if kind == 'pool':
        allowed = allowed and (role in {'admin', 'super_admin'} or (role == 'sales_manager' and row.created_by_id == actor.id))
    else:
        allowed = allowed and await inherited_access(db, actor, row)
    if not allowed:
        raise HTTPException(404, '商家不存在或不在您的核验权限范围内')
    reason = ('该商家已离开待分配池，请在有权限的销售线索中核验' if row.pool_status != 'pending' or row.converted_lead_id else None) if kind == 'pool' else enrichment_read_only_reason(row)
    return row, actor, reason


async def verification_view(db, kind, entity_id, user, *, include_history=True):
    row, actor, reason = await authorize_prospect(db, kind, entity_id, user)
    quality = await quality_for(db, kind, entity_id)
    source_row = row
    if kind == 'lead':
        # No profile/custom-fields or other prospect/owner data is exposed.
        source_row = await db.get(MerchantPool, row.merchant_pool_id) if row.merchant_pool_id else None
    source = source_metadata_from_raw(source_row.raw_payload if source_row else None, source_row)
    if kind == 'pool':
        key = phone_match_key(row.phone, row.country)
        blocked = bool(key and await blocked_phone_keys(db, {key}))
        protection = {'can_contact': not blocked, 'reason': PROTECTION_NOTICE if blocked else None}
    else:
        existing = await contact_protection_summary(db, row)
        protection = {'can_contact': existing['can_contact'], 'reason': existing['reason']}
    history = []
    if include_history:
        logs = (await db.scalars(select(Operation_logs).where(Operation_logs.action_type == _action(kind, entity_id)).order_by(Operation_logs.id.desc()).limit(20))).all()
        history = [{'id': log.id, **unpack(log.action_detail)} for log in logs]
    return {'entity_kind': kind, 'entity_id': entity_id, 'prospect_quality': quality, 'prospect_source': source,
            'effective_fields': {**{key: getattr(row, key) for key in ('business_name', 'address', 'contact_name', 'phone', 'city', 'state')}, 'chinese_service': quality['corrected_fields'].get('chinese_service', 'unknown')},
            'can_edit': reason is None, 'read_only_reason': reason, 'contact_protection': protection, 'history': history}


async def save_verification(db, kind, entity_id, user, payload):
    # Existing assignment uses merchant -> workflow lock order.
    from services.merchant_row_locks import lock_merchant_rows
    from services.sales_workflow_locks import lock_sales_workflow
    if kind == 'pool':
        await lock_merchant_rows(db, [entity_id])
        await lock_sales_workflow(db)
    else:
        await lock_sales_workflow(db, lead_ids=[entity_id])
    row, actor, reason = await authorize_prospect(db, kind, entity_id, user)
    if reason:
        raise HTTPException(409, reason)
    before = await quality_for(db, kind, entity_id)
    if payload.expected_revision != before['revision']:
        raise HTTPException(409, '核验已被其他人更新，请读取最新记录后再保存；本次输入未写入')
    corrected = deepcopy(before['corrected_fields'])
    updates = payload.corrected_fields.model_dump(exclude_unset=True)
    before_fields = {key: getattr(row, key) for key in ('business_name', 'address', 'contact_name')}
    for key in ('business_name', 'address', 'contact_name'):
        if key in updates:
            # Unknown blank input does not erase an existing business identity.
            if updates[key] is not None:
                setattr(row, key, updates[key])
                corrected[key] = updates[key]
    if 'chinese_service' in updates:
        corrected['chinese_service'] = updates['chinese_service']
    now = datetime.now(timezone.utc)
    after = {'revision': before['revision'] + 1, 'status': payload.status, 'verified_at': now.isoformat(),
             'verified_by_id': actor.id, 'verified_by_name': actor.name, 'method': payload.method,
             'notes': payload.notes, 'corrected_fields': corrected}
    task_effect = None
    if kind == 'lead':
        from zoneinfo import ZoneInfo
        from models.sales_daily_dial_tasks import SalesDailyDialTasks
        from services.sales_task_assignment import sync_pending_daily_tasks
        today = now.astimezone(ZoneInfo('Asia/Shanghai')).date()
        retained_ids = set(before.get('quality_cancelled_task_ids', []))
        if payload.status in {'invalid_phone', 'not_target', 'closed'}:
            pending_ids = set((await db.scalars(select(SalesDailyDialTasks.id).where(
                SalesDailyDialTasks.lead_id == row.id, SalesDailyDialTasks.status == 'pending',
                SalesDailyDialTasks.task_date >= today))).all())
            await sync_pending_daily_tasks(db, row, None, now=now)
            retained_ids |= pending_ids
            task_effect = {'cancelled_task_ids': sorted(pending_ids), 'restored_task_ids': []}
        elif payload.status == 'valid' and before['status'] in {'invalid_phone', 'not_target', 'closed'} and retained_ids:
            # Restore only the tasks this quality workflow cancelled. Do not
            # revive unrelated manual cancellations or rewrite old ownership.
            restored = []
            protection = await contact_protection_summary(db, row)
            if protection['can_contact'] and row.assigned_sales_id and not row.do_not_contact and not row.is_blacklisted and row.status not in {'blocked', 'lost', 'won'} and not row.converted_customer_id:
                tasks = (await db.scalars(select(SalesDailyDialTasks).where(
                    SalesDailyDialTasks.id.in_(retained_ids), SalesDailyDialTasks.lead_id == row.id,
                    SalesDailyDialTasks.sales_employee_id == row.assigned_sales_id,
                    SalesDailyDialTasks.task_date >= today, SalesDailyDialTasks.status == 'cancelled'))).all()
                for task in tasks:
                    task.status = 'pending'
                    restored.append(task.id)
            retained_ids -= set(restored)
            task_effect = {'cancelled_task_ids': [], 'restored_task_ids': restored}
        if retained_ids:
            after['quality_cancelled_task_ids'] = sorted(retained_ids)
    audit = {'schema_version': 1, 'entity_kind': kind, 'entity_id': entity_id, 'revision': after['revision'],
             'before': before, 'after': after, 'before_fields': before_fields,
             'after_fields': {key: getattr(row, key) for key in before_fields},
             'actor': {'id': actor.id, 'name': actor.name}, 'created_at': now.isoformat()}
    if task_effect:
        audit['task_effect'] = task_effect
    db.add(Operation_logs(user_id=str(actor.id), action_type=_action(kind, entity_id),
                          action_detail=json.dumps(audit, ensure_ascii=False), operator_name=actor.name, created_at=now))
    await db.flush()
    return after
