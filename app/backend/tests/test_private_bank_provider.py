"""Synthetic Plaid requests only: institution binding, no money actions, atomic deltas."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import json
from uuid import uuid4

import httpx
import pytest

from models.private_workspace import utcnow
from services import private_bank_provider as bank

CLIENT = 'synthetic_plaid_client'
SECRET = 'synthetic_plaid_secret'
ITEM = 'synthetic_bank_item'
INSTITUTION = 'ins_synthetic_bofa'
ACCESS = 'access-production-synthetic_private_only'
LINK = 'link-production-synthetic_private_only'
PUBLIC = 'public-production-synthetic_private_only'


@pytest.fixture
def bank_config(monkeypatch):
    for key, value in {
        'PRIVATE_WORKSPACE_PLAID_ENABLED': 'true', 'PRIVATE_WORKSPACE_PLAID_CLIENT_ID': CLIENT,
        'PRIVATE_WORKSPACE_PLAID_SECRET': SECRET, 'PRIVATE_WORKSPACE_PLAID_ENV': 'production',
        'PRIVATE_WORKSPACE_PUBLIC_URL': 'https://t24-crm.com',
        'PRIVATE_WORKSPACE_ENCRYPTION_KEY': 'synthetic_private_bank_cipher_for_tests_only',
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv('PRIVATE_WORKSPACE_BOFA_INSTITUTION_ID', raising=False)


def credentials():
    return {'owner_id': '4', 'environment': 'production', 'client_fingerprint': bank.bank_settings()['client_fingerprint'],
            'institution_id': INSTITUTION, 'item_id': ITEM, 'access_token': ACCESS, 'transaction_cursor': 'cursor_original'}


def account(account_id='synthetic_checking', **changes):
    return {'account_id': account_id, 'name': 'Synthetic checking', 'mask': '1234', 'type': 'depository', 'subtype': 'checking',
            'balances': {'current': 123.45, 'available': None, 'limit': None, 'iso_currency_code': 'USD',
                         'unofficial_currency_code': None, 'last_updated_datetime': None}, **changes}


def transaction(transaction_id='synthetic_tx', **changes):
    return {'transaction_id': transaction_id, 'account_id': 'synthetic_checking', 'amount': 12.35,
            'iso_currency_code': 'USD', 'unofficial_currency_code': None, 'pending': False,
            'pending_transaction_id': None, 'date': '2026-10-10', 'datetime': None,
            'name': 'Synthetic transaction', 'merchant_name': 'Synthetic merchant', **changes}


def sync_page(*, added=None, modified=None, removed=None, cursor='cursor_final', more=False, state='HISTORICAL_UPDATE_COMPLETE'):
    return {'added': added or [], 'modified': modified or [], 'removed': removed or [],
            'next_cursor': cursor, 'has_more': more, 'transactions_update_status': state}


class BankMock:
    def __init__(self, pages=None):
        self.pages = pages or [sync_page(added=[transaction()])]
        self.calls = []
        self.overrides = {}
        self.accounts = [account()]
        self.link_results = [{'results': {'item_add_results': [{'public_token': PUBLIC, 'institution': {'institution_id': INSTITUTION}}]}}]

    async def __call__(self, request):
        self.calls.append(request)
        assert request.method == 'POST' and request.url.host in bank.HOSTS.values()
        assert request.url.path in bank.PATHS and not request.url.query
        data = json.loads(request.content)
        assert data['client_id'] == CLIENT and data['secret'] == SECRET
        value = self.overrides.get(request.url.path)
        if callable(value): value = value(request, data)
        if isinstance(value, httpx.Response): return value
        if value is None:
            if request.url.path == '/link/token/create':
                value = {'link_token': LINK, 'hosted_link_url': 'https://secure.plaid.com/hl/synthetic_authorization',
                         'expiration': (utcnow() + timedelta(hours=2)).isoformat()}
            elif request.url.path == '/link/token/get': value = {'link_token': LINK, 'link_sessions': self.link_results}
            elif request.url.path == '/item/public_token/exchange': value = {'access_token': ACCESS, 'item_id': ITEM}
            elif request.url.path == '/item/get': value = {'item': {'item_id': ITEM, 'institution_id': INSTITUTION, 'error': None, 'status': {}}}
            elif request.url.path == '/institutions/get_by_id':
                value = {'institution': {'institution_id': INSTITUTION, 'name': 'Bank of America', 'country_codes': ['US'], 'products': ['transactions']}}
            elif request.url.path == '/accounts/get': value = {'item': {'item_id': ITEM, 'institution_id': INSTITUTION}, 'accounts': self.accounts}
            elif request.url.path == '/transactions/sync': value = self.pages.pop(0)
            else: raise AssertionError('Unexpected bank endpoint')
        return httpx.Response(200, json=value)

    @property
    def transport(self): return httpx.MockTransport(self)


@pytest.mark.asyncio
async def test_hosted_link_is_owner_bound_transactions_only_without_delivery(bank_config):
    mock = BankMock()
    session = str(uuid4())
    result = await bank.create_hosted_link('4', session, transport=mock.transport)
    payload = json.loads(mock.calls[0].content)
    assert payload['products'] == ['transactions'] and payload['country_codes'] == ['US']
    assert payload['hosted_link'] == {'completion_redirect_uri': 'https://t24-crm.com/private-workspace?view=bofa_bank&bank_session=' + session,
                                      'is_mobile_app': False, 'url_lifetime_seconds': 900}
    assert not {'webhook', 'email', 'phone_number'} & set(payload)
    assert result['authorization_url'] == 'https://secure.plaid.com/hl/synthetic_authorization'
    assert utcnow() < bank._aware(result['expires_at']) <= utcnow() + timedelta(seconds=900)
    assert len(mock.calls) == 1


@pytest.mark.parametrize('url', ['http://secure.plaid.com/hl/12345678', 'https://evil.example/hl/12345678',
    'https://secure.plaid.com.evil/hl/12345678', 'https://secure.plaid.com/hl/12345678?token=x',
    'https://u@secure.plaid.com/hl/12345678', 'https://secure.plaid.com:8443/hl/12345678', 'https://secure.plaid.com/other/12345678'])
def test_hosted_url_cannot_escape_approved_provider(url):
    with pytest.raises(bank.BankProviderError): bank.hosted_url(url)


@pytest.mark.asyncio
async def test_unapproved_money_and_paid_refresh_endpoints_are_unreachable(bank_config):
    mock = BankMock()
    async with bank.BankClient(bank.bank_settings(), mock.transport) as client:
        for path in ['/transfer/create', '/payment_initiation/payment/create', '/accounts/balance/get', '/transactions/refresh', 'https://evil.example/transactions/sync']:
            with pytest.raises(bank.BankProviderError) as error: await client.request(path, {})
            assert error.value.code == 'bank_request_not_allowed'
    assert not mock.calls


@pytest.mark.asyncio
async def test_exchange_does_not_complete_from_redirect_and_verifies_institution(bank_config):
    mock = BankMock(); mock.link_results = []
    context = {'link_token': LINK, 'environment': 'production', 'client_fingerprint': bank.bank_settings()['client_fingerprint']}
    assert await bank.exchange_completed_link(context, transport=mock.transport) is None
    assert [r.url.path for r in mock.calls] == ['/link/token/get']
    mock = BankMock(); staged = []
    async def save(value): staged.append(value)
    result = await bank.exchange_completed_link(context, transport=mock.transport, on_exchanged=save)
    assert len(staged) == 1 and PUBLIC not in json.dumps(staged) and staged[0]['access_token'] == ACCESS
    assert result['credentials']['institution_id'] == INSTITUTION
    assert result['metadata']['mode'] == 'live'
    assert [r.url.path for r in mock.calls] == ['/link/token/get', '/item/public_token/exchange', '/item/get', '/institutions/get_by_id']


@pytest.mark.asyncio
async def test_exchange_stage_resumes_without_reusing_one_time_public_token(bank_config):
    mock = BankMock()
    context = {'link_token': LINK, **credentials()}
    result = await bank.exchange_completed_link(context, transport=mock.transport)
    assert result['credentials']['access_token'] == ACCESS
    assert [r.url.path for r in mock.calls] == ['/item/get', '/institutions/get_by_id']


@pytest.mark.asyncio
async def test_delta_pagination_is_complete_preserves_input_cursor_and_pending_replacement(bank_config):
    mock = BankMock([
        sync_page(added=[transaction('old_pending', pending=True), transaction('modified_tx')], cursor='cursor_middle', more=True),
        sync_page(added=[transaction('posted_tx', pending_transaction_id='old_pending', amount=-56.78)],
                  modified=[transaction('modified_tx', amount=9.99)], removed=[{'transaction_id': 'removed_tx', 'account_id': 'synthetic_checking'}]),
    ])
    original = credentials(); unchanged = deepcopy(original)
    result = await bank.fetch_bofa_bank(original, transport=mock.transport)
    assert original == unchanged and result['credentials']['transaction_cursor'] == 'cursor_final'
    assert result['removed_external_ids'] == [ITEM + ':removed_tx']
    assert result['replaced_pending_external_ids'] == [ITEM + ':old_pending']
    values = {row['external_id']: row for row in result['items']}
    assert set(values) == {ITEM + ':modified_tx', ITEM + ':posted_tx'}
    assert values[ITEM + ':modified_tx']['amount_minor'] == -999
    assert values[ITEM + ':posted_tx']['amount_minor'] == 5678
    assert values[ITEM + ':posted_tx']['evidence']['amount_direction'] == 'inflow'
    assert all(row['occurred_at'] is None for row in values.values())
    assert result['balances'] == [] and result['metadata']['bank_accounts'][0]['available_minor'] is None
    snapshot = result['metadata']['bank_snapshot']
    assert snapshot['transactions_complete'] is True and snapshot['balance_realtime'] is False
    assert snapshot['accounts_complete'] is True and snapshot['pagination_complete'] is True
    sync_calls = [json.loads(row.content) for row in mock.calls if row.url.path == '/transactions/sync']
    assert [row['cursor'] for row in sync_calls] == ['cursor_original', 'cursor_middle']
    assert not any('balance/get' in row.url.path or 'refresh' in row.url.path for row in mock.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('state,complete', [('UNKNOWN', False), ('NOT_READY', False), ('INITIAL_UPDATE_COMPLETE', False), ('HISTORICAL_UPDATE_COMPLETE', True)])
async def test_history_preparing_is_not_claimed_as_all_read(bank_config, state, complete):
    result = await bank.fetch_bofa_bank(credentials(), transport=BankMock([sync_page(state=state)]).transport)
    assert result['metadata']['bank_snapshot']['transactions_complete'] is complete
    assert result['metadata']['partial'] is not complete


@pytest.mark.asyncio
async def test_cached_credit_balance_is_debt_missing_balance_stays_missing(bank_config):
    mock = BankMock([sync_page()])
    mock.accounts = [account(type='credit', subtype='credit card', balances={'current': 100.005, 'available': None, 'limit': 900.10,
                                                                        'iso_currency_code': 'USD', 'unofficial_currency_code': None})]
    result = await bank.fetch_bofa_bank(credentials(), transport=mock.transport)
    row = result['metadata']['bank_accounts'][0]
    assert row['balance_kind'] == 'owed' and row['current_minor'] == 10001 and row['available_minor'] is None and row['limit_minor'] == 90010
    assert row['current_decimal'] == '100.005' and row['balance_source'] == 'cached_accounts_get'
    assert result['metadata']['bank_snapshot']['bank_updated_at'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('where', ['institution', 'item', 'account', 'environment', 'owner'])
async def test_cross_bank_identity_is_rejected(bank_config, where):
    mock = BankMock(); auth = credentials()
    if where == 'institution': mock.overrides['/institutions/get_by_id'] = {'institution': {'institution_id': INSTITUTION, 'name': 'Chase', 'products': ['transactions'], 'country_codes': ['US']}}
    elif where == 'item': mock.overrides['/accounts/get'] = {'item': {'item_id': 'different_item', 'institution_id': INSTITUTION}, 'accounts': [account()]}
    elif where == 'account': mock.pages = [sync_page(added=[transaction(account_id='different_account')])]
    elif where == 'environment': auth['environment'] = 'sandbox'
    else: auth['owner_id'] = '5'
    with pytest.raises(bank.BankProviderError): await bank.fetch_bofa_bank(auth, transport=mock.transport)
    if where in {'environment', 'owner'}: assert not mock.calls


@pytest.mark.asyncio
async def test_second_page_mutation_keeps_original_cursor_and_no_partial_batch(bank_config):
    mock = BankMock([sync_page(added=[transaction()], cursor='middle', more=True)])
    def pages(request, data):
        return sync_page(added=[transaction()], cursor='middle', more=True) if data['cursor'] == 'cursor_original' else httpx.Response(
            400, json={'error_code': 'TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION', 'error_message': ACCESS + SECRET})
    mock.overrides['/transactions/sync'] = pages
    original = credentials()
    with pytest.raises(bank.BankProviderError) as error: await bank.fetch_bofa_bank(original, transport=mock.transport)
    assert error.value.code == 'bank_pagination_changed' and error.value.retryable
    assert original['transaction_cursor'] == 'cursor_original' and ACCESS not in str(error.value) and SECRET not in str(error.value)
    assert len([row for row in mock.calls if row.url.path == '/transactions/sync']) == 2


@pytest.mark.asyncio
async def test_sandbox_cannot_be_reported_as_real(bank_config, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_PLAID_ENV', 'sandbox')
    auth = {**credentials(), 'environment': 'sandbox', 'access_token': 'access-sandbox-synthetic_private_only'}
    mock = BankMock([sync_page()])
    result = await bank.fetch_bofa_bank(auth, transport=mock.transport)
    assert result['metadata']['mode'] == 'test' and result['metadata']['bank_snapshot']['environment'] == 'sandbox'
    assert all(row.url.host == 'sandbox.plaid.com' for row in mock.calls)


@pytest.mark.parametrize('value', [True, float('inf'), float('nan'), 'NaN', '-Infinity', 'notmoney', '90000000000001'])
def test_invalid_decimal_never_becomes_bank_money(value):
    with pytest.raises(bank.BankProviderError): bank._decimal(value)


def test_decimal_minor_conversion_does_not_truncate_cents():
    assert bank._minor(Decimal('1.005'), 'USD') == 101
    assert bank._minor(Decimal('-1.005'), 'USD') == -101
    assert bank._minor(None, 'USD') is None and bank._minor('12', None) is None
    assert bank._minor('12', 'JPY') == 12
    assert bank._minor('12', 'ISK') == 12 and bank._minor('12', 'UGX') == 12
    assert bank._minor('12.345', 'BHD') == 12345 and bank._minor('12.345', 'KWD') == 12345
    assert bank._minor('12.3456', 'CLF') == 123456 and bank._minor('12.34', 'MGA') == 1234
    assert bank._minor('12', 'XYZ') is None and bank._minor('12', 'XXX') is None


@pytest.mark.asyncio
async def test_redirection_and_provider_error_do_not_leak_tokens(bank_config):
    mock = BankMock()
    mock.overrides['/item/get'] = httpx.Response(302, headers={'Location': 'https://evil.example/' + ACCESS})
    with pytest.raises(bank.BankProviderError) as error: await bank.fetch_bofa_bank(credentials(), transport=mock.transport)
    assert error.value.code == 'bank_request_not_allowed' and len(mock.calls) == 1 and ACCESS not in str(error.value)
    mock = BankMock(); mock.overrides['/item/get'] = httpx.Response(401, json={'error_code': 'INVALID_ACCESS_TOKEN', 'error_message': SECRET})
    with pytest.raises(bank.BankProviderError) as error: await bank.fetch_bofa_bank(credentials(), transport=mock.transport)
    assert error.value.code == 'bank_authorization_expired' and SECRET not in str(error.value)


def test_bank_requires_explicit_enable_and_fixed_https_origin(bank_config, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_PLAID_ENABLED', 'false')
    assert 'PRIVATE_WORKSPACE_PLAID_ENABLED' in bank.missing_configuration()
    monkeypatch.setenv('PRIVATE_WORKSPACE_PLAID_ENABLED', 'true')
    monkeypatch.setenv('PRIVATE_WORKSPACE_PUBLIC_URL', 'https://t24-crm.com/evil')
    assert 'PRIVATE_WORKSPACE_PUBLIC_URL' in bank.missing_configuration()
