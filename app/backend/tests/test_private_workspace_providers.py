"""Real adapter methods with mock HTTP; no database, credentials or live requests."""
import asyncio
import json
from urllib.parse import parse_qs

import httpx
import pytest

from services import private_workspace_providers as providers

KEY = 'rk_test_synthetic1234567890'
GOOGLE = {'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh', 'expires_at': 2000000000,
          'scope': providers.GMAIL_SCOPE, 'token_type': 'Bearer'}
ENVIRONMENTS = ('GOOGLE_WORKSPACE_CLIENT_ID', 'GOOGLE_WORKSPACE_CLIENT_SECRET', 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET',
                'PRIVATE_WORKSPACE_PUBLIC_URL', 'GOOGLE_ADS_DEVELOPER_TOKEN', 'PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID',
                'GOOGLE_ADS_CUSTOMER_ID', 'GOOGLE_ADS_LOGIN_CUSTOMER_ID', 'PRIVATE_WORKSPACE_STRIPE_KEY',
                'PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT')


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    for name in ENVIRONMENTS: monkeypatch.delenv(name, raising=False)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('GOOGLE_WORKSPACE_CLIENT_ID', 'synthetic-client.apps.googleusercontent.com')
    monkeypatch.setenv('GOOGLE_WORKSPACE_CLIENT_SECRET', 'synthetic-client-secret')
    monkeypatch.setenv('PRIVATE_WORKSPACE_PUBLIC_URL', 'https://t24-crm.com')
    monkeypatch.setenv('PRIVATE_WORKSPACE_GOOGLE_ADS_CUSTOMER_ID', '123-456-7890')
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_KEY', KEY)


def balance():
    return {'object': 'balance', 'available': [{'currency': 'usd', 'amount': -123}, {'currency': 'jpy', 'amount': 1}],
            'pending': [{'currency': 'usd', 'amount': 456}]}


def message(identity='a1', sender='Sender <sender@example.com>'):
    return {'id': identity, 'threadId': 'b2', 'internalDate': '1700000000000', 'labelIds': ['UNREAD'],
            'snippet': 'Brief notification', 'payload': {'headers': [{'name': 'Subject', 'value': 'Notice'},
            {'name': 'From', 'value': sender}], 'body': {'data': 'FULL_MAIL_BODY_MUST_NOT_ESCAPE'}}}


def campaign(identity=1):
    return {'campaign': {'id': str(identity), 'name': 'Campaign', 'status': 'ENABLED'},
            'metrics': {'impressions': '10', 'clicks': '2', 'costMicros': '1000501'}}


def stripe_row(resource):
    prefix = {'charges': 'ch_', 'refunds': 're_', 'disputes': 'dp_', 'payouts': 'po_'}[resource]
    row = {'id': prefix+'synthetic1', 'amount': 1, 'currency': 'jpy', 'created': 1700000000,
           'status': 'needs_response' if resource == 'disputes' else 'succeeded' if resource != 'payouts' else 'in_transit'}
    if resource == 'refunds': row['charge'] = 'ch_synthetic1'
    if resource == 'disputes': row['evidence_details'] = {'due_by': 1700001000}
    if resource == 'payouts': row['arrival_date'] = 1700002000
    return row


def test_unconfigured_registry_is_honest_and_contains_no_configuration_values():
    sources = providers.describe_sources()
    assert [row['id'] for row in sources] == ['gmail', 'google_ads', 'bofa', 'stripe', 'manual']
    assert all(row['status'] == 'not_configured' for row in sources[:-1])
    assert sources[-1]['status'] == 'disconnected'
    assert all(isinstance(row['capabilities'], list) for row in sources)
    assert 'client_secret' not in json.dumps(sources)


@pytest.mark.asyncio
async def test_missing_configuration_does_not_attempt_authorization_or_http():
    async def forbidden(request): raise AssertionError('HTTP was not authorized')
    for source in ('gmail', 'google_ads', 'bofa', 'stripe'):
        with pytest.raises(providers.ProviderError) as error:
            await providers.begin_connect(source, 'a'*64, transport=httpx.MockTransport(forbidden))
        assert error.value.code == 'not_configured'


@pytest.mark.asyncio
async def test_oauth_url_uses_fixed_origin_exact_scope_and_state_without_secret(configured):
    for source, scope in (('gmail', providers.GMAIL_SCOPE), ('bofa', providers.GMAIL_SCOPE), ('google_ads', providers.ADS_SCOPE)):
        data = await providers.begin_connect(source, 'a'*64)
        url = httpx.URL(data['authorization_url']); query = parse_qs(url.query.decode())
        assert url.host == 'accounts.google.com' and url.path == '/o/oauth2/v2/auth'
        assert query['scope'] == [scope] and query['state'] == ['a'*64]
        assert query['redirect_uri'] == [f'https://t24-crm.com/api/v1/private-workspace/oauth/{source}/callback']
        assert query['access_type'] == ['offline']
        assert 'synthetic-client-secret' not in data['authorization_url']
        assert 'credentials' not in data


@pytest.mark.parametrize('origin', ['http://t24-crm.com', 'https://t24-crm.com/attacker', 'https://t24-crm.com?token=x',
    'https://user:secret@t24-crm.com', 'https://t24-crm.com#fragment', 'https://t24-crm.com:invalid'])
def test_invalid_public_origin_is_not_configured(configured, monkeypatch, origin):
    monkeypatch.setenv('PRIVATE_WORKSPACE_PUBLIC_URL', origin)
    assert 'PRIVATE_WORKSPACE_PUBLIC_URL' in providers.describe_sources()[0]['missing_configuration']


@pytest.mark.asyncio
async def test_google_exchange_sends_secret_only_to_fixed_form_endpoint(configured):
    calls = []
    async def handler(request):
        calls.append(request)
        if request.url.host == 'oauth2.googleapis.com':
            return httpx.Response(200, json={'access_token': 'issued-access', 'refresh_token': 'issued-refresh',
                'expires_in': 3600, 'token_type': 'Bearer', 'scope': providers.GMAIL_SCOPE})
        return httpx.Response(200, json={'emailAddress': 'owner@example.com'})
    data = await providers.complete_connect('gmail', 'one-time-code', transport=httpx.MockTransport(handler))
    assert [(request.method, request.url.host) for request in calls] == [('POST', 'oauth2.googleapis.com'), ('GET', 'gmail.googleapis.com')]
    form = parse_qs(calls[0].content.decode())
    assert form['client_secret'] == ['synthetic-client-secret']
    assert form['code'] == ['one-time-code']
    assert data['credentials']['refresh_token'] == 'issued-refresh'
    assert 'synthetic-client-secret' not in json.dumps(data)
    assert data['metadata']['account_label'] == 'owner@example.com'


@pytest.mark.asyncio
@pytest.mark.parametrize('expected,account,allowed', [
    (None, 'another@example.com', True),
    ('owner@example.com', 'OWNER@EXAMPLE.COM', True),
    ('owner@example.com', 'another@example.com', False),
    ('owner@example.com', 'owner+alias@example.com', False),
])
async def test_optional_gmail_account_check_uses_actual_profile(configured, monkeypatch, expected, account, allowed):
    if expected: monkeypatch.setenv('PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT', expected)
    calls = []
    async def handler(request):
        calls.append(request)
        if request.url.host == 'oauth2.googleapis.com':
            return httpx.Response(200, json={'access_token': 'issued-access', 'scope': providers.GMAIL_SCOPE})
        assert request.url.path.endswith('/profile')
        return httpx.Response(200, json={'emailAddress': account})
    if allowed:
        result = await providers.complete_connect('gmail', 'one-time-code', transport=httpx.MockTransport(handler))
        assert result['metadata']['account_label'] == account
    else:
        with pytest.raises(providers.ProviderError) as error:
            await providers.complete_connect('gmail', 'one-time-code', transport=httpx.MockTransport(handler))
        assert error.value.code == 'access_denied'
        assert account not in str(error.value) and 'issued-access' not in str(error.value)
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('account', [None, '', 'not-an-email', 'owner@example.com\n', 'owner@example.com?token=x'])
async def test_missing_or_malformed_profile_is_not_a_connected_mailbox(configured, account):
    async def handler(request):
        if request.url.host == 'oauth2.googleapis.com':
            return httpx.Response(200, json={'access_token': 'issued-access', 'scope': providers.GMAIL_SCOPE})
        return httpx.Response(200, json={'emailAddress': account})
    with pytest.raises(providers.ProviderError) as error:
        await providers.complete_connect('gmail', 'one-time-code', transport=httpx.MockTransport(handler))
    assert error.value.code == 'invalid_response'


@pytest.mark.asyncio
async def test_gmail_account_configuration_does_not_restrict_bofa_or_ads(configured, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT', 'owner@example.com')
    async def handler(request):
        if request.url.host == 'oauth2.googleapis.com':
            return httpx.Response(200, json={'access_token': 'issued-access', 'scope': providers.GMAIL_SCOPE})
        return httpx.Response(200, json={'emailAddress': 'different@example.com'})
    result = await providers.complete_connect('bofa', 'one-time-code', transport=httpx.MockTransport(handler))
    assert result['metadata']['account_label'] == 'different@example.com'
    monkeypatch.setenv('PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT', 'bad-account')
    descriptors = {row['id']: row for row in providers.describe_sources()}
    assert descriptors['gmail']['missing_configuration'] == ['PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT']
    assert descriptors['google_ads']['missing_configuration'] == []
    assert descriptors['bofa']['missing_configuration'] == []
    await providers.begin_connect('google_ads', 'a' * 64)
    async def forbidden(request): raise AssertionError('Invalid account configuration must not make a request')
    with pytest.raises(providers.ProviderError) as error:
        await providers.complete_connect('gmail', 'one-time-code', transport=httpx.MockTransport(forbidden))
    assert error.value.code == 'not_configured'


@pytest.mark.asyncio
async def test_exchange_rejects_wrong_scope_without_fetching_mail(configured):
    calls = []
    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'access_token': 'wrong-scope-token', 'scope': 'https://www.googleapis.com/auth/drive'})
    with pytest.raises(providers.ProviderError) as error:
        await providers.complete_connect('gmail', 'one-time-code', transport=httpx.MockTransport(handler))
    assert error.value.code == 'access_denied' and len(calls) == 1


@pytest.mark.asyncio
async def test_gmail_metadata_only_and_stable_ids_exclude_full_body(configured):
    calls = []
    async def handler(request):
        calls.append(request)
        if request.url.path.endswith('/messages'):
            assert request.url.params['q'] == 'newer_than:60d {in:inbox is:important is:starred}'
            return httpx.Response(200, json={'messages': [{'id': 'a1'}]})
        assert request.url.params['format'] == 'metadata'
        return httpx.Response(200, json=message())
    batch = await providers.fetch_source('gmail', GOOGLE, {'account_label': 'owner+private@example.com'}, transport=httpx.MockTransport(handler))
    item = batch['items'][0]
    assert item['external_id'] == 'a1' and item['kind'] == 'email' and item['status'] == 'unread'
    assert item['source_url'] == 'https://mail.google.com/mail/u/?authuser=owner%2Bprivate%40example.com#all/b2'
    assert item['evidence']['from'] == 'Sender <sender@example.com>'
    assert item['evidence']['sender_verification'] == 'unverified'
    assert 'FULL_MAIL_BODY' not in json.dumps(batch) and 'synthetic-access' not in json.dumps(batch)
    assert batch['metadata']['sync_window'] == 'last_60_days'
    assert all(request.method == 'GET' and not request.url.params.get('access_token') for request in calls)


@pytest.mark.asyncio
async def test_mailbox_unknown_does_not_open_default_account_and_sender_header_is_bounded(configured):
    async def handler(request):
        if request.url.path.endswith('/messages'):
            return httpx.Response(200, json={'messages': [{'id': 'a1'}]})
        return httpx.Response(200, json=message(sender='Impersonated Bank\r\n' + 'A' * 400 + '<sender@example.com>'))
    result = await providers.fetch_source('gmail', GOOGLE, {}, transport=httpx.MockTransport(handler))
    row = result['items'][0]
    assert row['source_url'] is None
    assert len(row['evidence']['from']) == 300 and '\r' not in row['evidence']['from'] and '\n' not in row['evidence']['from']
    assert row['evidence']['sender_verification'] == 'unverified'


@pytest.mark.asyncio
@pytest.mark.parametrize('metadata', [{}, {'account_label': ''}, {'account_label': None}])
async def test_configured_mailbox_requires_confirmed_identity_before_sync(configured, monkeypatch, metadata):
    monkeypatch.setenv('PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT', 'owner@example.com')
    calls = []
    async def forbidden(request):
        calls.append(request)
        raise AssertionError('An unidentified mailbox must not fetch messages or refresh a token')
    with pytest.raises(providers.ProviderError) as error:
        await providers.fetch_source('gmail', GOOGLE, metadata, transport=httpx.MockTransport(forbidden))
    assert error.value.code == 'authorization_expired' and '重新连接' in str(error.value)
    assert calls == [] and 'owner@example.com' not in str(error.value) and 'synthetic-access' not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('labels', [['UNREAD', 'IMPORTANT'], ['STARRED'], ['UNREAD']])
async def test_gmail_labels_are_evidence_not_automatic_personal_urgency(configured, labels):
    async def handler(request):
        if request.url.path.endswith('/messages'):
            assert request.url.params['q'] == 'newer_than:60d {in:inbox is:important is:starred}'
            return httpx.Response(200, json={'messages': [{'id': 'a1'}]})
        return httpx.Response(200, json={**message(), 'labelIds': labels})
    batch = await providers.fetch_source('gmail', GOOGLE, {}, transport=httpx.MockTransport(handler))
    assert batch['items'][0]['priority'] == 'normal'
    assert batch['items'][0]['evidence']['labels'] == labels
    assert batch['metadata']['importance_source'] == 'owner_metadata_rules'


@pytest.mark.asyncio
async def test_gmail_refresh_once_on_explicit_401_rotates_credentials_only_for_core(configured):
    calls = []
    async def handler(request):
        calls.append(request)
        if request.url.host == 'oauth2.googleapis.com':
            return httpx.Response(200, json={'access_token': 'rotated-access', 'refresh_token': 'rotated-refresh', 'scope': providers.GMAIL_SCOPE})
        if request.headers['authorization'] == 'Bearer synthetic-access': return httpx.Response(401, json={'token': 'DO_NOT_EXPOSE'})
        return httpx.Response(200, json={'messages': []})
    batch = await providers.fetch_source('gmail', GOOGLE, {}, transport=httpx.MockTransport(handler))
    assert len(calls) == 3 and batch['credentials']['access_token'] == 'rotated-access'
    assert batch['credentials']['refresh_token'] == 'rotated-refresh'
    assert GOOGLE['access_token'] == 'synthetic-access'
    assert calls[1].url.path == '/token' and calls[1].method == 'POST'
    assert 'DO_NOT_EXPOSE' not in json.dumps(batch)


@pytest.mark.asyncio
async def test_expired_token_refreshes_before_any_data_request(configured):
    calls = []
    async def handler(request):
        calls.append(request)
        if request.url.host == 'oauth2.googleapis.com': return httpx.Response(200, json={'access_token': 'fresh-access'})
        return httpx.Response(200, json={'messages': []})
    await providers.fetch_source('gmail', {**GOOGLE, 'expires_at': 1}, {}, transport=httpx.MockTransport(handler))
    assert len(calls) == 2 and calls[0].url.host == 'oauth2.googleapis.com'


@pytest.mark.asyncio
async def test_second_explicit_401_does_not_loop(configured):
    calls = []
    async def handler(request):
        calls.append(request)
        if request.url.host == 'oauth2.googleapis.com': return httpx.Response(200, json={'access_token': 'still-rejected'})
        return httpx.Response(401, json={'error': 'secret-error'})
    with pytest.raises(providers.ProviderError) as error:
        await providers.fetch_source('gmail', GOOGLE, {}, transport=httpx.MockTransport(handler))
    assert len(calls) == 3 and error.value.code == 'authorization_expired'
    assert 'secret' not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code', [(403, 'access_denied'), (429, 'rate_limited'), (503, 'upstream_unavailable')])
async def test_rejections_are_sanitized_without_refresh_or_partial_success(configured, status, code):
    calls = []
    async def handler(request):
        calls.append(request); return httpx.Response(status, json={'error': {'message': 'Bearer secret', 'key': KEY}})
    with pytest.raises(providers.ProviderError) as error:
        await providers.fetch_source('gmail', GOOGLE, {}, transport=httpx.MockTransport(handler))
    assert len(calls) == 1 and error.value.code == code and KEY not in str(error.value)


@pytest.mark.asyncio
async def test_gmail_bounded_pages_report_partial_instead_of_complete_mailbox(configured):
    calls = []
    async def handler(request):
        calls.append(request)
        if request.url.path.endswith('/messages'):
            page = int(request.url.params.get('pageToken') or 0)
            return httpx.Response(200, json={'messages': [{'id': 'm'+str(page*20+n)} for n in range(20)], 'nextPageToken': str(page + 1)})
        return httpx.Response(200, json=message(request.url.path.rsplit('/', 1)[1]))
    batch = await providers.fetch_source('gmail', GOOGLE, {}, transport=httpx.MockTransport(handler))
    assert len(batch['items']) == 80 and len(calls) == 84
    assert batch['metadata']['record_limit'] == 80
    assert batch['metadata']['partial'] is True and batch['metadata']['coverage'] == 'bounded_recent_records'


@pytest.mark.asyncio
async def test_bofa_filters_sender_domain_and_keeps_all_alerts_unverified(configured):
    senders = {'real': 'Bank <online@ealerts.bankofamerica.com>', 'spoof': 'Bank <online@bankofamerica.com.evil.com>',
               'display': 'Bankofamerica.com <attacker@example.com>', 'bofa': 'Bank <alert@bofa.com>'}
    async def handler(request):
        if request.url.path.endswith('/messages'):
            assert 'from:bankofamerica.com' in request.url.params['q']
            return httpx.Response(200, json={'messages': [{'id': key} for key in senders]})
        identity = request.url.path.rsplit('/', 1)[1]
        return httpx.Response(200, json=message(identity, senders[identity]))
    batch = await providers.fetch_source('bofa', GOOGLE, {}, transport=httpx.MockTransport(handler))
    assert {row['external_id'] for row in batch['items']} == {'real', 'bofa'}
    assert batch['balances'] == []
    assert all(row['status'] == 'unverified' and row['kind'] == 'email_alert' and 'amount_minor' not in row for row in batch['items'])
    assert all(row['evidence']['verification'] == 'unverified' and row['evidence']['accounting_effect'] == 'none' for row in batch['items'])


@pytest.mark.asyncio
async def test_google_ads_uses_only_fixed_read_search_rpc_and_keeps_original_micros(configured, monkeypatch):
    monkeypatch.setenv('GOOGLE_ADS_DEVELOPER_TOKEN', 'obsolete-value-is-not-used')
    monkeypatch.setenv('GOOGLE_ADS_LOGIN_CUSTOMER_ID', '999-888-7777'); calls = []
    async def handler(request):
        calls.append(request); query = json.loads(request.content)['query']
        assert request.method == 'POST' and request.url.path == '/v25/customers/1234567890/googleAds:search'
        assert 'developer-token' not in request.headers
        assert request.headers['login-customer-id'] == '9998887777'
        if query == providers.ADS_ACCOUNT_QUERY: return httpx.Response(200, json={'results': [{'customer': {'id': '1234567890', 'currencyCode': 'JPY'}}]})
        assert query == providers.ADS_CAMPAIGN_QUERY
        return httpx.Response(200, json={'results': [campaign()]})
    batch = await providers.fetch_source('google_ads', {**GOOGLE, 'scope': providers.ADS_SCOPE}, {'ads_customer_id': '1234567890'}, transport=httpx.MockTransport(handler))
    item = batch['items'][0]
    assert len(calls) == 2 and item['evidence']['cost_micros'] == 1000501 and 'amount_minor' not in item
    assert item['status'] == 'ENABLED' and item['currency'] == 'jpy'
    assert item['source_url'] == 'https://ads.google.com/aw/overview' and 'ocid' not in item['source_url']
    assert '1.000501 JPY' in item['summary'] and '不含今天' in item['summary'] and batch['metadata']['aggregated_totals'] is False
    assert batch['metadata']['ads_customer_id'] == '1234567890'


@pytest.mark.asyncio
async def test_google_ads_limit_probe_marks_truncation_even_without_next_page_token(configured):
    async def handler(request):
        if json.loads(request.content)['query'] == providers.ADS_ACCOUNT_QUERY:
            return httpx.Response(200, json={'results': [{'customer': {'id': '1234567890', 'currencyCode': 'USD'}}]})
        return httpx.Response(200, json={'results': [campaign(identity) for identity in range(101)]})
    batch = await providers.fetch_source('google_ads', {**GOOGLE, 'scope': providers.ADS_SCOPE}, {'ads_customer_id': '1234567890'}, transport=httpx.MockTransport(handler))
    assert len(batch['items']) == 100 and batch['metadata']['partial'] is True


@pytest.mark.asyncio
async def test_google_ads_connect_without_developer_token_confirms_single_advertiser(configured):
    assert next(row for row in providers.describe_sources() if row['id'] == 'google_ads')['missing_configuration'] == []
    calls = []
    async def handler(request):
        calls.append(request)
        if request.url.host == 'oauth2.googleapis.com':
            assert parse_qs(request.content.decode())['redirect_uri'] == ['https://t24-crm.com/api/v1/private-workspace/oauth/google_ads/callback']
            return httpx.Response(200, json={'access_token': 'issued-access', 'refresh_token': 'issued-refresh', 'scope': providers.ADS_SCOPE})
        assert request.method == 'POST' and request.url.path == '/v25/customers/1234567890/googleAds:search'
        assert json.loads(request.content)['query'] == providers.ADS_ACCOUNT_QUERY
        assert request.headers['authorization'] == 'Bearer issued-access'
        assert 'developer-token' not in request.headers and 'login-customer-id' not in request.headers
        return httpx.Response(200, json={'results': [{'customer': {'id': '1234567890', 'descriptiveName': 'Verified advertiser', 'currencyCode': 'USD', 'manager': False}}]})
    connected = await providers.complete_connect('google_ads', 'one-time-code', transport=httpx.MockTransport(handler))
    assert len(calls) == 2 and connected['metadata']['ads_customer_id'] == '1234567890'
    assert connected['metadata']['account_label'] == 'Verified advertiser'
    assert connected['metadata']['scope'] == providers.ADS_SCOPE and connected['metadata']['read_only_adapter'] is True
    assert 'gmail' not in json.dumps(connected['metadata']) and 'issued-access' not in json.dumps(connected['metadata'])


@pytest.mark.asyncio
@pytest.mark.parametrize('returned,code', [
    ({'id': '9998887777', 'currencyCode': 'USD'}, 'access_denied'),
    ({'id': '1234567890', 'currencyCode': 'USD', 'manager': True}, 'ads_manager_account'),
    ({'id': '1234567890', 'currencyCode': 'USD', 'manager': 'false'}, 'invalid_response'),
])
async def test_google_ads_connect_rejects_wrong_or_manager_account(configured, returned, code):
    calls = []
    async def handler(request):
        calls.append(request)
        if request.url.host == 'oauth2.googleapis.com':
            return httpx.Response(200, json={'access_token': 'issued-access', 'scope': providers.ADS_SCOPE})
        return httpx.Response(200, json={'results': [{'customer': returned}]})
    with pytest.raises(providers.ProviderError) as error:
        await providers.complete_connect('google_ads', 'one-time-code', transport=httpx.MockTransport(handler))
    assert error.value.code == code and len(calls) == 2
    assert 'issued-access' not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('metadata', [{}, {'ads_customer_id': '9998887777'}, {'ads_customer_id': '123-456-7890'}, {'ads_customer_id': 1234567890}])
async def test_google_ads_sync_requires_exact_bound_account_before_any_request(configured, metadata):
    async def forbidden(request): raise AssertionError('Changed or unidentified target must not refresh or fetch any account')
    with pytest.raises(providers.ProviderError) as error:
        await providers.fetch_source('google_ads', {**GOOGLE, 'expires_at': 1, 'scope': providers.ADS_SCOPE}, metadata, transport=httpx.MockTransport(forbidden))
    assert error.value.code == 'ads_account_changed' and '重新连接' in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [400, 403])
async def test_ads_project_production_approval_error_is_fixed_safe_guidance(configured, status):
    async def handler(request):
        if request.url.host == 'oauth2.googleapis.com':
            return httpx.Response(200, json={'access_token': 'issued-access', 'scope': providers.ADS_SCOPE})
        return httpx.Response(status, json={'error': {'message': 'Bearer DO_NOT_EXPOSE private-account', 'details': [
            {'errors': [{'errorCode': {'authorizationError': 'CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION'}, 'message': 'PRIVATE RAW DETAILS'}]}]}})
    with pytest.raises(providers.ProviderError) as error:
        await providers.complete_connect('google_ads', 'one-time-code', transport=httpx.MockTransport(handler))
    assert error.value.code == 'ads_project_not_approved' and 'Explorer' in str(error.value)
    assert not error.value.retryable and 'DO_NOT_EXPOSE' not in str(error.value) and 'PRIVATE' not in str(error.value)


@pytest.mark.asyncio
async def test_ads_error_message_text_cannot_invent_approval_error(configured):
    async def handler(request):
        return httpx.Response(403, json={'error': {'message': 'CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION Bearer DO_NOT_EXPOSE', 'details': [
            {'errors': [{'errorCode': {'authorizationError': 'USER_PERMISSION_DENIED'}}]}]}})
    with pytest.raises(providers.ProviderError) as error:
        await providers.fetch_source('google_ads', {**GOOGLE, 'scope': providers.ADS_SCOPE}, {'ads_customer_id': '1234567890'}, transport=httpx.MockTransport(handler))
    assert error.value.code == 'access_denied' and 'DO_NOT_EXPOSE' not in str(error.value)


@pytest.mark.asyncio
async def test_stripe_restricted_key_connect_validates_balance_read_only(configured):
    calls = []
    async def handler(request):
        calls.append(request); return httpx.Response(200, json=balance())
    connected = await providers.begin_connect('stripe', '', transport=httpx.MockTransport(handler))
    assert connected['credentials'] == {'api_key': KEY} and len(calls) == 1
    assert calls[0].method == 'GET' and str(calls[0].url) == 'https://api.stripe.com/v1/balance'
    assert KEY not in json.dumps(connected['metadata'])


@pytest.mark.parametrize('key', ['sk_live_unsafe1234567890', 'pk_live_public1234567890', 'rk_live_bad\nAuthorization:evil', 'placeholder'])
def test_unrestricted_or_invalid_stripe_key_cannot_be_configured(configured, monkeypatch, key):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_KEY', key)
    stripe = next(row for row in providers.describe_sources() if row['id'] == 'stripe')
    assert stripe['status'] == 'not_configured'


@pytest.mark.asyncio
async def test_stripe_preserves_status_minor_units_and_distinguishes_payouts_from_income(configured):
    calls = []
    async def handler(request):
        calls.append(request)
        assert request.method == 'GET' and request.url.host == 'api.stripe.com'
        assert request.headers['authorization'] == 'Bearer '+KEY and KEY not in str(request.url)
        if request.url.path == '/v1/balance': return httpx.Response(200, json=balance())
        resource = request.url.path.rsplit('/', 1)[1]
        return httpx.Response(200, json={'data': [stripe_row(resource)], 'has_more': False})
    batch = await providers.fetch_source('stripe', {'api_key': KEY}, {}, transport=httpx.MockTransport(handler))
    assert len(calls) == 5 and {row['kind'] for row in batch['items']} == {'payment', 'refund', 'dispute', 'payout'}
    assert all(row['amount_minor'] == 1 and row['currency'] == 'jpy' for row in batch['items'])
    payout = next(row for row in batch['items'] if row['kind'] == 'payout')
    assert payout['status'] == 'in_transit' and payout['evidence']['funds_movement'] == 'stripe_balance_to_bank'
    assert batch['metadata']['payouts_are_income'] is False and batch['metadata']['aggregated_totals'] is False
    assert next(row for row in batch['balances'] if row['currency'] == 'usd')['available_minor'] == -123
    assert KEY not in json.dumps(batch)


@pytest.mark.asyncio
async def test_stripe_paging_is_bounded_and_has_resource_specific_coverage(configured):
    calls = []
    async def handler(request):
        calls.append(request)
        if request.url.path == '/v1/balance': return httpx.Response(200, json=balance())
        if request.url.path != '/v1/charges': return httpx.Response(200, json={'data': [], 'has_more': False})
        page = 1 if request.url.params.get('starting_after') else 0
        rows = [{**stripe_row('charges'), 'id': 'ch_'+str(page*50+index)} for index in range(50)]
        return httpx.Response(200, json={'data': rows, 'has_more': True})
    batch = await providers.fetch_source('stripe', {'api_key': KEY}, {}, transport=httpx.MockTransport(handler))
    assert len(batch['items']) == 100 and len(calls) == 6 and batch['metadata']['partial'] is True
    assert batch['metadata']['resources']['charges'] == {'fetched': 100, 'partial': True}


@pytest.mark.asyncio
@pytest.mark.parametrize('method,url,arguments', [('POST', 'https://api.stripe.com/v1/refunds', {}),
    ('GET', 'https://evil.com/v1/balance', {}), ('GET', 'https://api.stripe.com/v1/balance?api_key=secret', {}),
    ('GET', 'http://api.stripe.com/v1/balance', {}), ('GET', 'https://api.stripe.com/v1/balance', {'params': {'access_token': 'secret'}}),
    ('POST', 'https://googleads.googleapis.com/v25/customers/1234567890/googleAds:mutate', {}),
    ('POST', 'https://googleads.googleapis.com/v25/customers/1234567890/googleAds:search', {'json': {'query': 'DELETE arbitrary'}})])
async def test_transport_blocks_writes_arbitrary_hosts_urls_queries_and_token_query(method, url, arguments):
    async def forbidden(request): raise AssertionError('Disallowed outbound request')
    async with providers._Client(httpx.MockTransport(forbidden)) as client:
        with pytest.raises(providers.ProviderError) as error: await client.request(method, url, **arguments)
    assert error.value.code == 'request_not_allowed'


@pytest.mark.asyncio
@pytest.mark.parametrize('data', [{'messages': ['malformed']}, {'messages': [{'id': '../attacker'}]}, {'messages': [{}]}])
async def test_malformed_or_hostile_provider_record_fails_safely(configured, data):
    async def handler(request): return httpx.Response(200, json=data)
    with pytest.raises(providers.ProviderError) as error:
        await providers.fetch_source('gmail', GOOGLE, {}, transport=httpx.MockTransport(handler))
    assert error.value.code == 'invalid_response' and 'attacker' not in str(error.value)


@pytest.mark.asyncio
async def test_upstream_timeout_body_limit_and_deadline_are_sanitized(configured, monkeypatch):
    async def timeout(request): raise httpx.ReadTimeout('secret upstream URL', request=request)
    with pytest.raises(providers.ProviderError) as error:
        await providers.fetch_source('gmail', GOOGLE, {}, transport=httpx.MockTransport(timeout))
    assert error.value.code == 'upstream_timeout' and 'secret' not in str(error.value)
    async def too_large(request): return httpx.Response(200, content=b'x'*(providers.MAX_RESPONSE_BYTES+1))
    with pytest.raises(providers.ProviderError) as error:
        await providers.fetch_source('gmail', GOOGLE, {}, transport=httpx.MockTransport(too_large))
    assert error.value.code == 'invalid_response'
    monkeypatch.setattr(providers, 'MAX_SYNC_SECONDS', 0.001)
    async def slow(request): await asyncio.sleep(0.1); return httpx.Response(200, json={'messages': []})
    with pytest.raises(providers.ProviderError) as error:
        await providers.fetch_source('gmail', GOOGLE, {}, transport=httpx.MockTransport(slow))
    assert error.value.code == 'upstream_timeout'


@pytest.mark.asyncio
async def test_manual_never_calls_network_and_unknown_source_is_rejected():
    async def forbidden(request): raise AssertionError('Manual must be local')
    data = await providers.fetch_source('manual', {}, {}, transport=httpx.MockTransport(forbidden))
    assert data['items'] == data['balances'] == []
    with pytest.raises(providers.ProviderError) as error: await providers.begin_connect('unregistered', '')
    assert error.value.code == 'unknown_source'


@pytest.mark.asyncio
async def test_oauth_refresh_invalid_grant_requires_reconnect_without_body_leak(configured):
    calls = []
    async def handler(request):
        calls.append(request); return httpx.Response(400, json={'error': 'invalid_grant', 'error_description': 'secret-refresh-token'})
    with pytest.raises(providers.ProviderError) as error:
        await providers.fetch_source('gmail', {**GOOGLE, 'expires_at': 1}, {}, transport=httpx.MockTransport(handler))
    assert len(calls) == 1 and calls[0].url.host == 'oauth2.googleapis.com'
    assert error.value.code == 'authorization_expired' and 'secret' not in str(error.value)


@pytest.mark.asyncio
async def test_wrong_source_scope_is_rejected_before_network(configured):
    async def forbidden(request): raise AssertionError('Wrong scope must not call provider')
    with pytest.raises(providers.ProviderError) as error:
        await providers.fetch_source('google_ads', GOOGLE, {}, transport=httpx.MockTransport(forbidden))
    assert error.value.code == 'access_denied'


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [{'access_token': 'token', 'expires_in': 0},
    {'access_token': 'token', 'token_type': 123}, {'access_token': 'bad\r\nInjected:secret'}, {'expires_in': 3600}])
async def test_malformed_token_response_is_sanitized_and_never_connected(configured, response):
    async def handler(request): return httpx.Response(200, json=response)
    with pytest.raises(providers.ProviderError):
        await providers.complete_connect('gmail', 'one-time-code', transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_stripe_second_resource_failure_does_not_return_partial_success(configured):
    calls = []
    async def handler(request):
        calls.append(request)
        if request.url.path == '/v1/balance': return httpx.Response(200, json=balance())
        if request.url.path == '/v1/charges': return httpx.Response(200, json={'data': [stripe_row('charges')], 'has_more': False})
        return httpx.Response(403, json={'key': KEY, 'message': 'missing secret permission'})
    with pytest.raises(providers.ProviderError) as error:
        await providers.fetch_source('stripe', {'api_key': KEY}, {}, transport=httpx.MockTransport(handler))
    assert len(calls) == 3 and error.value.code == 'access_denied' and KEY not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [
    {'data': [], 'has_more': True},
    {'data': [stripe_row('charges'), stripe_row('charges')], 'has_more': False},
    {'data': [{**stripe_row('charges'), 'amount': 1.5}], 'has_more': False},
    {'data': [{**stripe_row('charges'), 'currency': 'not-currency'}], 'has_more': False},
    {'data': [{**stripe_row('charges'), 'id': 'ch_../../redirect'}], 'has_more': False}])
async def test_stripe_malformed_paging_amount_currency_or_identifier_fails_closed(configured, response):
    async def handler(request):
        return httpx.Response(200, json=balance() if request.url.path == '/v1/balance' else response)
    with pytest.raises(providers.ProviderError) as error:
        await providers.fetch_source('stripe', {'api_key': KEY}, {}, transport=httpx.MockTransport(handler))
    assert error.value.code == 'invalid_response'


@pytest.mark.asyncio
async def test_duplicate_balance_currency_is_rejected_instead_of_double_counted(configured):
    response = balance(); response['available'].append(response['available'][0])
    async def handler(request): return httpx.Response(200, json=response)
    with pytest.raises(providers.ProviderError) as error:
        await providers.fetch_source('stripe', {'api_key': KEY}, {}, transport=httpx.MockTransport(handler))
    assert error.value.code == 'invalid_response'


@pytest.mark.asyncio
async def test_redirect_response_is_never_followed_with_credentials(configured):
    calls = []
    async def handler(request):
        calls.append(request); return httpx.Response(302, headers={'Location': 'https://evil.com/steal'})
    with pytest.raises(providers.ProviderError) as error:
        await providers.fetch_source('gmail', GOOGLE, {}, transport=httpx.MockTransport(handler))
    assert len(calls) == 1 and calls[0].url.host == 'gmail.googleapis.com' and error.value.code == 'invalid_response'


@pytest.mark.asyncio
async def test_request_budget_blocks_before_an_additional_request(monkeypatch):
    monkeypatch.setattr(providers, 'MAX_REQUESTS', 1); calls = []
    async def handler(request): calls.append(request); return httpx.Response(200, json=balance())
    async with providers._Client(httpx.MockTransport(handler)) as client:
        await client.request('GET', 'https://api.stripe.com/v1/balance')
        with pytest.raises(providers.ProviderError) as error:
            await client.request('GET', 'https://api.stripe.com/v1/balance')
    assert len(calls) == 1 and error.value.code == 'sync_limit'


@pytest.mark.asyncio
async def test_stable_external_ids_make_repeat_syncs_idempotent(configured):
    async def handler(request):
        if request.url.path.endswith('/messages'): return httpx.Response(200, json={'messages': [{'id': 'a1'}]})
        return httpx.Response(200, json=message())
    first = await providers.fetch_source('gmail', GOOGLE, {}, transport=httpx.MockTransport(handler))
    second = await providers.fetch_source('gmail', GOOGLE, {}, transport=httpx.MockTransport(handler))
    assert first['items'] == second['items'] and first['items'][0]['external_id'] == 'a1'
