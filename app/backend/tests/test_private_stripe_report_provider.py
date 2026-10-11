"""Financial and read boundary tests; entirely synthetic mock HTTP records."""
import json

import httpx
import pytest

from services import private_stripe_report_provider as report
from services import private_workspace_providers as providers

KEY = 'rk_test_synthetic1234567890'
ACCOUNT = 'acct_synthetic12345678'
CREDENTIALS = {'api_key': KEY, 'stripe_account_id': ACCOUNT, 'mode': 'test'}
METADATA = {'stripe_account_id': ACCOUNT, 'mode': 'test'}
START, END = 1704067200, 1706745600


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_ACCOUNT_ID', ACCOUNT)
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_MODE', 'test')
    monkeypatch.delenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', raising=False)


def account():
    return {'id': ACCOUNT, 'object': 'account', 'business_profile': {'name': 'Synthetic business'}, 'settings': {}}


def balance():
    return {'object': 'balance', 'livemode': False, 'available': [{'currency': 'usd', 'amount': 1000}], 'pending': []}


def charge(identity='ch_sale', transaction='txn_sale', amount=10000, *, currency='usd', invoice=None, created=START - 86400, **fields):
    return {'id': identity, 'object': 'charge', 'livemode': False, 'amount': amount, 'amount_captured': amount,
            'amount_refunded': 0, 'captured': True, 'paid': True, 'refunded': False, 'status': 'succeeded',
            'currency': currency, 'created': created, 'invoice': invoice, 'customer': 'cus_synthetic',
            'balance_transaction': transaction, 'billing_details': {'name': 'Synthetic customer'}, 'payment_intent': None, **fields}


def refund(identity='re_refund', transaction='txn_refund', charge_id='ch_sale', amount=2000, **fields):
    # Real Stripe refund objects need not contain livemode.
    return {'id': identity, 'object': 'refund', 'balance_transaction': transaction, 'charge': charge_id,
            'amount': amount, 'currency': 'usd', 'status': 'succeeded', 'created': START + 60, **fields}


def transaction(identity='txn_sale', kind='charge', amount=10000, fee=320, source='ch_sale', created=START + 100, **fields):
    return {'id': identity, 'object': 'balance_transaction', 'type': kind, 'reporting_category': kind,
            'currency': 'usd', 'amount': amount, 'fee': fee, 'net': amount - fee, 'created': created,
            'source': source, 'status': 'available', 'description': 'Synthetic financial record', **fields}


def line(identity='il_subscription', kind='subscription', subscription_id='sub_plan', **fields):
    return {'id': identity, 'object': 'line_item', 'type': kind, 'subscription': subscription_id,
            'amount': 10000, 'currency': 'usd', 'livemode': False, **fields}


def invoice(identity='in_paid', charge_id='ch_sale', subscription_id='sub_plan', **fields):
    return {'id': identity, 'object': 'invoice', 'livemode': False, 'charge': charge_id, 'subscription': subscription_id,
            'currency': 'usd', 'paid': True, 'status': 'paid', 'customer': 'cus_synthetic', 'customer_name': 'Synthetic customer',
            'amount_remaining': 0, 'created': START - 86400, 'due_date': None,
            'lines': {'object': 'list', 'has_more': False, 'data': [line()] if subscription_id else []}, **fields}


def subscription(identity='sub_plan', **fields):
    return {'id': identity, 'object': 'subscription', 'livemode': False, 'status': 'active', 'currency': 'usd',
            'customer': 'cus_synthetic', 'created': START - 3000000, 'current_period_end': END, 'cancel_at_period_end': False,
            'items': {'object': 'list', 'has_more': False, 'data': [
                {'id': 'si_plan', 'object': 'subscription_item', 'subscription': identity, 'quantity': 1,
                 'price': {'id': 'price_plan', 'object': 'price', 'livemode': False, 'type': 'recurring', 'currency': 'usd',
                           'unit_amount': 10000, 'nickname': 'Synthetic plan', 'product': 'prod_synthetic',
                           'recurring': {'interval': 'month', 'interval_count': 1}}}]}, **fields}


def listing(rows=(), *, has_more=False, resource=None):
    result = {'object': 'list', 'data': list(rows), 'has_more': has_more}
    if resource: result['url'] = '/v1/' + resource
    return result


class StripeMock:
    def __init__(self, *, transactions=(), charges=(), refunds=(), invoices=(), subscriptions=(), overrides=None):
        self.transactions = list(transactions)
        self.objects = {}
        for resource, rows in [('charges', charges), ('refunds', refunds), ('invoices', invoices)]:
            for row in rows: self.objects[(resource, row['id'])] = row
        self.current_invoices = [row for row in invoices if row['status'] == 'open']
        self.subscriptions = list(subscriptions)
        self.overrides = overrides or {}; self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        assert request.method == 'GET'
        assert request.url.host == 'api.stripe.com'
        assert request.headers['stripe-version'] == report.STRIPE_REPORT_API_VERSION
        assert request.headers['authorization'] == 'Bearer ' + KEY
        path = request.url.path
        if path in self.overrides:
            handler = self.overrides[path]
            return handler(request) if callable(handler) else handler
        if path == '/v1/account': return httpx.Response(200, json=account())
        if path == '/v1/balance': return httpx.Response(200, json=balance())
        if path == '/v1/balance_transactions':
            assert request.url.params['created[gte]'] == str(START)
            assert request.url.params['created[lt]'] == str(END)
            return httpx.Response(200, json=listing(self.transactions, resource='balance_transactions'))
        if path == '/v1/subscriptions':
            # Current inventory must include old subscriptions and pending
            # cancellations. It is not filtered by this report's creation date.
            assert 'created[gte]' not in request.url.params
            return httpx.Response(200, json=listing(self.subscriptions))
        if path == '/v1/invoices':
            assert request.url.params['status'] == 'open'
            return httpx.Response(200, json=listing(self.current_invoices))
        if path in {'/v1/payouts', '/v1/disputes'}: return httpx.Response(200, json=listing())
        pieces = path.split('/')
        if len(pieces) == 4 and (pieces[2], pieces[3]) in self.objects:
            return httpx.Response(200, json=self.objects[(pieces[2], pieces[3])])
        raise AssertionError('Unexpected synthetic read: ' + path)


async def fetch(mock, credentials=None, metadata=None):
    return await report.fetch_report(credentials or CREDENTIALS, metadata or METADATA, START, END, transport=httpx.MockTransport(mock))


@pytest.mark.asyncio
async def test_settlement_receipts_capture_date_and_refunds_do_not_double_count():
    paid = charge(amount_refunded=2000, refunded=False)
    raw = [transaction(source=paid), transaction('txn_refund', 'refund', -2000, 0, refund())]
    mock = StripeMock(transactions=raw, charges=[paid])
    result = await fetch(mock)
    payment, returned = result['transactions']
    assert payment['created'] == START + 100 and payment['charge_created'] < START
    assert payment['amount'] == 10000 and payment['fee'] == 320 and payment['net'] == 9680
    assert returned['amount'] == -2000 and returned['fee'] == 0
    assert payment['classification'] == returned['classification'] == 'one_time'
    assert sum(row['net'] for row in result['transactions']) == 7680
    assert result['coverage']['amounts_complete'] and result['coverage']['classifications_complete']
    assert result['period']['timezone'] == 'UTC' and result['period']['end_exclusive']
    assert KEY not in json.dumps(result) and 'billing_details' not in json.dumps(result)


@pytest.mark.asyncio
async def test_partial_capture_uses_captured_amount_not_authorized_amount():
    paid = charge(amount=20000, amount_captured=7000, captured=False)
    result = await fetch(StripeMock(transactions=[transaction(amount=7000, fee=230, source=paid)]))
    row = result['transactions'][0]
    assert row['amount'] == row['source_amount_minor'] == 7000 and row['income_eligible'] is True


@pytest.mark.asyncio
async def test_documented_full_authorization_and_release_pair_is_retained_partial_without_overcount():
    paid = charge(amount=20000, amount_captured=7000, captured=True)
    released = refund(amount=13000)
    raw = [transaction(amount=20000, fee=250, source=paid), transaction('txn_refund', 'refund', -13000, 0, released)]
    result = await fetch(StripeMock(transactions=raw, charges=[paid]))
    payment, returned = result['transactions']
    assert payment['amount'] == 20000 and returned['amount'] == -13000
    assert sum(row['net'] for row in result['transactions']) == 6750
    assert payment['income_eligible'] is returned['income_eligible'] is None
    assert not result['coverage']['amounts_complete'] and not result['coverage']['source_verification_complete']
    assert any(row['code'] == 'partial_capture_unreconciled' for row in result['coverage']['warnings'])


@pytest.mark.asyncio
async def test_small_uncaptured_release_cannot_masquerade_as_customer_refund():
    paid = charge(amount=20000, amount_captured=13000)
    result = await fetch(StripeMock(transactions=[transaction('txn_refund', 'refund', -7000, 0, refund(amount=7000))], charges=[paid]))
    assert result['transactions'][0]['income_eligible'] is None
    assert not result['coverage']['amounts_complete']


@pytest.mark.asyncio
async def test_cross_currency_partial_capture_does_not_assert_full_authorization_as_income():
    paid = charge(amount=20000, amount_captured=7000, currency='eur')
    result = await fetch(StripeMock(transactions=[transaction(amount=22000, source=paid)]))
    assert result['transactions'][0]['income_eligible'] is None
    assert not result['coverage']['amounts_complete']


@pytest.mark.asyncio
async def test_expired_uncaptured_authorization_release_is_not_customer_refund():
    paid = charge(amount=20000, amount_captured=0, captured=False)
    raw = transaction('txn_refund', 'refund', -20000, 0, refund(amount=20000, reason='expired_uncaptured_charge'))
    result = await fetch(StripeMock(transactions=[raw], charges=[paid]))
    row = result['transactions'][0]
    assert row['income_eligible'] is False and row['exclusion_reason'] == 'uncaptured_authorization_release'
    assert row['classification_label'] == '未扣款预授权额度释放'
    assert result['coverage']['amounts_complete']


@pytest.mark.asyncio
async def test_old_payment_refunded_in_period_is_included_with_its_subscription_association():
    paid = charge(transaction='txn_old', invoice='in_paid', amount_refunded=2000)
    mock = StripeMock(transactions=[transaction('txn_refund', 'refund', -2000, 0, refund())], charges=[paid], invoices=[invoice()])
    result = await fetch(mock)
    row = result['transactions'][0]
    assert row['classification'] == 'subscription' and row['subscription_id'] == 'sub_plan'
    assert row['charge_created'] < START and row['amount'] == -2000 and row['income_eligible']
    assert not any('/v1/charges?' in str(call.url) for call in mock.calls)


@pytest.mark.asyncio
async def test_subscription_addon_invoice_is_explicitly_associated_and_never_split_by_description():
    lines = {'object': 'list', 'has_more': False, 'data': [line(), line('il_addon', 'invoiceitem', None, amount=500)]}
    paid = charge(invoice='in_paid', description='one time payment - misleading')
    result = await fetch(StripeMock(transactions=[transaction(source=paid)], invoices=[invoice(lines=lines)]))
    row = result['transactions'][0]
    assert row['classification'] == 'subscription' and row['includes_one_time_items'] is True
    assert '附加项' in row['classification_label'] and row['invoice_lines_complete']


@pytest.mark.asyncio
async def test_truncated_invoice_lines_preserve_association_but_do_not_claim_pure_recurring_revenue():
    lines = {'object': 'list', 'has_more': True, 'data': [line()]}
    result = await fetch(StripeMock(transactions=[transaction(source=charge(invoice='in_paid'))], invoices=[invoice(lines=lines)]))
    row = result['transactions'][0]
    assert row['classification'] == 'subscription' and row['includes_one_time_items'] is None
    assert not row['invoice_lines_complete']
    assert any(warning['code'] == 'incomplete_invoice_lines' for warning in result['coverage']['warnings'])


@pytest.mark.asyncio
async def test_no_invoice_is_one_time_even_if_description_says_subscription():
    result = await fetch(StripeMock(transactions=[transaction(source=charge(description='subscription annual renewal'))]))
    assert result['transactions'][0]['classification'] == 'one_time'


@pytest.mark.asyncio
@pytest.mark.parametrize('fields', [{'currency': 'eur'}, {'invoice': 'in_foreign'}, {'subscription': 'sub_foreign'}])
async def test_invoice_lines_from_another_currency_invoice_or_subscription_fail_closed(fields):
    bill = invoice(lines={'object': 'list', 'has_more': False, 'data': [line(**fields)]})
    with pytest.raises(providers.ProviderError) as failure:
        await fetch(StripeMock(transactions=[transaction(source=charge(invoice='in_paid'))], invoices=[bill]))
    assert failure.value.code == 'invalid_response'


@pytest.mark.asyncio
async def test_cross_currency_stays_settlement_currency_and_preserves_original_units():
    paid = charge(amount=10000, currency='eur')
    result = await fetch(StripeMock(transactions=[transaction(amount=12340, fee=450, source=paid)]))
    row = result['transactions'][0]
    assert row['currency'] == 'usd' and row['amount'] == 12340 and row['net'] == 11890
    assert row['source_currency'] == 'eur' and row['source_amount_minor'] == 10000


@pytest.mark.asyncio
async def test_zero_decimal_currency_and_fee_credits_preserve_exact_integers():
    paid = charge(amount=1000, currency='jpy')
    raw = transaction(amount=1000, fee=-12, source=paid, currency='jpy')
    result = await fetch(StripeMock(transactions=[raw]))
    row = result['transactions'][0]
    assert row['amount'] == 1000 and row['fee'] == -12 and row['net'] == 1012


@pytest.mark.asyncio
@pytest.mark.parametrize('fields', [
    {'paid': True, 'captured': False, 'amount_captured': 0},
    {'paid': False, 'captured': False, 'amount_captured': 0, 'status': 'failed'},
    {'paid': False, 'captured': False, 'amount_captured': 0, 'status': 'pending'},
])
async def test_uncaptured_failed_pending_charge_is_not_collected_income(fields):
    paid = charge(**fields)
    result = await fetch(StripeMock(transactions=[transaction(source=paid)]))
    row = result['transactions'][0]
    assert row['income_eligible'] is False and row['classification'] == 'unclassified'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['pending', 'failed', 'canceled', 'requires_action'])
async def test_non_succeeded_refund_is_balance_activity_not_confirmed_refund(status):
    result = await fetch(StripeMock(transactions=[transaction('txn_refund', 'refund', -2000, 0, refund(status=status))]))
    row = result['transactions'][0]
    assert row['income_eligible'] is False and row['source_status'] == status


@pytest.mark.asyncio
async def test_payout_transfer_dispute_and_failed_refund_reversals_are_not_income():
    raw = [transaction('txn_payout', 'payout', -5000, 0, 'po_payout'),
           transaction('txn_dispute', 'adjustment', -1000, 150, 'du_dispute', reporting_category='dispute'),
           transaction('txn_transfer', 'transfer', 500, 0, 'tr_transfer'),
           transaction('txn_reverse', 'refund_failure', 500, -20, 're_previous')]
    result = await fetch(StripeMock(transactions=raw))
    assert all(row['kind'] == 'other_balance_activity' and row['income_eligible'] is False for row in result['transactions'])
    assert result['transactions'][0]['source_url'].endswith('/payouts/po_payout')
    assert result['transactions'][1]['source_url'].endswith('/disputes/du_dispute')


@pytest.mark.asyncio
async def test_denied_invoice_permissions_keep_authoritative_money_as_unclassified():
    raw = transaction(source=charge(invoice='in_paid'))
    denied = httpx.Response(403, json={'error': {'message': 'RAW SECRET UPSTREAM TEXT'}})
    mock = StripeMock(transactions=[raw], overrides={'/v1/invoices': denied, '/v1/invoices/in_paid': denied})
    result = await fetch(mock)
    row = result['transactions'][0]
    assert row['income_eligible'] and row['amount'] == 10000 and row['classification'] == 'unclassified'
    assert result['coverage']['amounts_complete'] and not result['coverage']['classifications_complete']
    assert 'RAW SECRET' not in json.dumps(result)


@pytest.mark.asyncio
async def test_denied_charge_permission_marks_source_and_amount_eligibility_incomplete():
    denied = httpx.Response(403, json={'error': {'message': 'RAW PRIVATE MESSAGE'}})
    result = await fetch(StripeMock(transactions=[transaction()], overrides={'/v1/charges/ch_sale': denied}))
    row = result['transactions'][0]
    assert row['amount'] == 10000 and row['income_eligible'] is None and row['classification'] == 'unclassified'
    assert not result['coverage']['source_verification_complete'] and not result['coverage']['amounts_complete']
    assert 'RAW PRIVATE' not in json.dumps(result)


@pytest.mark.asyncio
async def test_primary_balance_read_permission_failure_cannot_masquerade_as_zero_income():
    with pytest.raises(providers.ProviderError) as failure:
        await fetch(StripeMock(overrides={'/v1/balance_transactions': httpx.Response(403, json={'error': {'message': KEY}})}))
    assert failure.value.code == 'access_denied' and KEY not in str(failure.value)


@pytest.mark.asyncio
async def test_expansion_permission_failure_retries_raw_transaction_reads_then_source_hydration():
    def balance_transactions(request):
        if 'expand[]' in request.url.params: return httpx.Response(403, json={'error': {'message': 'denied expansion'}})
        return httpx.Response(200, json=listing([transaction()]))
    mock = StripeMock(charges=[charge()], overrides={'/v1/balance_transactions': balance_transactions})
    result = await fetch(mock)
    assert result['coverage']['amounts_complete'] and result['transactions'][0]['classification'] == 'one_time'
    assert len([call for call in mock.calls if call.url.path == '/v1/balance_transactions']) == 2


@pytest.mark.asyncio
async def test_legacy_raw_pyr_refund_id_hydrates_through_readonly_allowlist_after_expansion_denied():
    returned = refund('pyr_legacyrefund')
    raw = transaction('txn_refund', 'refund', -2000, 0, 'pyr_legacyrefund')
    def balance_transactions(request):
        if 'expand[]' in request.url.params: return httpx.Response(403, json={'error': {'message': 'synthetic permission denial'}})
        return httpx.Response(200, json=listing([raw]))
    mock = StripeMock(charges=[charge()], refunds=[returned], overrides={'/v1/balance_transactions': balance_transactions})
    result = await fetch(mock)
    assert result['transactions'][0]['income_eligible'] is True
    assert result['transactions'][0]['classification'] == 'one_time'
    assert result['coverage']['amounts_complete']
    assert any(call.url.path == '/v1/refunds/pyr_legacyrefund' for call in mock.calls)


@pytest.mark.asyncio
async def test_positive_local_method_refund_reversal_is_balance_activity():
    raw = transaction('txn_returned', 'payment_refund', 2000, 0, 'pyr_returned')
    result = await fetch(StripeMock(transactions=[raw]))
    row = result['transactions'][0]
    assert row['kind'] == 'other_balance_activity' and row['income_eligible'] is False
    assert row['amount'] == 2000 and result['coverage']['amounts_complete']


@pytest.mark.asyncio
async def test_all_pages_are_followed_and_cursor_is_resource_specific():
    def pages(request):
        if request.url.params.get('starting_after') is None:
            return httpx.Response(200, json=listing([transaction(source=charge())], has_more=True))
        assert request.url.params['starting_after'] == 'txn_sale'
        return httpx.Response(200, json=listing([transaction('txn_second', amount=5000, fee=175, source=charge('ch_second', 'txn_second', 5000))]))
    mock = StripeMock(overrides={'/v1/balance_transactions': pages})
    result = await fetch(mock)
    assert len(result['transactions']) == 2 and result['coverage']['balance_transactions']['pages'] == 2
    assert result['coverage']['amounts_complete']


@pytest.mark.asyncio
async def test_record_cap_is_partial_and_never_claims_complete_range(monkeypatch):
    monkeypatch.setattr(report, 'MAX_BALANCE_TRANSACTIONS', 1)
    raw = listing([transaction(source=charge())], has_more=True)
    result = await fetch(StripeMock(overrides={'/v1/balance_transactions': httpx.Response(200, json=raw)}))
    coverage = result['coverage']['balance_transactions']
    assert coverage == {'complete': False, 'count': 1, 'pages': 1, 'reason': 'record_limit', 'record_limit': 1}
    assert not result['coverage']['amounts_complete'] and not result['coverage']['classifications_complete']


@pytest.mark.asyncio
async def test_later_page_rate_limit_keeps_observed_money_and_marks_partial():
    def pages(request):
        if request.url.params.get('starting_after'): return httpx.Response(429, json={'error': {'message': 'secret upstream'}})
        return httpx.Response(200, json=listing([transaction(source=charge())], has_more=True))
    result = await fetch(StripeMock(overrides={'/v1/balance_transactions': pages}))
    assert result['transactions'][0]['amount'] == 10000 and not result['coverage']['amounts_complete']
    assert result['coverage']['balance_transactions']['reason'] == 'rate_limited'


@pytest.mark.asyncio
async def test_request_budget_marks_secondary_and_hydration_partial(monkeypatch):
    monkeypatch.setattr(providers, 'MAX_REQUESTS', 3)
    result = await fetch(StripeMock(transactions=[transaction()]))
    assert result['coverage']['balance_transactions']['complete']
    assert not result['coverage']['subscriptions_complete'] and not result['coverage']['amounts_complete']
    assert result['coverage']['subscriptions']['reason'] == 'sync_limit'


@pytest.mark.asyncio
async def test_time_budget_stops_reads_and_marks_partial(monkeypatch):
    original_read = report._ReportReader.read
    async def expired_after_transactions(reader, resource, parameters=None, identity=None):
        if resource != 'balance_transactions': reader.client.deadline = 0
        return await original_read(reader, resource, parameters, identity)
    monkeypatch.setattr(report._ReportReader, 'read', expired_after_transactions)
    result = await fetch(StripeMock(transactions=[transaction()]))
    assert not result['coverage']['amounts_complete'] and result['coverage']['subscriptions']['reason'] == 'upstream_timeout'


@pytest.mark.asyncio
@pytest.mark.parametrize('resource,rows', [
    ('balance_transactions', [transaction(source=charge()), transaction(source=charge())]),
    ('subscriptions', [subscription(), subscription()]),
])
async def test_duplicate_records_fail_closed(resource, rows):
    with pytest.raises(providers.ProviderError) as failure:
        await fetch(StripeMock(overrides={'/v1/' + resource: httpx.Response(200, json=listing(rows))}))
    assert failure.value.code == 'invalid_response'


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [
    {'object': 'list', 'data': [], 'has_more': True},
    {'object': 'list', 'data': [], 'has_more': 'false'},
    {'object': 'list', 'data': 'not list', 'has_more': False},
    {'object': 'list', 'data': [], 'has_more': False, 'url': '/v1/charges'},
])
async def test_invalid_pagination_cannot_claim_complete(payload):
    with pytest.raises(providers.ProviderError) as failure:
        await fetch(StripeMock(overrides={'/v1/balance_transactions': httpx.Response(200, json=payload)}))
    assert failure.value.code == 'invalid_response'


@pytest.mark.asyncio
@pytest.mark.parametrize('fields', [
    {'amount': True}, {'fee': 1.5}, {'net': 9999}, {'currency': 'US D'},
    {'created': END}, {'created': START - 1}, {'source': '../../charges/ch_foreign'},
    {'id': 'txn_bad?api_key=oops'}, {'type': 'charge', 'amount': -1, 'net': -321},
    {'reporting_category': None}, {'status': 'unknown'}, {'type': 'future_unknown_income'},
])
async def test_malformed_monetary_records_fail_closed(fields):
    raw = transaction(**{'source': charge(), **fields})
    with pytest.raises(providers.ProviderError) as failure: await fetch(StripeMock(transactions=[raw]))
    assert failure.value.code == 'invalid_response'


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['charge_backlink', 'invoice_backlink', 'invoice_customer', 'invoice_currency', 'invoice_unpaid', 'missing_invoice_field', 'missing_subscription_field', 'refund_backlink', 'refund_currency'])
async def test_broken_financial_linkage_fails_closed(change):
    paid = charge(invoice='in_paid'); bill = invoice(); returned = refund()
    raw = transaction(source=paid)
    if change == 'charge_backlink': paid['balance_transaction'] = 'txn_foreign'
    if change == 'invoice_backlink': bill['charge'] = 'ch_foreign'
    if change == 'invoice_customer': bill['customer'] = 'cus_foreign'
    if change == 'invoice_currency': bill['currency'] = 'eur'
    if change == 'invoice_unpaid': bill.update(paid=False, status='open')
    if change == 'missing_invoice_field': paid.pop('invoice')
    if change == 'missing_subscription_field': bill.pop('subscription')
    if change.startswith('refund_'):
        paid['balance_transaction'] = 'txn_old'
        raw = transaction('txn_refund', 'refund', -2000, 0, returned)
        if change == 'refund_backlink': returned['balance_transaction'] = 'txn_foreign'
        else: returned['currency'] = 'eur'
    with pytest.raises(providers.ProviderError) as failure:
        await fetch(StripeMock(transactions=[raw], charges=[paid], invoices=[bill]))
    assert failure.value.code == 'invalid_response'


@pytest.mark.asyncio
@pytest.mark.parametrize('resource', ['balance', 'balance_transaction', 'charge', 'invoice', 'subscription', 'refund'])
async def test_returned_live_mode_mismatch_is_rejected(resource):
    paid = charge(invoice='in_paid'); bill = invoice(); plan = subscription(); returned = refund(livemode=True)
    raw = transaction(source=paid); overrides = {}
    if resource == 'balance': overrides['/v1/balance'] = httpx.Response(200, json={**balance(), 'livemode': True})
    if resource == 'balance_transaction': raw['livemode'] = True
    if resource == 'charge': paid['livemode'] = True
    if resource == 'invoice': bill['livemode'] = True
    if resource == 'subscription': plan['livemode'] = True
    if resource == 'refund': raw = transaction('txn_refund', 'refund', -2000, 0, returned)
    with pytest.raises(providers.ProviderError) as failure:
        await fetch(StripeMock(transactions=[raw], invoices=[bill], subscriptions=[plan], overrides=overrides))
    assert failure.value.code == 'stripe_account_changed'


@pytest.mark.asyncio
@pytest.mark.parametrize('which,field,value', [
    ('credentials', 'stripe_account_id', 'acct_foreign12345678'), ('credentials', 'mode', 'live'),
    ('metadata', 'stripe_account_id', 'acct_foreign12345678'), ('metadata', 'mode', 'live'),
    ('credentials', 'api_key', 'rk_live_synthetic1234567890'),
])
async def test_stored_account_and_mode_binding_is_checked_before_http(which, field, value):
    credentials, metadata = dict(CREDENTIALS), dict(METADATA)
    (credentials if which == 'credentials' else metadata)[field] = value
    mock = StripeMock()
    with pytest.raises(providers.ProviderError) as failure: await fetch(mock, credentials, metadata)
    assert failure.value.code == 'stripe_account_changed' and mock.calls == []


@pytest.mark.asyncio
async def test_actual_account_mismatch_is_rejected_before_financial_reads():
    mock = StripeMock(overrides={'/v1/account': httpx.Response(200, json={**account(), 'id': 'acct_foreign12345678'})})
    with pytest.raises(providers.ProviderError) as failure: await fetch(mock)
    assert failure.value.code == 'stripe_account_changed' and len(mock.calls) == 1


@pytest.mark.asyncio
async def test_open_invoice_and_subscription_inventory_are_observed_status_never_income():
    plan = subscription(status='past_due', cancel_at_period_end=True)
    outstanding = invoice('in_open', None, 'sub_plan', status='open', paid=False, amount_remaining=4000)
    result = await fetch(StripeMock(subscriptions=[plan], invoices=[outstanding]))
    assert result['transactions'] == []
    assert {row['kind'] for row in result['attention']} == {'subscription', 'invoice'}
    assert all(row['is_income'] is False and row['date_basis'] == 'current_status' for row in result['attention'])
    assert result['subscriptions'][0]['items'][0]['unit_amount_minor'] == 10000
    assert result['coverage']['subscriptions']['scope'] == 'current_non_canceled'
    assert next(row for row in result['attention'] if row['kind'] == 'subscription')['reason'] == '订阅已设置到期取消，请核对后续安排'


@pytest.mark.asyncio
async def test_period_payout_dispute_inspection_has_independent_date_basis():
    payout = {'id': 'po_failed', 'object': 'payout', 'livemode': False, 'created': START + 1, 'status': 'failed',
              'currency': 'usd', 'amount': 3000, 'arrival_date': END - 100}
    dispute = {'id': 'du_response', 'object': 'dispute', 'livemode': False, 'created': START + 2,
               'status': 'needs_response', 'currency': 'usd', 'amount': 1000, 'evidence_details': {'due_by': END - 50}}
    result = await fetch(StripeMock(overrides={'/v1/payouts': httpx.Response(200, json=listing([payout])), '/v1/disputes': httpx.Response(200, json=listing([dispute]))}))
    assert len(result['attention']) == 2 and result['transactions'] == []
    assert all(row['is_income'] is False and row['date_basis'] == 'resource_created' for row in result['attention'])


@pytest.mark.asyncio
async def test_null_metered_price_does_not_invent_subscription_revenue():
    plan = subscription(); plan['items']['data'][0]['price']['unit_amount'] = None
    result = await fetch(StripeMock(subscriptions=[plan]))
    assert result['subscriptions'][0]['items'][0]['unit_amount_minor'] is None
    assert result['transactions'] == []


@pytest.mark.asyncio
async def test_truncated_subscription_items_explicitly_limit_inventory(monkeypatch):
    plan = subscription(); plan['items']['has_more'] = True
    result = await fetch(StripeMock(subscriptions=[plan]))
    assert result['coverage']['amounts_complete'] and not result['coverage']['subscriptions_complete']
    assert not result['subscriptions'][0]['items_complete']


@pytest.mark.asyncio
@pytest.mark.parametrize('zone', ['', 'Not/AZone', 'UTC\ninvalid'])
async def test_invalid_server_reporting_timezone_is_rejected_before_http(monkeypatch, zone):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_REPORT_TIMEZONE', zone)
    mock = StripeMock()
    with pytest.raises(providers.ProviderError) as failure: await fetch(mock)
    assert failure.value.code == 'not_configured' and mock.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('start,end', [(True, END), (START, False), (START, START), (-1, END), (str(START), END)])
async def test_invalid_range_fails_before_http(start, end):
    mock = StripeMock()
    with pytest.raises(providers.ProviderError):
        await report.fetch_report(CREDENTIALS, METADATA, start, end, transport=httpx.MockTransport(mock))
    assert not mock.calls


@pytest.mark.asyncio
@pytest.mark.parametrize('method,path', [
    ('POST', '/v1/balance_transactions'), ('DELETE', '/v1/subscriptions/sub_plan'),
    ('POST', '/v1/charges/ch_sale/capture'), ('GET', '/v1/invoices/in_bad/finalize'),
    ('GET', '/v1/charges/ch_bad/../ch_sale'), ('GET', '/v1/refunds/re_bad/cancel'),
    ('GET', '/v1/customers/cus_customer'), ('GET', '/v1/subscriptions/sub_plan/cancel'),
])
async def test_client_report_allowlist_cannot_be_used_for_mutations_or_arbitrary_reads(method, path):
    mock = StripeMock()
    async with providers._Client(httpx.MockTransport(mock)) as client:
        with pytest.raises(providers.ProviderError) as failure:
            await client.request(method, 'https://api.stripe.com' + path)
    assert failure.value.code == 'request_not_allowed' and mock.calls == []


@pytest.mark.asyncio
async def test_upstream_redirect_is_not_followed_and_error_body_never_returned():
    mock = StripeMock(overrides={'/v1/account': httpx.Response(302, headers={'Location': 'https://evil.invalid/capture?api_key=' + KEY})})
    with pytest.raises(providers.ProviderError) as failure: await fetch(mock)
    assert failure.value.code == 'invalid_response' and len(mock.calls) == 1 and KEY not in str(failure.value)
