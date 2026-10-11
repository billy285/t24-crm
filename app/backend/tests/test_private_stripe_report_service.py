"""Synthetic cash reconciliation and real owner/session/cache boundaries."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
from types import SimpleNamespace

from fastapi import HTTPException, Request
import pytest
import pytest_asyncio
from sqlalchemy import select

from dependencies.private_workspace import revalidate_private_owner
from models.private_workspace import PrivateConnection, PrivateStripeReport
from schemas.private_workspace import PrivateStripeReportRequest
from routers import private_workspace as routes
from services import emp_auth
from services import private_stripe_report_provider as provider
from services import private_stripe_report_service as service
from services import private_workspace as core
from services import private_workspace_providers as providers
from test_private_workspace_app import private_app
from test_private_workspace_core import STRIPE_ACCOUNT, headers, workspace


NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
KEY = 'rk_test_syntheticReport1234567890'
URL = '/api/v1/private-workspace/stripe/report'


def event(identity, created, amount, *, currency='USD', fee=0, kind='payment',
          classification='one_time', eligible=True, **changes):
    return {'id': identity, 'created': created, 'amount': amount, 'fee': fee,
            'net': amount - fee, 'kind': kind, 'type': 'charge' if kind == 'payment' else kind,
            'currency': currency, 'classification': classification,
            'classification_label': '订阅账单关联' if classification == 'subscription' else '直接收款',
            'income_eligible': eligible, 'source_verified': eligible is not None,
            'source_id': 'ch_' + identity.removeprefix('txn_'),
            'source_status': 'succeeded', 'customer_label': 'Sensitive private merchant',
            'source_url': 'https://dashboard.stripe.com/test/payments/ch_Synthetic', **changes}


def batch(transactions=(), *, observed_at=None, **changes):
    return {'identity': {'stripe_account_id': STRIPE_ACCOUNT, 'mode': 'test',
                         'account_label': 'Synthetic private Stripe'},
            'observed_at': observed_at or NOW.isoformat(),
            'transactions': list(transactions), 'subscriptions': [], 'attention': [],
            'payouts': [], 'disputes': [],
            'balances': [{'currency': 'USD', 'available_minor': 700, 'pending_minor': 20}],
            'coverage': {'amounts_complete': True, 'classifications_complete': True,
                         'subscriptions_complete': True, 'invoices_attention_complete': True,
                         'payouts_complete': True, 'disputes_complete': True,
                         'balance_transactions': {'complete': True},
                         'warnings': []}, **changes}


def current_event(identity='txn_Current', amount=1200, **changes):
    window = service.resolve_period(now=NOW)
    return event(identity, window['start'] + 3600, amount, **changes)


async def put_connection(owner_id='1', *, generation=1, credentials=None):
    sessions = await core.private_session_factory()
    async with sessions() as db:
        connection = await core.connection_for(db, owner_id, 'stripe', create=True)
        connection.status = 'connected'
        connection.generation = generation
        connection.encrypted_credentials = core.encrypt_credentials(credentials or {
            'api_key': KEY, 'stripe_account_id': STRIPE_ACCOUNT, 'mode': 'test'})
        connection.metadata_json = {'stripe_account_id': STRIPE_ACCOUNT, 'mode': 'test'}
        await db.commit()
        return connection.id


def request_for(app, auth_headers):
    return Request({'type': 'http', 'method': 'POST', 'path': URL,
                    'headers': [(name.lower().encode(), value.encode()) for name, value in auth_headers.items()],
                    'app': app})


@pytest_asyncio.fixture
async def reports(workspace, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC')
    await put_connection()
    calls = []
    control = SimpleNamespace(hook=None, result=None)

    async def fetch(credentials, metadata, start, end):
        assert credentials == {'api_key': KEY, 'stripe_account_id': STRIPE_ACCOUNT, 'mode': 'test'}
        assert metadata == {'stripe_account_id': STRIPE_ACCOUNT, 'mode': 'test'}
        calls.append((start, end))
        if control.hook:
            await control.hook()
        return deepcopy(control.result if control.result is not None else batch(
            [current_event()], observed_at=(NOW + timedelta(seconds=len(calls))).isoformat()))

    monkeypatch.setattr(provider, 'fetch_report', fetch)
    app = workspace.client._transport.app

    async def get(payload=None, *, now=NOW, owner_id='1', auth_headers=None):
        req = request_for(app, auth_headers or headers(int(owner_id)))
        sessions = await core.private_session_factory()
        async with sessions() as db:
            return await service.report(db, owner_id, payload or PrivateStripeReportRequest(), now=now,
                owner_validator=lambda: revalidate_private_owner(req, owner_id))

    yield SimpleNamespace(value=workspace, calls=calls, control=control, get=get)


@pytest_asyncio.fixture
async def report_app(private_app, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_ACCOUNT_ID', STRIPE_ACCOUNT)
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_MODE', 'test')
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC')
    await put_connection()
    calls = []
    control = SimpleNamespace(hook=None, result=None)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(service, 'datetime', FrozenDateTime)

    async def fetch(*args):
        calls.append(args)
        if control.hook:
            await control.hook()
        return deepcopy(control.result if control.result is not None else batch([current_event()]))

    monkeypatch.setattr(provider, 'fetch_report', fetch)
    yield SimpleNamespace(value=private_app, control=control, calls=calls)


def currencies(report):
    return {row['currency']: row for row in report['currencies']}


def test_integer_reconciliation_separates_currencies_refunds_and_balance_movements(monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC')
    window = service.resolve_period(now=NOW)
    current = window['start'] + 3600
    values = [event('txn_Previous', window['previous_start'] + 1, 1000),
              event('txn_Sub', current, 2000, fee=88, classification='subscription'),
              event('txn_Single', current, 1200, fee=60),
              event('txn_Refund', current, -500, kind='refund', fee=-15),
              event('txn_Payout', current, -1000, kind='other_balance_activity', eligible=False),
              event('txn_Dispute', current, -700, fee=150, kind='other_balance_activity', eligible=False),
              event('txn_FeeReversal', current, 0, fee=-5, kind='other_balance_activity', eligible=False),
              event('txn_Eur', current, 123456789012345, currency='EUR', fee=13),
              event('txn_Jpy', current, 17, currency='JPY')]
    result = service.build_report(batch(values), window)
    rows = currencies(result)
    assert rows['USD']['gross_minor'] == 3200
    assert rows['USD']['subscription_minor'] == 2000 and rows['USD']['one_time_minor'] == 1200
    assert rows['USD']['refunds_minor'] == 500 and rows['USD']['net_receipts_minor'] == 2700
    assert rows['USD']['fees_minor'] == 278 and rows['USD']['count'] == 2
    assert rows['USD']['comparison'] == {'gross_minor': 1000, 'change_pct': 220.0, 'complete': True}
    assert rows['EUR']['gross_minor'] == 123456789012345 and rows['EUR']['fees_minor'] == 13
    assert rows['JPY']['gross_minor'] == 17 and 'JPY 17' in rows['JPY']['summary'][0]
    assert sum(day['subscription_minor'] for day in rows['USD']['trend']) == 2000
    assert sum(day['one_time_minor'] for day in rows['USD']['trend']) == 1200
    assert next(day for day in rows['USD']['trend'] if day['date'] == '2026-10-01')['one_time_minor'] == 1200
    assert {row['kind'] for row in result['records'] if row['id'] in {'txn_Payout', 'txn_Dispute'}} == {'adjustment'}


def test_standalone_stripe_fees_and_positive_credits_reconcile_without_changing_income(monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC')
    window = service.resolve_period(now=NOW)
    created = window['start'] + 3600
    values = [event('txn_Paid', created, 1000, fee=100),
              event('txn_Refund', created, -200, fee=-10, kind='refund'),
              event('txn_ServiceFee', created, -50, fee=3, kind='other_balance_activity',
                    eligible=False, type='stripe_fee'),
              event('txn_FeeCredit', created, 20, kind='other_balance_activity',
                    eligible=False, type='stripe_fee'),
              event('txn_FxFee', created, -30, kind='other_balance_activity',
                    eligible=False, type='stripe_fx_fee'),
              event('txn_Payout', created, -10000, kind='other_balance_activity', eligible=False, type='payout'),
              event('txn_BankTopup', created, 7000, kind='other_balance_activity', eligible=False, type='topup')]
    result = service.build_report(batch(values), window)
    usd = currencies(result)['USD']
    assert usd['gross_minor'] == usd['one_time_minor'] == 1000 and usd['count'] == 1
    assert usd['refunds_minor'] == 200 and usd['net_receipts_minor'] == 800
    assert usd['fees_minor'] == 153  # 100 - 10 + (50 + 3) - 20 + 30.
    adjustments = {row['id']: row for row in result['records'] if row['kind'] == 'adjustment'}
    assert adjustments['txn_FeeCredit']['amount_minor'] == 20
    assert adjustments['txn_ServiceFee']['amount_minor'] == -50
    assert set(adjustments) == {'txn_ServiceFee', 'txn_FeeCredit', 'txn_FxFee', 'txn_Payout', 'txn_BankTopup'}


@pytest.mark.parametrize('kind,amount,status,eligible', [
    ('payment', 900, 'failed', False), ('payment', 900, 'pending', False),
    ('payment', 900, 'succeeded', None), ('refund', -300, 'pending', False),
    ('refund', -300, 'failed', False), ('refund', -300, 'succeeded', None),
])
def test_only_verified_eligible_activity_changes_successful_receipts(monkeypatch, kind, amount, status, eligible):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC')
    source = batch([current_event(amount=amount, kind=kind, eligible=eligible, source_status=status)])
    if eligible is None:
        source['coverage'].update(amounts_complete=False, classifications_complete=False)
    result = service.build_report(source, service.resolve_period(now=NOW))
    usd = currencies(result)['USD']
    assert usd['gross_minor'] == usd['refunds_minor'] == usd['count'] == 0
    assert result['records'][0]['status'] == status
    if eligible is None:
        assert result['state'] == 'partial' and not result['coverage']['amounts_complete']


def test_unclassified_verified_income_is_retained_without_claiming_complete_classification(monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC')
    source = batch([current_event(classification='unclassified')])
    source['coverage'].update(classifications_complete=False)
    result = service.build_report(source, service.resolve_period(now=NOW))
    usd = currencies(result)['USD']
    assert usd['gross_minor'] == usd['unclassified_minor'] == 1200
    assert usd['subscription_minor'] == usd['one_time_minor'] == 0
    assert result['state'] == 'partial' and result['coverage']['reasons']
    assert any('待确认' in sentence for sentence in usd['summary'])


@pytest.mark.parametrize('known_category,empty_label', [('subscription', '单次收款'),
                                                     ('one_time', '订阅相关收款')])
def test_incomplete_classification_summary_never_confirms_missing_category_as_zero(monkeypatch, known_category, empty_label):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC')
    source = batch([current_event('txn_Known', 1200, classification=known_category),
                    current_event('txn_Unknown', 800, classification='unclassified')])
    source['coverage']['classifications_complete'] = False
    result = service.build_report(source, service.resolve_period(now=NOW))
    usd = currencies(result)['USD']
    summary = ''.join(usd['summary'])
    assert usd[known_category + '_minor'] == 1200 and usd['unclassified_minor'] == 800
    assert usd['gross_minor'] == 2000 and result['coverage']['amounts_complete']
    assert 'USD 12.00' in summary and '待确认' in summary
    assert 'USD 0.00' not in summary, f'{empty_label} cannot be confirmed zero while association is incomplete'


@pytest.mark.parametrize('kind,amount,eligible,status', [
    ('payment', 900, None, 'succeeded'), ('payment', 900, False, 'failed'),
    ('other_balance_activity', -50, False, 'stripe_fee'), ('refund', -300, True, 'succeeded'),
])
def test_incomplete_amount_summary_with_no_verified_receipts_says_total_pending(monkeypatch, kind, amount, eligible, status):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC')
    source = batch([current_event(kind=kind, amount=amount, eligible=eligible, source_status=status)])
    source['coverage'].update(amounts_complete=False, classifications_complete=False)
    result = service.build_report(source, service.resolve_period(now=NOW))
    usd = currencies(result)['USD']
    assert usd['gross_minor'] == usd['count'] == 0
    assert '待确认' in usd['summary'][0]
    assert 'USD 0.00' not in ''.join(usd['summary'])
    assert result['state'] == 'partial' and usd['comparison']['gross_minor'] is None


def test_complete_empty_cash_history_can_confirm_zero_summary(monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC')
    result = service.build_report(batch([]), service.resolve_period(now=NOW))
    usd = currencies(result)['USD']
    assert result['coverage']['amounts_complete'] and result['coverage']['classifications_complete']
    assert usd['gross_minor'] == usd['count'] == 0 and 'USD 0.00' in usd['summary'][0]


def test_complete_classification_can_confirm_empty_category_zero(monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC')
    result = service.build_report(batch([current_event(classification='subscription')]), service.resolve_period(now=NOW))
    usd = currencies(result)['USD']
    assert result['coverage']['classifications_complete']
    assert any('单次收款 USD 0.00' in sentence for sentence in usd['summary'])


def test_partial_primary_history_does_not_claim_growth_or_full_zero(monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC')
    source = batch([current_event()])
    source['coverage'].update(amounts_complete=False, classifications_complete=False,
        warnings=[{'message': '已达到读取上限'}])
    result = service.build_report(source, service.resolve_period(now=NOW))
    usd = currencies(result)['USD']
    assert result['state'] == 'partial' and result['coverage']['reasons'] == ['已达到读取上限']
    assert usd['comparison'] == {'gross_minor': None, 'change_pct': None, 'complete': False}
    assert '已读取范围内' in usd['summary'][0]
    assert currencies(service.build_report({**source, 'transactions': []}, service.resolve_period(now=NOW))) == {}


def test_provider_inspection_and_subscription_contract_preserves_status_without_inventing_income(monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC')
    window = service.resolve_period(now=NOW)
    observed = window['start'] + 500
    payout = {'id': 'po_Synthetic', 'kind': 'payout', 'created': observed, 'status': 'failed',
              'amount_minor': 7000, 'currency': 'USD', 'arrival_date': observed + 86400,
              'source_url': 'https://dashboard.stripe.com/test/payouts/po_Synthetic'}
    dispute = {'id': 'dp_Synthetic', 'kind': 'dispute', 'created': observed, 'status': 'needs_response',
               'amount_minor': 5000, 'currency': 'USD', 'due_date': observed + 2 * 86400,
               'source_url': 'https://dashboard.stripe.com/test/disputes/dp_Synthetic'}
    subscription = {'id': 'sub_Synthetic', 'status': 'past_due', 'currency': 'USD',
                    'customer_label': 'Synthetic subscriber', 'current_period_end': observed + 86400,
                    'cancel_at_period_end': False, 'items': [{'unit_amount_minor': 90000}],
                    'source_url': 'https://dashboard.stripe.com/test/subscriptions/sub_Synthetic'}
    result = service.build_report(batch([], payouts=[payout], disputes=[dispute],
        subscriptions=[subscription], attention=[payout, dispute, {**subscription, 'kind': 'subscription'}]), window)
    assert currencies(result)['USD']['gross_minor'] == currencies(result)['USD']['refunds_minor'] == 0
    records = {row['id']: row for row in result['records']}
    assert records['po_Synthetic']['kind'] == 'payout' and records['po_Synthetic']['status'] == 'failed'
    assert records['dp_Synthetic']['kind'] == 'dispute' and records['dp_Synthetic']['status'] == 'needs_response'
    assert all(row['category'] is None for row in records.values())
    assert result['subscriptions'][0]['amount_minor'] is None and result['subscriptions'][0]['next_payment_at'] is None
    attention = {row['id']: row for row in result['attention']}
    assert len(attention) == len(result['attention']) == 3
    assert '提现' in attention['po_Synthetic']['reason'] and '争议' in attention['dp_Synthetic']['reason']
    assert '订阅' in attention['sub_Synthetic']['reason']


@pytest.mark.parametrize('missing', ['payouts_complete', 'disputes_complete',
                                   'subscriptions_complete', 'invoices_attention_complete'])
def test_optional_source_gaps_cannot_claim_complete_funds_or_attention(monkeypatch, missing):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC')
    source = batch([current_event()])
    source['coverage'][missing] = False
    source['coverage']['warnings'] = [{'message': '部分信息读取未完成'}]
    result = service.build_report(source, service.resolve_period(now=NOW))
    assert result['coverage']['amounts_complete'] and result['coverage']['classifications_complete']
    assert currencies(result)['USD']['gross_minor'] == 1200
    assert result['coverage']['attention_complete'] is False
    assert result['coverage']['funds_complete'] is (missing not in {'payouts_complete', 'disputes_complete'})


@pytest.mark.parametrize('changes', [
    {'amount': True}, {'fee': 1.5}, {'net': '1200'}, {'amount': 9_000_000_000_000_001},
    {'created': True}, {'currency': 'USＤ'}, {'currency': 'US'}, {'classification': 'guessed'},
    {'net': 1199}, {'amount': -1, 'net': -1},
])
def test_invalid_financial_contract_is_rejected(monkeypatch, changes):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC')
    with pytest.raises((ValueError, TypeError)):
        service.build_report(batch([{**current_event(), **changes}]), service.resolve_period(now=NOW))


def test_duplicate_transactions_and_aggregate_overflow_fail_closed(monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC')
    window = service.resolve_period(now=NOW)
    with pytest.raises(ValueError, match='duplicate'):
        service.build_report(batch([current_event(), current_event()]), window)
    with pytest.raises(ValueError):
        service.build_report(batch([current_event('txn_Huge1', 6_000_000_000_000_000),
                                    current_event('txn_Huge2', 6_000_000_000_000_000)]), window)


def test_current_interval_excludes_end_and_comparison_gap(monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC')
    window = service.resolve_period(now=NOW)
    values = [event('txn_Start', window['start'], 100), event('txn_End', window['end'], 900),
              event('txn_Prior', window['previous_start'], 200),
              event('txn_PriorEnd', window['previous_end'], 800)]
    result = service.build_report(batch(values), window)
    usd = currencies(result)['USD']
    assert usd['gross_minor'] == 100 and usd['comparison']['gross_minor'] == 200
    assert [row['id'] for row in result['records']] == ['txn_Start']


@pytest.mark.parametrize('day,utc_start,hours', [
    ('2026-03-08', datetime(2026, 3, 8, 5, tzinfo=timezone.utc), 23),
    ('2026-11-01', datetime(2026, 11, 1, 4, tzinfo=timezone.utc), 25),
])
def test_custom_day_uses_local_midnight_and_dst_end_exclusive(monkeypatch, day, utc_start, hours):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'America/New_York')
    result = service.resolve_period('custom', day, day, now=datetime(2026, 12, 2, tzinfo=timezone.utc))
    assert result['start'] == int(utc_start.timestamp())
    assert result['end'] - result['start'] == hours * 3600
    assert result['previous_end'] == result['start'] and result['timezone'] == 'America/New_York'


@pytest.mark.parametrize('period,start,end', [
    ('custom', '2026-10-13', '2026-10-13'), ('custom', '2026-10-02', '2026-10-01'),
    ('custom', '2025-01-01', '2026-01-02'), ('custom', '2009-12-31', '2010-01-01'),
    ('custom', '20261001', '2026-10-01'), ('custom', None, '2026-10-01'),
    ('month', '2026-10-01', None), ('invalid', None, None),
])
def test_invalid_date_ranges_rejected_before_provider(monkeypatch, period, start, end):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC')
    with pytest.raises(HTTPException) as caught:
        service.resolve_period(period, start, end, now=NOW)
    assert caught.value.status_code == 422


def test_366_days_and_preset_elapsed_comparison_are_explicit(monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'UTC')
    result = service.resolve_period('custom', '2024-01-01', '2024-12-31', now=NOW)
    assert result['end'] - result['start'] == 366 * 86400
    for preset, month in [('month', 10), ('quarter', 10), ('year', 1)]:
        value = service.resolve_period(preset, now=NOW)
        assert value['start'] == int(datetime(2026, month, 1, tzinfo=timezone.utc).timestamp())
        assert value['end'] == int(NOW.timestamp())
        assert value['previous_end'] - value['previous_start'] == value['end'] - value['start']


@pytest.mark.asyncio
async def test_cache_is_encrypted_persistent_and_does_not_mutate_crm(reports):
    value = reports.value
    business_before = hashlib.sha256(value.business_path.read_bytes()).hexdigest()
    first = await reports.get()
    await core.close_private_workspace_storage()
    second = await reports.get()
    assert first == second and len(reports.calls) == 1
    with sqlite3.connect(value.private_path) as db:
        rows = db.execute('SELECT owner_id,encrypted_report FROM private_stripe_reports').fetchall()
        assert len(rows) == 1 and rows[0][0] == '1'
        assert 'Sensitive private merchant' not in rows[0][1] and KEY not in rows[0][1]
        decoded = json.loads(core._cipher().decrypt(rows[0][1].encode()))
        assert decoded['report'] == first and decoded['cache_context']['owner_id'] == '1'
    assert KEY not in json.dumps(first) and 'encrypted_report' not in json.dumps(first)
    assert hashlib.sha256(value.business_path.read_bytes()).hexdigest() == business_before
    assert all(statement.lstrip().upper().startswith('SELECT') for statement in value.statements)


@pytest.mark.asyncio
async def test_cache_expiration_refresh_throttle_and_date_range_isolation(reports):
    first = await reports.get()
    assert await reports.get(PrivateStripeReportRequest(refresh=True), now=NOW + timedelta(seconds=30)) == first
    assert len(reports.calls) == 1
    refreshed = await reports.get(PrivateStripeReportRequest(refresh=True), now=NOW + timedelta(seconds=61))
    assert refreshed['snapshot_id'] != first['snapshot_id'] and len(reports.calls) == 2
    await reports.get(now=NOW + timedelta(seconds=662))
    assert len(reports.calls) == 3
    await reports.get(PrivateStripeReportRequest(period='custom', start_date='2026-10-01', end_date='2026-10-02'))
    assert len(reports.calls) == 4


@pytest.mark.asyncio
async def test_owner_generation_credentials_and_timezone_cannot_reuse_cache(reports, monkeypatch):
    await reports.get()
    monkeypatch.setenv('PRIVATE_WORKSPACE_OWNER_IDS', '1,2')
    await put_connection('2')
    await reports.get(owner_id='2')
    assert len(reports.calls) == 2
    await put_connection(generation=2)
    await reports.get()
    assert len(reports.calls) == 3
    # Re-encryption changes the credential fingerprint even if an operator forgot to increment generation.
    await put_connection(generation=2)
    await reports.get()
    assert len(reports.calls) == 4
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', 'America/New_York')
    await reports.get()
    assert len(reports.calls) == 5


@pytest.mark.asyncio
async def test_corrupted_or_cross_context_ciphertext_is_never_disclosed(reports):
    await reports.get()
    sessions = await core.private_session_factory()
    async with sessions() as db:
        cached = (await db.execute(select(PrivateStripeReport))).scalar_one()
        decoded = json.loads(core._cipher().decrypt(cached.encrypted_report.encode()))
        decoded['cache_context']['owner_id'] = '2'
        cached.encrypted_report = core._cipher().encrypt(json.dumps(decoded).encode()).decode()
        await db.commit()
    with pytest.raises(HTTPException) as caught:
        await reports.get()
    assert caught.value.status_code == 503 and len(reports.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['disconnect', 'generation', 'credential', 'account', 'mode'])
async def test_connection_change_during_provider_wait_cannot_save_or_return_stale_report(reports, monkeypatch, change):
    entered, release = asyncio.Event(), asyncio.Event()
    async def held():
        entered.set()
        await release.wait()
    reports.control.hook = held
    running = asyncio.create_task(reports.get())
    await asyncio.wait_for(entered.wait(), 3)
    try:
        if change in {'account', 'mode'}:
            monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_ACCOUNT_ID' if change == 'account' else 'PRIVATE_WORKSPACE_STRIPE_MODE',
                'acct_changedSynthetic123456' if change == 'account' else 'live')
        else:
            sessions = await core.private_session_factory()
            async with sessions() as db:
                connection = await core.connection_for(db, '1', 'stripe')
                if change == 'disconnect':
                    connection.status = 'disconnected'
                    connection.encrypted_credentials = None
                    connection.generation += 1
                elif change == 'generation':
                    connection.generation += 1
                else:
                    connection.encrypted_credentials = core.encrypt_credentials({
                        'api_key': KEY, 'stripe_account_id': STRIPE_ACCOUNT, 'mode': 'test'})
                await db.commit()
        business_before = hashlib.sha256(reports.value.business_path.read_bytes()).hexdigest()
        release.set()
        with pytest.raises(HTTPException) as caught:
            await asyncio.wait_for(running, 3)
        assert caught.value.status_code in {409, 503}
        with sqlite3.connect(reports.value.private_path) as db:
            assert db.execute('SELECT count(*) FROM private_stripe_reports').fetchone() == (0,)
        assert hashlib.sha256(reports.value.business_path.read_bytes()).hexdigest() == business_before
    finally:
        release.set()
        if not running.done():
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['logout', 'password', 'role', 'inactive', 'allowlist'])
async def test_real_owner_revocation_after_network_blocks_cache_and_no_store_response(report_app, monkeypatch, change):
    value = report_app.value
    entered, release = asyncio.Event(), asyncio.Event()
    async def held():
        entered.set()
        await release.wait()
    report_app.control.hook = held
    running = asyncio.create_task(value.client.post(URL, headers=value.headers(), json={'period': 'month'}))
    await asyncio.wait_for(entered.wait(), 3)
    try:
        if change == 'allowlist':
            monkeypatch.setenv('PRIVATE_WORKSPACE_OWNER_IDS', '2')
        else:
            statement = {'logout': 'UPDATE employee_auth_sessions SET revoked_at=1 WHERE employee_id=1',
                         'password': "UPDATE employees SET password='changed-synthetic-password' WHERE id=1",
                         'role': "UPDATE employees SET role='sales' WHERE id=1",
                         'inactive': "UPDATE employees SET status='inactive' WHERE id=1"}[change]
            with sqlite3.connect(value.business_path) as db:
                db.execute(statement)
        business_before = hashlib.sha256(value.business_path.read_bytes()).hexdigest()
        release.set()
        response = await asyncio.wait_for(running, 3)
        assert response.status_code == 403 and response.headers['cache-control'] == 'no-store'
        assert 'currencies' not in response.json() and 'Sensitive private merchant' not in response.text
        with sqlite3.connect(value.private_path) as db:
            assert db.execute('SELECT count(*) FROM private_stripe_reports').fetchone() == (0,)
        assert hashlib.sha256(value.business_path.read_bytes()).hexdigest() == business_before
    finally:
        release.set()
        if not running.done():
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
async def test_cached_report_still_requires_current_real_session(report_app):
    value = report_app.value
    assert (await value.client.post(URL, headers=value.headers(), json={})).status_code == 200
    with sqlite3.connect(value.business_path) as db:
        db.execute('UPDATE employee_auth_sessions SET revoked_at=1 WHERE employee_id=1')
    response = await value.client.post(URL, headers=value.headers(), json={})
    assert response.status_code == 401 and response.headers['cache-control'] == 'no-store'
    assert len(report_app.calls) == 1 and 'currencies' not in response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary,change', [('cache', 'logout'), ('cache', 'generation'),
                                          ('commit', 'logout'), ('commit', 'generation'),
                                          ('response', 'logout')])
async def test_final_cache_and_commit_boundaries_recheck_owner_and_connection(report_app, monkeypatch, boundary, change):
    value = report_app.value
    if boundary == 'cache':
        assert (await value.client.post(URL, headers=value.headers(), json={})).status_code == 200
    entered, release = asyncio.Event(), asyncio.Event()
    checks = 0
    original = routes.revalidate_private_owner
    hold_on = {'cache': 2, 'commit': 3, 'response': 4}[boundary]

    async def held_validator(request, owner_id):
        nonlocal checks
        checks += 1
        if checks == hold_on:
            entered.set()
            await release.wait()
        return await original(request, owner_id)

    monkeypatch.setattr(routes, 'revalidate_private_owner', held_validator)
    running = asyncio.create_task(value.client.post(URL, headers=value.headers(), json={}))
    await asyncio.wait_for(entered.wait(), 3)
    try:
        if change == 'logout':
            with sqlite3.connect(value.business_path) as db:
                db.execute('UPDATE employee_auth_sessions SET revoked_at=1 WHERE employee_id=1')
        else:
            sessions = await core.private_session_factory()
            async with sessions() as db:
                connection = await core.connection_for(db, '1', 'stripe')
                connection.generation += 1
                await db.commit()
        before = hashlib.sha256(value.business_path.read_bytes()).hexdigest()
        release.set()
        response = await asyncio.wait_for(running, 3)
        assert response.status_code == (403 if change == 'logout' else 409)
        assert response.headers['cache-control'] == 'no-store' and 'currencies' not in response.json()
        with sqlite3.connect(value.private_path) as db:
            assert db.execute('SELECT count(*) FROM private_stripe_reports').fetchone() == (
                0 if boundary == 'commit' else 1,)
        assert hashlib.sha256(value.business_path.read_bytes()).hexdigest() == before
    finally:
        release.set()
        if not running.done():
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
async def test_token_expiring_while_report_reads_upstream_cannot_save_or_disclose(report_app):
    value = report_app.value
    entered, release = asyncio.Event(), asyncio.Event()
    async def held():
        entered.set()
        await release.wait()
    report_app.control.hook = held
    token = emp_auth.create_access_token({'emp_id': 1, 'role': 'super_admin', 'sid': 'synthetic-session-1'},
                                        expires_delta=timedelta(seconds=2))
    running = asyncio.create_task(value.client.post(URL, headers={'Authorization': 'Bearer ' + token}, json={}))
    await asyncio.wait_for(entered.wait(), 3)
    try:
        await asyncio.sleep(2.1)
        release.set()
        response = await asyncio.wait_for(running, 3)
        assert response.status_code == 403 and response.headers['cache-control'] == 'no-store'
        with sqlite3.connect(value.private_path) as db:
            assert db.execute('SELECT count(*) FROM private_stripe_reports').fetchone() == (0,)
    finally:
        release.set()
        if not running.done():
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
async def test_nonowners_and_invalid_dates_do_not_make_any_provider_request(report_app, monkeypatch):
    value = report_app.value
    for employee_id in (2, 3, 4):
        response = await value.client.post(URL, headers=value.headers(employee_id), json={})
        assert response.status_code == 403 and response.headers['cache-control'] == 'no-store'
    for payload in ({'period': 'custom', 'start_date': '2026-10-13', 'end_date': '2026-10-13'},
                    {'period': 'year', 'start_date': '2026-01-01'}, {'refresh': 'true'},
                    {'period': 'month', 'account_id': 'acct_otherSynthetic123456'}):
        response = await value.client.post(URL, headers=value.headers(), json=payload)
        assert response.status_code == 422 and response.headers['cache-control'] == 'no-store'
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', '../not-a-timezone')
    response = await value.client.post(URL, headers=value.headers(), json={})
    assert response.status_code == 503 and response.headers['cache-control'] == 'no-store'
    assert not report_app.calls


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['identity', 'net', 'access_denied', 'timeout'])
async def test_safe_failure_never_persists_invalid_or_secret_report(report_app, monkeypatch, failure):
    value = report_app.value
    raw_secret = 'rk_test_doNotExposeSyntheticSecret12345'
    if failure in {'identity', 'net'}:
        report_app.control.result = batch([current_event()])
        if failure == 'identity':
            report_app.control.result['identity']['stripe_account_id'] = 'acct_wrongSynthetic12345'
        else:
            report_app.control.result['transactions'][0]['net'] = 42
    else:
        async def failing(*args):
            if failure == 'timeout':
                raise asyncio.TimeoutError(raw_secret)
            raise providers.ProviderError('access_denied')
        monkeypatch.setattr(provider, 'fetch_report', failing)
    before = hashlib.sha256(value.business_path.read_bytes()).hexdigest()
    response = await value.client.post(URL, headers=value.headers(), json={})
    assert response.status_code == 503 and response.headers['cache-control'] == 'no-store'
    assert raw_secret not in response.text and 'currencies' not in response.json()
    with sqlite3.connect(value.private_path) as db:
        assert db.execute('SELECT count(*) FROM private_stripe_reports').fetchone() == (0,)
    assert hashlib.sha256(value.business_path.read_bytes()).hexdigest() == before
