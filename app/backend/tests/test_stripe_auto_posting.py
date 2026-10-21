"""Opt-in accounting: real cash proof plus original ledger rules, no history backfill."""
import copy
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from backend.tests.test_stripe_history_reconciliation import history_api, sale_api, bind, sync, remote_invoice, snapshot, headers, API
from models.stripe_auto_posting import StripeAutoPostingJob as Job, StripeAutoPostingPolicy as Policy
from models.stripe_history_reconciliation import StripeHistoryBinding as Binding, StripeHistoryInvoiceReview as Review, StripeHistoryPosting as Posting
from models.payments import Payments
from models.employees import Employees
from models.commissions import CommissionEntry
from models.finance_profit_closes import MonthlyProfitClose
from services import stripe_auto_posting as auto
from services import stripe_history_reconciliation as history

AUTO = API + '/auto-posting'


async def prepared(history_api, monkeypatch):
    client, sessions, fake = history_api
    clock = [datetime(2026, 10, 21, 3, tzinfo=timezone.utc)]
    monkeypatch.setattr(auto, 'now', lambda: clock[0])
    monkeypatch.setattr(history, 'now', lambda: clock[0])
    bindings = []
    for identity in (100, 101, 102):
        binding = await bind(client, identity)
        await sync(client, binding)
        bindings.append(binding)
    before = await snapshot(sessions, excluding=('stripe_auto_posting_policies', 'stripe_auto_posting_jobs'))
    response = await client.post(AUTO + '/trials', headers=headers(1), json={'binding_ids': [b['id'] for b in bindings], 'owner_verified': True})
    assert response.status_code == 200, response.text
    assert response.json()['passed'], response.text
    assert before == await snapshot(sessions, excluding=('stripe_auto_posting_policies', 'stripe_auto_posting_jobs'))
    item = next(i for i in response.json()['items'] if i['binding_id'] == bindings[0]['id'])
    enable = await client.patch(AUTO + f"/bindings/{item['binding_id']}", headers=headers(1),
        json={'enabled': True, 'revision': item['revision'], 'owner_verified': True, 'owner_note': '首批验证通过开启正常新账单'})
    assert enable.status_code == 200, enable.text
    return client, sessions, fake, clock, bindings


def future_invoice(clock, identity=100, unique='next'):
    raw = remote_invoice(identity)
    created = clock[0] + timedelta(minutes=10)
    start = int(created.timestamp())
    end = int((created + timedelta(days=31)).timestamp())
    raw['id'] = 'in_' + unique
    raw['created'] = start
    raw['status_transitions']['paid_at'] = start + 10
    raw['lines']['data'][0]['period'] = {'start': start, 'end': end}
    intent = raw['payment_intent']
    intent['id'] = 'pi_' + unique
    charge = intent['latest_charge']
    charge.update(id='ch_' + unique, payment_intent=intent['id'], invoice=raw['id'])
    charge['balance_transaction'].update(id='txn_' + unique, source=charge['id'])
    clock[0] = created + timedelta(seconds=20)
    return raw


async def save(sessions, binding_id, raw):
    async with sessions() as db:
        binding = await db.get(Binding, binding_id)
        row = await history.save_invoice(db, binding, raw)
        await db.commit()
        return row.id


@pytest.mark.asyncio
async def test_owner_only_and_default_disabled_no_provider_or_financial_writes(history_api):
    client, sessions, fake = history_api
    for actor in (11, 12, 13, 14, 15, 16, 17):
        assert (await client.get(AUTO, headers=headers(actor))).status_code == 403
        assert (await client.post(AUTO + '/trials', headers=headers(actor), json={'binding_ids': [1,2,3], 'owner_verified': True})).status_code == 403
    before = await snapshot(sessions)
    data = await client.get(AUTO, headers=headers(1))
    assert data.status_code == 200 and data.json()['enabled_count'] == 0
    assert 'no-store' in data.headers['cache-control']
    assert fake.calls == []
    assert await auto.run_batch(sessions) == {'processed': 0, 'enabled': True}
    assert await snapshot(sessions) == before


@pytest.mark.asyncio
async def test_trial_3_services_no_financial_writes_history_excluded_and_one_new_post(history_api, monkeypatch):
    client, sessions, fake, clock, bindings = await prepared(history_api, monkeypatch)
    assert (await auto.run_batch(sessions))['processed'] == 0
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0
        assert await db.scalar(select(func.count()).select_from(Job)) == 0
    raw = future_invoice(clock)
    fake.invoice_rows[raw['id']] = raw
    review_id = await save(sessions, bindings[0]['id'], raw)
    assert (await auto.run_batch(sessions))['processed'] == 1
    assert (await auto.run_batch(sessions))['processed'] == 0
    async with sessions() as db:
        job, posting = await db.get(Job, review_id), await db.get(Posting, review_id)
        assert job.status == 'auto_posted', job.reason
        payment = await db.get(Payments, posting.payment_id)
        assert payment.amount_paid == 198 and payment.currency == 'USD'
        from services.deal_payment_sync import _calculate_stripe_fee
        original_fee = _calculate_stripe_fee(198, 'stripe', 'subscription_auto')
        assert payment.stripe_fee_amount == original_fee and payment.net_amount == 198 - original_fee
        assert payment.management_amount == 198 and payment.ads_recharge_amount == 0
        assert payment.transaction_reference == raw['id'] and '系统自动' in payment.recorded_by
        assert posting.action == 'auto_create_payment'
        assert await db.scalar(select(func.count()).select_from(Payments)) == 1
        assert await db.scalar(select(func.count()).select_from(CommissionEntry)) == 1
    await save(sessions, bindings[0]['id'], raw)
    await auto.run_batch(sessions)
    result = (await client.get(AUTO, headers=headers(1))).json()
    assert result['counts']['auto_posted'] == 1 and result['totals'] == [{'currency':'USD','amount':198.0,'count':1}]
    detail = (await client.get(API + f'/invoice-reviews/{review_id}', headers=headers(1))).json()['review']
    assert detail['auto_posting']['status'] == 'auto_posted'


@pytest.mark.asyncio
async def test_late_discovered_historical_invoice_never_auto_posted(history_api, monkeypatch):
    client, sessions, fake, clock, bindings = await prepared(history_api, monkeypatch)
    raw = copy.deepcopy(fake.invoice_rows['in_history100'])
    raw['id'] = 'in_old_discovered'
    review_id = await save(sessions, bindings[0]['id'], raw)
    await auto.run_batch(sessions)
    async with sessions() as db:
        assert (await db.get(Job, review_id)).reason_code == 'historical_excluded'
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['refund', 'out_of_band', 'price', 'tax', 'partial', 'owner_disabled', 'closed_month', 'duplicate_original', 'pause'])
async def test_abnormal_or_unauthorized_never_auto_posts(history_api, monkeypatch, mutation):
    client, sessions, fake, clock, bindings = await prepared(history_api, monkeypatch)
    raw = future_invoice(clock)
    if mutation == 'refund': raw['payment_intent']['latest_charge']['refunded'] = True
    if mutation == 'out_of_band': raw['paid_out_of_band'] = True
    if mutation == 'price': raw['lines']['data'][0]['price']['id'] = 'price_changed'
    if mutation == 'tax': raw['tax'] = 0; raw['total_tax_amounts'] = []
    if mutation == 'partial': raw['amount_paid'] -= 1
    fake.invoice_rows[raw['id']] = raw
    review_id = await save(sessions, bindings[0]['id'], raw)
    async with sessions() as db:
        if mutation == 'owner_disabled': (await db.get(Employees, 1)).status = 'inactive'
        if mutation == 'pause': (await db.get(Policy, bindings[0]['id'])).enabled = False
        if mutation == 'closed_month':
            db.add(MonthlyProfitClose(year_month=clock[0].strftime('%Y-%m'), status='locked', snapshot_json='{}', locked_by='User 1'))
        if mutation == 'duplicate_original':
            db.add(Payments(customer_id=100, customer_name='Synthetic History 100', amount_due=198, amount_paid=198, currency='USD',
                payment_date=clock[0], transaction_reference=raw['id'], product_name='专业套餐', user_id='1', engagement_id=100, business_line_id=1, product_id=1))
        await db.commit()
    await auto.run_batch(sessions)
    async with sessions() as db:
        job = await db.get(Job, review_id)
        assert job.status == 'manual_required', job.reason
        assert await db.scalar(select(func.count()).select_from(Payments)) == (1 if mutation == 'duplicate_original' else 0)
        assert await db.scalar(select(func.count()).select_from(Posting)) == 0


@pytest.mark.asyncio
async def test_retry_provider_failure_and_once_only_after_recovery(history_api, monkeypatch):
    client, sessions, fake, clock, bindings = await prepared(history_api, monkeypatch)
    raw = future_invoice(clock)
    fake.invoice_rows[raw['id']] = raw
    review_id = await save(sessions, bindings[0]['id'], raw)
    original = fake.invoice
    async def fails(identity):
        from fastapi import HTTPException
        raise HTTPException(503, 'temporary')
    monkeypatch.setattr(fake, 'invoice', fails)
    await auto.run_batch(sessions)
    async with sessions() as db:
        assert (await db.get(Job, review_id)).status == 'retry'
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0
    monkeypatch.setattr(fake, 'invoice', original)
    clock[0] += timedelta(minutes=5)
    await auto.run_batch(sessions)
    async with sessions() as db:
        assert (await db.get(Job, review_id)).status == 'auto_posted'
        assert await db.scalar(select(func.count()).select_from(Payments)) == 1


@pytest.mark.asyncio
async def test_unpaid_zero_cash_then_success_recovers_without_manual_or_duplicate(history_api, monkeypatch):
    client, sessions, fake, clock, bindings = await prepared(history_api, monkeypatch)
    paid = future_invoice(clock)
    unpaid = copy.deepcopy(paid)
    unpaid.update(status='open', paid=False, amount_paid=0, amount_remaining=unpaid['total'])
    unpaid['payment_intent'].update(status='requires_payment_method', amount_received=0)
    unpaid['payment_intent']['latest_charge'] = None
    unpaid['status_transitions']['paid_at'] = None
    fake.subscription_rows['sub_history100']['status'] = 'past_due'
    fake.invoice_rows[paid['id']] = unpaid
    review_id = await save(sessions, bindings[0]['id'], unpaid)
    await auto.run_batch(sessions)
    async with sessions() as db:
        assert (await db.get(Job, review_id)).status == 'retry'
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0
    fake.subscription_rows['sub_history100']['status'] = 'active'
    fake.invoice_rows[paid['id']] = paid
    await save(sessions, bindings[0]['id'], paid)
    clock[0] += timedelta(minutes=5)
    await auto.run_batch(sessions)
    async with sessions() as db:
        assert (await db.get(Job, review_id)).status == 'auto_posted'
        assert await db.scalar(select(func.count()).select_from(Payments)) == 1


@pytest.mark.asyncio
async def test_pause_reenable_excludes_pending_jobs_and_manual_processing_completes_them(history_api, monkeypatch):
    client, sessions, fake, clock, bindings = await prepared(history_api, monkeypatch)
    raw = future_invoice(clock)
    fake.invoice_rows[raw['id']] = raw
    review_id = await save(sessions, bindings[0]['id'], raw)
    info = (await client.get(AUTO, headers=headers(1))).json()
    policy = next(row for row in info['items'] if row['binding_id'] == bindings[0]['id'])
    response = await client.patch(AUTO + f"/bindings/{policy['binding_id']}", headers=headers(1),
        json={'enabled':False,'revision':policy['revision'],'owner_verified':True,'owner_note':'暂停自动改人工核对'})
    assert response.status_code == 200
    async with sessions() as db:
        assert (await db.get(Job, review_id)).status == 'manual_required'
    reenable = next(row for row in response.json()['items'] if row['binding_id'] == policy['binding_id'])
    response = await client.patch(AUTO + f"/bindings/{policy['binding_id']}", headers=headers(1),
        json={'enabled':True,'revision':reenable['revision'],'owner_verified':True,'owner_note':'重新开启只处理之后新账单'})
    assert response.status_code == 200
    await auto.run_batch(sessions)
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0
    detail = (await client.get(API + f'/invoice-reviews/{review_id}', headers=headers(1))).json()['review']
    response = await client.post(API + f'/invoice-reviews/{review_id}/confirm', headers=headers(1), json={
        'revision':detail['revision'],'action':'create_payment','owner_verified':True,'verification_note':'暂停后已人工核对实际扣款'})
    assert response.status_code == 200, response.text
    async with sessions() as db:
        assert (await db.get(Job, review_id)).status == 'manual_completed'
    assert (await client.get(AUTO, headers=headers(1))).json()['counts']['manual_required'] == 0


@pytest.mark.asyncio
async def test_posted_refund_flags_original_adjustment_and_preserves_income(history_api, monkeypatch):
    client, sessions, fake, clock, bindings = await prepared(history_api, monkeypatch)
    raw = future_invoice(clock)
    fake.invoice_rows[raw['id']] = raw
    review_id = await save(sessions, bindings[0]['id'], raw)
    await auto.run_batch(sessions)
    before = await snapshot(sessions, excluding=('stripe_auto_posting_policies','stripe_auto_posting_jobs'))
    raw['payment_intent']['latest_charge'].update(refunded=True, amount_refunded=100)
    await save(sessions, bindings[0]['id'], raw)
    await auto.run_batch(sessions)
    assert before == await snapshot(sessions, excluding=('stripe_auto_posting_policies','stripe_auto_posting_jobs'))
    result = (await client.get(AUTO, headers=headers(1))).json()
    assert result['counts']['auto_posted'] == 1 and result['counts']['manual_required'] == 1
    assert result['totals'][0]['amount'] == 198
    jobs = (await client.get(AUTO + '/jobs', headers=headers(1))).json()
    assert jobs['items'][0]['amount'] == 198


@pytest.mark.asyncio
async def test_stale_trial_and_conflicting_revision_rejected(history_api, monkeypatch):
    client, sessions, fake, clock, bindings = await prepared(history_api, monkeypatch)
    info = (await client.get(AUTO, headers=headers(1))).json()
    other = next(row for row in info['items'] if row['binding_id'] == bindings[1]['id'])
    wrong = await client.patch(AUTO + f"/bindings/{other['binding_id']}", headers=headers(1), json={
        'enabled':True,'revision':other['revision'] + 10,'owner_verified':True,'owner_note':'错误版本不能开启'})
    assert wrong.status_code == 409
    clock[0] += timedelta(hours=25)
    stale = await client.patch(AUTO + f"/bindings/{other['binding_id']}", headers=headers(1), json={
        'enabled':True,'revision':other['revision'],'owner_verified':True,'owner_note':'过期模拟不能开启'})
    assert stale.status_code == 409
    info = (await client.get(AUTO, headers=headers(1))).json()
    assert next(row for row in info['items'] if row['binding_id'] == other['binding_id'])['trial']['passed'] is False


@pytest.mark.asyncio
async def test_lease_expiry_and_two_claims_cannot_duplicate_post(history_api, monkeypatch):
    client, sessions, fake, clock, bindings = await prepared(history_api, monkeypatch)
    raw = future_invoice(clock)
    fake.invoice_rows[raw['id']] = raw
    review_id = await save(sessions, bindings[0]['id'], raw)
    claim = await auto.claim_job(sessions)
    assert claim and await auto.claim_job(sessions) is None
    clock[0] += timedelta(seconds=auto.LEASE_SECONDS + 1)
    replacement = await auto.claim_job(sessions)
    assert replacement['token'] != claim['token']
    await auto.process_job(sessions, claim)
    await auto.process_job(sessions, replacement)
    await auto.process_job(sessions, replacement)
    async with sessions() as db:
        assert (await db.get(Job, review_id)).status == 'auto_posted'
        assert await db.scalar(select(func.count()).select_from(Payments)) == 1
        assert await db.scalar(select(func.count()).select_from(Posting)) == 1


@pytest.mark.asyncio
async def test_worker_disabled_does_not_read_provider_or_write(history_api, monkeypatch):
    client, sessions, fake, clock, bindings = await prepared(history_api, monkeypatch)
    raw = future_invoice(clock)
    await save(sessions, bindings[0]['id'], raw)
    monkeypatch.setenv('STRIPE_AUTO_POSTING_ENABLED','false')
    before = await snapshot(sessions)
    calls = list(fake.calls)
    assert await auto.run_batch(sessions) == {'processed':0,'enabled':False}
    assert fake.calls == calls and await snapshot(sessions) == before
    assert auto.start_auto_posting() is None


@pytest.mark.asyncio
async def test_changed_existing_commission_basis_stops_auto_without_reassigning(history_api, monkeypatch):
    client, sessions, fake, clock, bindings = await prepared(history_api, monkeypatch)
    from models.commissions import CommissionAgreement
    raw = future_invoice(clock)
    fake.invoice_rows[raw['id']] = raw
    review_id = await save(sessions, bindings[0]['id'], raw)
    async with sessions() as db:
        (await db.get(CommissionAgreement, 100)).renewal_rate = .2
        await db.commit()
    before = await snapshot(sessions, excluding=('stripe_auto_posting_policies','stripe_auto_posting_jobs'))
    await auto.run_batch(sessions)
    assert before == await snapshot(sessions, excluding=('stripe_auto_posting_policies','stripe_auto_posting_jobs'))
    async with sessions() as db:
        assert (await db.get(Job, review_id)).status == 'manual_required'
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0


@pytest.mark.asyncio
async def test_commission_failure_rolls_back_payment_posting_and_remains_retryable(history_api, monkeypatch):
    client, sessions, fake, clock, bindings = await prepared(history_api, monkeypatch)
    from services import commissions
    raw = future_invoice(clock)
    fake.invoice_rows[raw['id']] = raw
    review_id = await save(sessions, bindings[0]['id'], raw)
    original = commissions.sync_payment_commission
    async def fail_after_insert(db, payment):
        raise RuntimeError('controlled failure after original Payments flush')
    monkeypatch.setattr(commissions, 'sync_payment_commission', fail_after_insert)
    await auto.run_batch(sessions)
    async with sessions() as db:
        assert (await db.get(Job, review_id)).status == 'retry'
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0
        assert await db.scalar(select(func.count()).select_from(Posting)) == 0
        assert await db.scalar(select(func.count()).select_from(CommissionEntry)) == 0
    monkeypatch.setattr(commissions, 'sync_payment_commission', original)
    clock[0] += timedelta(minutes=5)
    await auto.run_batch(sessions)
    async with sessions() as db:
        assert (await db.get(Job, review_id)).status == 'auto_posted'
        assert await db.scalar(select(func.count()).select_from(Payments)) == 1


def test_migration_only_adds_empty_auto_tables_preserving_all_old_objects():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    engine = create_engine('sqlite://')
    file = Path(__file__).resolve().parents[1] / 'alembic/versions/f3c7d1a9b456_stripe_auto_posting.py'
    spec = importlib.util.spec_from_file_location('isolated_auto_migration', file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE payments(id INTEGER PRIMARY KEY, amount_paid FLOAT)'))
        connection.execute(text('INSERT INTO payments VALUES (1,198)'))
        connection.execute(text('CREATE TABLE stripe_history_bindings(id INTEGER PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE stripe_history_invoice_reviews(id INTEGER PRIMARY KEY)'))
        old_objects = connection.execute(text('SELECT type,name,sql FROM sqlite_master ORDER BY name')).all()
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        assert connection.execute(text('SELECT * FROM payments')).all() == [(1,198)]
        new_names = {'stripe_auto_posting_policies','stripe_auto_posting_jobs','ix_stripe_auto_posting_jobs_binding_id','ix_stripe_auto_posting_jobs_status'}
        assert [row for row in connection.execute(text('SELECT type,name,sql FROM sqlite_master ORDER BY name')).all() if row[1] not in new_names] == old_objects
        for table in ('stripe_auto_posting_policies','stripe_auto_posting_jobs'):
            assert connection.execute(text('SELECT count(*) FROM '+table)).scalar() == 0
        assert [col['name'] for col in inspect(connection).get_columns('stripe_auto_posting_policies')] == list(Policy.__table__.columns.keys())
        assert [col['name'] for col in inspect(connection).get_columns('stripe_auto_posting_jobs')] == list(Job.__table__.columns.keys())


@pytest.mark.asyncio
async def test_completed_authorization_evidence_is_immutable_after_reauthorizing(history_api, monkeypatch):
    client, sessions, fake, clock, bindings = await prepared(history_api, monkeypatch)
    raw = future_invoice(clock)
    fake.invoice_rows[raw['id']] = raw
    review_id = await save(sessions, bindings[0]['id'], raw)
    await auto.run_batch(sessions)
    original = (await client.get(API + f'/invoice-reviews/{review_id}', headers=headers(1))).json()['review']['auto_posting']
    async with sessions() as db:
        policy = await db.get(Policy, bindings[0]['id'])
        policy.authorized_by_name = 'Changed Owner Name'
        policy.effective_from = clock[0] + timedelta(days=5)
        policy.revision += 10
        await db.commit()
    updated = (await client.get(API + f'/invoice-reviews/{review_id}', headers=headers(1))).json()['review']['auto_posting']
    assert updated['authorized_by_name'] == original['authorized_by_name'] == 'User 1'
    assert updated['effective_from'] == original['effective_from']


@pytest.mark.asyncio
async def test_queued_jobs_excluded_from_manual_pending_on_both_overviews(history_api, monkeypatch):
    client, sessions, fake, clock, bindings = await prepared(history_api, monkeypatch)
    before = (await client.get(API + '/overview', headers=headers(1))).json()['counts']['manual_pending']
    raw = future_invoice(clock)
    await save(sessions, bindings[0]['id'], raw)
    overview = (await client.get(API + '/overview', headers=headers(1))).json()
    reviews = (await client.get(API + '/invoice-reviews', headers=headers(1))).json()
    reminders = (await client.get(API + '/reminders', headers=headers(1))).json()
    assert overview['counts']['manual_pending'] == reviews['counts']['manual_pending'] == reminders['manual_pending'] == before
