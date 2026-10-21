"""Opt-in, bounded automatic receipts for new invoices only.

The provider remains read-only. Durable jobs call the original ledger transaction,
with a fresh owner authorization, cash proof, duplicate, close and commission check.
"""
import asyncio
import contextlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from models.employees import Employees
from models.payments import Payments
from models.stripe_auto_posting import StripeAutoPostingJob as Job, StripeAutoPostingPolicy as Policy
from models.stripe_history_reconciliation import StripeHistoryBinding as Binding, StripeHistoryInvoiceReview as Review, StripeHistoryPosting as Posting
from services import stripe_history_provider as provider
from services import stripe_history_reconciliation as history
from services.sales_workflow_locks import lock_sales_workflow

LIMIT = 5
STARTUP_DELAY_SECONDS = 300
POLL_SECONDS = 30
LEASE_SECONDS = 120
BATCH_LIMIT = 5
JOB_STATES = ('queued', 'retry', 'manual_required', 'auto_posted', 'manual_completed')
BEIJING = ZoneInfo('Asia/Shanghai')


def now():
    return datetime.now(timezone.utc)


def enabled():
    return (os.getenv('STRIPE_AUTO_POSTING_ENABLED') or 'true').strip().lower() not in {'0', 'false', 'no', 'off'}


def parse_time(value):
    try:
        return history.utc(datetime.fromisoformat(value)) if isinstance(value, str) else history.utc(value)
    except (ValueError, TypeError):
        return None


def scope(binding):
    return history.digest({'account': binding.account_id, 'live': binding.livemode, 'sub': binding.stripe_subscription_id,
        'customer': binding.stripe_customer_id, 'crm': binding.crm_snapshot, 'price': binding.price_snapshot,
        'income_type': binding.income_type, 'sync_from': binding.sync_from})


async def commission_scope(db, binding):
    """Pin existing attribution and agreement configuration, without changing it."""
    from services.commissions import commission_ledger_available
    if not await commission_ledger_available(db):
        return 'unavailable'
    from models.commissions import CustomerCommissionAttribution, CommissionAgreement, SalesPartner
    engagement_id = binding.crm_snapshot.get('engagement_id')
    condition = or_(CustomerCommissionAttribution.engagement_id == engagement_id, CustomerCommissionAttribution.engagement_id.is_(None)) if engagement_id else CustomerCommissionAttribution.engagement_id.is_(None)
    attrs = (await db.scalars(select(CustomerCommissionAttribution).where(CustomerCommissionAttribution.customer_id == binding.customer_id, condition).order_by(CustomerCommissionAttribution.id))).all()
    ids = [row.partner_id for row in attrs]
    partners = (await db.scalars(select(SalesPartner).where(SalesPartner.id.in_(ids)).order_by(SalesPartner.id))).all()
    agreements = (await db.scalars(select(CommissionAgreement).where(CommissionAgreement.partner_id.in_(ids)).order_by(CommissionAgreement.id))).all()
    def values(rows, fields):
        return [{name: getattr(row, name) for name in fields} for row in rows]
    return history.digest({'attributions': values(attrs, ('id','engagement_id','partner_id','attribution_role','commission_mode','commission_start_date','first_service_start','effective_from','effective_to','is_active')),
        'partners': values(partners, ('id','partner_type','status','stopped_at')),
        'agreements': values(agreements, ('id','partner_id','version','business_line_id','product_id','calculation_version','renewal_policy','first_order_rate','renewal_rate','activity_decay_json','effective_from','effective_to','status'))})


async def authority(db, policy):
    actor = await db.get(Employees, policy.authorized_by_id, populate_existing=True)
    if not actor or actor.role != 'super_admin' or actor.status not in {'active', 'probation'}:
        raise HTTPException(409, '授权老板账号已停用或权限已变化，转人工核对')
    return SimpleNamespace(id=str(actor.id), name=actor.name or policy.authorized_by_name, role=actor.role)


async def eligible(db, binding):
    reasons = []
    if binding.status != 'active' or not binding.livemode or binding.account_id != history.STRIPE_ACCOUNT_ID:
        reasons.append('绑定未启用或不属于正式账户')
    if not await history.binding_context_matches(db, binding):
        reasons.append('客户服务或业务归属发生变化')
    if not binding.price_snapshot.get('price_id') or not binding.price_snapshot.get('billing_cycle'):
        reasons.append('固定套餐或周期未明确')
    return reasons


def subscription_matches(raw, binding, *, allow_past_due=False):
    value = history.subscription_data(raw)
    return value['valid'] and value['status'] in ({'active', 'past_due'} if allow_past_due else {'active'}) and value['subscription_id'] == binding.stripe_subscription_id and value['customer_id'] == binding.stripe_customer_id and all(
        value.get(key) == binding.price_snapshot.get(key) for key in ('price_id', 'currency', 'amount_minor', 'billing_cycle', 'tax_behavior'))


async def summary(db):
    enabled_count = await db.scalar(select(func.count()).select_from(Policy).where(Policy.enabled.is_(True))) or 0
    jobs = (await db.scalars(select(Job))).all()
    counts = {state: sum(job.status == state for job in jobs) for state in JOB_STATES}
    posted = (await db.execute(select(Posting, Payments).join(Payments, Payments.id == Posting.payment_id).where(Posting.action == 'auto_create_payment'))).all()
    counts['auto_posted'] = len(posted)
    def totals(today_only=False):
        result = {}
        for posting, payment in posted:
            if today_only and history.utc(posting.created_at).astimezone(BEIJING).date() != now().astimezone(BEIJING).date():
                continue
            currency = (payment.currency or 'USD').upper()
            item = result.setdefault(currency, {'currency': currency, 'amount': 0, 'count': 0})
            item['amount'] = round(item['amount'] + float(payment.amount_paid or 0), 2)
            item['count'] += 1
        return list(result.values())
    return {'enabled_count': enabled_count, 'counts': counts, 'totals': totals(), 'today_totals': totals(True)}


def trial_data(policy, binding):
    if not policy or not policy.trial:
        return None
    result = dict(policy.trial)
    checked = parse_time(result.get('checked_at'))
    if not checked or now() - checked > timedelta(hours=24) or result.get('scope_fingerprint') != scope(binding):
        result['passed'] = False
        result['reasons'] = list(result.get('reasons') or []) + ['模拟已过期或服务归属变化，请重新验证']
    return result


async def overview(db, user):
    await history.owner(db, user)
    bindings = (await db.scalars(select(Binding).where(Binding.account_id == history.STRIPE_ACCOUNT_ID, Binding.livemode.is_(True)).order_by(Binding.id))).all()
    items = []
    for binding in bindings:
        policy = await db.get(Policy, binding.id)
        reasons = await eligible(db, binding)
        last = await db.scalar(select(Job).where(Job.binding_id == binding.id).order_by(Job.created_at.desc(), Job.review_id.desc()).limit(1))
        items.append({'binding_id': binding.id, 'customer_name': binding.crm_snapshot['customer_name'], 'package_name': binding.crm_snapshot['package_name'],
            'stripe_subscription_id': binding.stripe_subscription_id, 'amount': binding.price_snapshot.get('amount_minor', 0) / 100,
            'currency': binding.price_snapshot.get('currency'), 'billing_cycle': binding.price_snapshot.get('billing_cycle'),
            'enabled': bool(policy and policy.enabled), 'effective_from': policy.effective_from if policy else None,
            'revision': policy.revision if policy else 0, 'eligible': not reasons, 'eligibility_reasons': reasons,
            'trial': trial_data(policy, binding), 'latest_job': {'status': last.status, 'reason': last.reason, 'payment_id': last.payment_id,
                'review_id': last.review_id, 'last_attempt_at': last.last_attempt_at} if last else None})
    return {'limit': LIMIT, 'items': items, **await summary(db)}


async def trial_bindings(db, payload, user):
    await history.owner(db, user)
    if len(set(payload.binding_ids)) != len(payload.binding_ids):
        raise HTTPException(400, '请选择 3–5 项不同服务')
    prepared = []
    reader = provider.reader()
    for binding_id in payload.binding_ids:
        binding = await history.get_binding(db, binding_id, user, active=True)
        reasons = await eligible(db, binding)
        if (await db.get(Policy, binding.id)) and (await db.get(Policy, binding.id)).enabled:
            raise HTTPException(409, '已开启的服务请先暂停再重新验证')
        fingerprint = scope(binding)
        commission_fingerprint = await commission_scope(db, binding)
        rows = (await db.scalars(select(Review).where(Review.binding_id == binding.id).order_by(Review.id.desc()))).all()
        candidate = next((row for row in rows if not row.snapshot.get('issues') and row.snapshot.get('stripe_charge_id')), None)
        invoice_count = 0
        if candidate is None:
            reasons.append('尚无可模拟核验的完整到账账单')
        try:
            remote = await asyncio.wait_for(reader.subscription(binding.stripe_subscription_id), timeout=25)
            if not subscription_matches(remote, binding):
                reasons.append('Stripe 当前订阅或固定价格与绑定不一致')
            if candidate:
                raw = await asyncio.wait_for(reader.invoice(candidate.stripe_invoice_id), timeout=25)
                fresh = history.invoice_snapshot(raw, binding)
                repeated = history.invoice_snapshot(await asyncio.wait_for(reader.invoice(candidate.stripe_invoice_id), timeout=25), binding)
                if fresh['issues'] or history.digest(fresh) != history.digest(repeated):
                    reasons.append('到账证据不完整或重复读取不一致')
                else:
                    invoice_count = 1
                    # The exact same original preview/close/commission checks, without a ledger write.
                    preview = history.accounting_payload(binding, fresh, user)
                    from services.finance_period_lock import ensure_payment_writes_open
                    await ensure_payment_writes_open(db, [preview], action='模拟自动入账')
                    from services.commissions import commission_ledger_available, preview_payment_commission
                    if await commission_ledger_available(db):
                        proof = await preview_payment_commission(db, Payments(**preview))
                        if proof['issues']:
                            reasons.append('现有分润依据或服务期间不完整')
        except (HTTPException, asyncio.TimeoutError):
            reasons.append('平台凭据、关账或原财务检查未通过，请先人工核对')
        prepared.append((binding.id, fingerprint, {'passed': not reasons, 'checked_at': now().isoformat(),
            'invoice_count': invoice_count, 'reasons': reasons, 'scope_fingerprint': fingerprint, 'commission_fingerprint': commission_fingerprint, 'batch_ids': list(payload.binding_ids)}))
    await lock_sales_workflow(db, employee_ids=[int(user.id)])
    await history.owner(db, user)
    complete_batch = all(item[2]['passed'] for item in prepared)
    for binding_id, fingerprint, trial in prepared:
        if not complete_batch and trial['passed']:
            trial['passed'] = False
            trial['reasons'].append('同批验证尚有未通过项目，请选定 3–5 项完整验证')
        binding = await history.get_binding(db, binding_id, user, active=True)
        if scope(binding) != fingerprint or await commission_scope(db, binding) != trial['commission_fingerprint']:
            raise HTTPException(409, '模拟期间绑定发生变化，请重新验证')
        policy = await db.get(Policy, binding_id, populate_existing=True)
        if policy and policy.enabled:
            raise HTTPException(409, '服务已开启，不能覆盖当前授权')
        if not policy:
            policy = Policy(binding_id=binding_id, enabled=False, revision=1, excluded_through_review_id=0,
                authorized_by_id=int(user.id), authorized_by_name=user.name or '', owner_note=payload.owner_note,
                scope_fingerprint=fingerprint, trial=trial)
            db.add(policy)
        else:
            policy.trial, policy.scope_fingerprint = trial, fingerprint
            policy.revision += 1
        policy.updated_at = now()
        history.audit(db, user, 'auto_trial_completed', {'trial': trial, 'financial_writes': False}, binding_id)
    await db.flush()
    result = await overview(db, user)
    return {**result, 'passed': all(item[2]['passed'] for item in prepared)}


async def update_policy(db, binding_id, payload, user):
    await lock_sales_workflow(db, employee_ids=[int(user.id)])
    binding = await history.get_binding(db, binding_id, user)
    policy = await db.get(Policy, binding_id, populate_existing=True)
    if not policy or policy.revision != payload.revision:
        raise HTTPException(409, '设置已变化，请重新读取后操作')
    if payload.enabled:
        if policy.enabled:
            return await overview(db, user)
        reasons = await eligible(db, binding)
        trial = policy.trial or {}
        at = now()
        checked = parse_time(trial.get('checked_at'))
        if reasons or not trial.get('passed') or not checked or at - checked > timedelta(hours=24) or trial.get('scope_fingerprint') != scope(binding) or trial.get('commission_fingerprint') != await commission_scope(db, binding):
            raise HTTPException(409, '需要先完成当前服务的 3–5 项模拟验证，且归属未变化')
        if await db.scalar(select(func.count()).select_from(Policy).where(Policy.enabled.is_(True))) >= LIMIT:
            raise HTTPException(409, '本轮最多开启 5 项服务，请先验证首批结果')
        policy.effective_from = at
        policy.excluded_through_review_id = await db.scalar(select(func.max(Review.id))) or 0
        policy.scope_fingerprint = scope(binding)
    if not payload.enabled:
        waiting = (await db.scalars(select(Job).where(Job.binding_id == binding.id, Job.status.in_(('queued', 'retry'))))).all()
        for job in waiting:
            job.status, job.reason_code, job.reason = 'manual_required', 'policy_paused', '自动入账已暂停，请人工核对'
            job.retry_at = job.lease_token = job.lease_until = None
    policy.enabled = payload.enabled
    policy.revision += 1
    policy.authorized_by_id, policy.authorized_by_name = int(user.id), user.name or ''
    policy.owner_note, policy.updated_at = payload.owner_note, now()
    history.audit(db, user, 'auto_policy_enabled' if payload.enabled else 'auto_policy_paused',
        {'policy_revision': policy.revision, 'effective_from': policy.effective_from.isoformat() if policy.effective_from else None, 'excluded_through_review_id': policy.excluded_through_review_id,
            'owner_note': payload.owner_note, 'new_invoices_only': True}, binding.id)
    await db.flush()
    return await overview(db, user)


async def enqueue_review(db, row, binding):
    policy = await db.get(Policy, binding.id)
    if not policy or not policy.enabled or row.id <= policy.excluded_through_review_id:
        return
    existing = await db.get(Job, row.id)
    posting = await db.get(Posting, row.id)
    if existing:
        if posting and (posting.fingerprint != row.fingerprint or row.snapshot.get('issues')):
            existing.status, existing.reason_code, existing.reason = 'manual_required', 'posted_evidence_changed', '已入账凭据发生变化，请核对原调整流程'
            existing.payment_id = posting.payment_id
        return
    if posting:
        return
    created = parse_time(row.snapshot.get('invoice_created'))
    historical = not created or not policy.effective_from or created <= history.utc(policy.effective_from)
    db.add(Job(review_id=row.id, binding_id=binding.id, policy_revision=policy.revision,
        authorization_snapshot={'authorized_by_id':policy.authorized_by_id, 'authorized_by_name':policy.authorized_by_name, 'effective_from':history.utc(policy.effective_from).isoformat() if policy.effective_from else None, 'policy_revision':policy.revision},
        status='manual_required' if historical else 'queued', reason_code='historical_excluded' if historical else None,
        reason='历史账单保留人工核对，不自动补记' if historical else None, attempt_count=0))


async def review_evidence(db, review_id):
    job = await db.get(Job, review_id)
    if not job:
        return None
    authorization = job.authorization_snapshot or {}
    posting = await db.get(Posting, review_id)
    return {'status': 'auto_posted' if posting and posting.action == 'auto_create_payment' else job.status, 'reason': job.reason, 'payment_id': posting.payment_id if posting else job.payment_id,
        'authorized_by_name': authorization.get('authorized_by_name'), 'effective_from': authorization.get('effective_from'),
        'processed_at': job.processed_at}


async def jobs(db, user, status='all'):
    await history.owner(db, user)
    query = select(Job, Review, Binding).join(Review, Review.id == Job.review_id).join(Binding, Binding.id == Job.binding_id)
    if status != 'all':
        query = query.where(Job.status == status)
    rows = (await db.execute(query.order_by(Job.created_at.desc(), Job.review_id.desc()).limit(100))).all()
    total = await db.scalar(select(func.count()).select_from(Job).where(Job.status == status)) if status != 'all' else await db.scalar(select(func.count()).select_from(Job))
    payments = {payment.id: payment for payment in (await db.scalars(select(Payments).where(Payments.id.in_([job.payment_id for job, _, _ in rows if job.payment_id])))).all()}
    return {'total': total, 'items': [{'id': job.review_id, 'review_id': job.review_id, 'binding_id': job.binding_id,
        'customer_name': binding.crm_snapshot['customer_name'], 'package_name': binding.crm_snapshot['package_name'],
        'currency': row.snapshot.get('currency') or binding.price_snapshot['currency'],
        'amount': float(payments[job.payment_id].amount_paid) if job.payment_id in payments else row.snapshot['service_minor'] / 100 if row.snapshot.get('service_minor') is not None else None,
        'status': job.status, 'reason': job.reason, 'payment_id': job.payment_id,
        'last_attempt_at': job.last_attempt_at, 'created_at': job.created_at} for job, row, binding in rows]}


async def queue_pending(sessions):
    async with sessions() as db:
        await lock_sales_workflow(db)
        selected = (await db.execute(select(Review, Binding).join(Binding, Binding.id == Review.binding_id).join(Policy, Policy.binding_id == Binding.id)
            .outerjoin(Job, Job.review_id == Review.id).outerjoin(Posting, Posting.review_id == Review.id).where(Policy.enabled.is_(True), Review.id > Policy.excluded_through_review_id,
                Job.review_id.is_(None), Posting.review_id.is_(None)).order_by(Review.id).limit(50))).all()
        for row, binding in selected:
            await enqueue_review(db, row, binding)
        await db.commit()


async def claim_job(sessions):
    async with sessions() as db:
        await lock_sales_workflow(db)
        at = now()
        job = await db.scalar(select(Job).where(Job.status.in_(('queued', 'retry')),
            or_(Job.retry_at.is_(None), Job.retry_at <= at), or_(Job.lease_until.is_(None), Job.lease_until <= at))
            .order_by(Job.last_attempt_at.asc().nullsfirst(), Job.review_id).limit(1))
        if job is None:
            return None
        job.lease_token, job.lease_until = secrets.token_hex(24), at + timedelta(seconds=LEASE_SECONDS)
        job.attempt_count += 1
        job.last_attempt_at = at
        result = {'review_id': job.review_id, 'binding_id': job.binding_id, 'token': job.lease_token}
        await db.commit()
        return result


async def outcome(sessions, claim, status, code, message):
    async with sessions() as db:
        await lock_sales_workflow(db)
        job = await db.get(Job, claim['review_id'], populate_existing=True)
        if not job or job.lease_token != claim['token']:
            return
        job.status, job.reason_code, job.reason = status, code, message[:500]
        job.retry_at = now() + timedelta(seconds=min(3600, 30 * 2 ** min(job.attempt_count, 6))) if status == 'retry' else None
        job.lease_token = job.lease_until = None
        await db.commit()


async def process_job(sessions, claim):
    try:
        async with sessions() as db:
            row = await db.get(Review, claim['review_id'])
            binding = await db.get(Binding, claim['binding_id'])
            if not row or not binding:
                raise HTTPException(409, '客户服务或核对记录不存在')
            invoice_id, sub_id = row.stripe_invoice_id, binding.stripe_subscription_id
        reader = provider.reader()
        remote = await asyncio.wait_for(reader.subscription(sub_id), timeout=25)
        raw = await asyncio.wait_for(reader.invoice(invoice_id), timeout=25)
        async with sessions() as db:
            await lock_sales_workflow(db)
            job = await db.get(Job, claim['review_id'], populate_existing=True)
            row = await db.get(Review, claim['review_id'], populate_existing=True)
            binding = await db.get(Binding, claim['binding_id'], populate_existing=True)
            policy = await db.get(Policy, claim['binding_id'], populate_existing=True)
            at = now()
            if not job or job.lease_token != claim['token'] or not job.lease_until or history.utc(job.lease_until) <= at:
                return
            if not policy or not policy.enabled or policy.revision != job.policy_revision or not enabled():
                raise HTTPException(409, '自动入账已暂停或授权发生变化，转人工核对')
            user = await authority(db, policy)
            if await eligible(db, binding) or policy.scope_fingerprint != scope(binding) or not subscription_matches(remote, binding, allow_past_due=True) or policy.trial.get('commission_fingerprint') != await commission_scope(db, binding):
                raise HTTPException(409, '当前客户服务、Stripe 订阅或固定价格发生变化，转人工核对')
            fresh = history.invoice_snapshot(raw, binding)
            created = parse_time(fresh.get('invoice_created'))
            if row.id <= policy.excluded_through_review_id or not created or created <= history.utc(policy.effective_from):
                raise HTTPException(409, '历史账单不在自动范围，保留人工核对')
            posting = await db.get(Posting, row.id)
            if posting:
                job.status = 'auto_posted' if posting.action == 'auto_create_payment' else 'manual_completed'
                job.reason = None if job.status == 'auto_posted' else '此账单已人工处理，无需重复记账'
                job.payment_id, job.processed_at = posting.payment_id, at
            else:
                pending_codes = {'provider_verification_required', 'cash_unverified', 'fee_unverified', 'payment_date', 'not_paid'}
                if fresh['issues']:
                    await history.save_invoice(db, binding, raw)
                    waiting_without_cash = ('not_paid' in fresh['issues'] and raw.get('paid') is False and raw.get('amount_paid') == 0 and raw.get('status') in {'open', 'draft'} and (not isinstance(raw.get('payment_intent'), dict) or raw['payment_intent'].get('amount_received', 0) == 0))
                    waiting_codes = pending_codes | {'partial_payment'}
                    intent = raw.get('payment_intent') if isinstance(raw.get('payment_intent'), dict) else {}
                    if not intent.get('latest_charge'):
                        waiting_codes.add('refund_or_dispute')  # No charge yet is missing proof, not a refund signal.
                    retry = set(fresh['issues']) <= (waiting_codes if waiting_without_cash else pending_codes)
                    job.status = 'retry' if retry else 'manual_required'
                    job.reason_code = 'evidence_pending' if retry else 'validation_required'
                    job.reason = ('；'.join(item['message'] for item in history.issues_data(fresh['issues'])) + ('，稍后自动重试' if retry else '，请人工核对'))[:500]
                    job.retry_at = at + timedelta(seconds=min(3600, 30 * 2 ** min(job.attempt_count, 6))) if retry else None
                    job.lease_token = job.lease_until = None
                    await db.commit()
                    return
                # Fresh read is persisted in the same transaction; shared checks cannot trust stale notifications.
                row = await history.save_invoice(db, binding, raw)
                result = await history.apply_verified_invoice(db, row, binding, fresh, revision=row.revision, action='create_payment',
                    existing_payment_id=None, verification_note='系统按老板授权核验新账单实际扣款并自动入账；授权版本 ' + str(policy.revision),
                    user=user, source='system_auto')
                job.status, job.payment_id, job.processed_at = 'auto_posted', result['payment_id'], at
                job.reason_code = job.reason = None
            job.retry_at = job.lease_token = job.lease_until = None
            await db.commit()
    except (asyncio.TimeoutError, TimeoutError):
        await outcome(sessions, claim, 'retry', 'provider_timeout', 'Stripe 读取超时，将自动重试')
    except HTTPException as error:
        retry = error.status_code >= 500
        message = error.detail if isinstance(error.detail, str) else 'Stripe 只读连接暂不可用，将自动重试'
        await outcome(sessions, claim, 'retry' if retry else 'manual_required', 'evidence_pending' if retry else 'validation_required', message)
    except Exception:
        # Rollback the complete ledger transaction, preserve the job for bounded retry, never log payer/credential payloads.
        await outcome(sessions, claim, 'retry', 'processing_retry', '处理暂未完成，将自动重试；重复扣款与账单仍受原防重检查')


async def run_batch(sessions=None):
    if not enabled():
        return {'processed': 0, 'enabled': False}
    if sessions is None:
        from core.database import db_manager
        sessions = db_manager.async_session_maker
    if sessions is None:
        return {'processed': 0, 'enabled': True}
    await queue_pending(sessions)
    count = 0
    for _ in range(BATCH_LIMIT):
        if not enabled():
            break
        claim = await claim_job(sessions)
        if not claim:
            break
        await process_job(sessions, claim)
        count += 1
    return {'processed': count, 'enabled': True}


async def loop():
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        with contextlib.suppress(Exception):
            await run_batch()
        await asyncio.sleep(POLL_SECONDS)


def start_auto_posting():
    if not enabled() or os.getenv('IS_LAMBDA') == 'true':
        return None
    return asyncio.create_task(loop())


async def stop_auto_posting(task):
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
