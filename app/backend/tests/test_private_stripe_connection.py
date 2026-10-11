"""Dedicated private Stripe identity, read-only permission and money semantics.

Every provider request uses MockTransport. API tests use isolated fixture databases;
no Stripe credential, real network request or customer financial mutation occurs.
"""
import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from models.private_workspace import PrivateConnection, PrivateItem, utcnow
from services import private_workspace as core, private_workspace_providers as providers
from test_private_workspace_core import workspace, headers
from test_private_workspace_providers import (
    configured, settings, balance, stripe_row, KEY, STRIPE_ACCOUNT, STRIPE_CREDENTIALS, STRIPE_METADATA,
)


def response_for(request, *, account=STRIPE_ACCOUNT, live=False, charges=None):
    if request.url.path == '/v1/account':
        return {'object': 'account', 'id': account, 'business_profile': {'name': 'Synthetic owner account'}}
    if request.url.path == '/v1/balance': return {**balance(), 'livemode': live}
    return {'object': 'list', 'data': charges or [] if request.url.path == '/v1/charges' else [], 'has_more': False}


@pytest.mark.asyncio
async def test_stripe_worker_uses_encrypted_connection_credential_without_environment_key(configured, monkeypatch):
    calls = []
    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response_for(request))
    connected = await providers.begin_connect('stripe', '', transport=httpx.MockTransport(handler))
    monkeypatch.delenv('PRIVATE_WORKSPACE_STRIPE_KEY')
    fetched = await providers.fetch_source('stripe', connected['credentials'], connected['metadata'], transport=httpx.MockTransport(handler))
    assert len(calls) == 12 and all(call.method == 'GET' for call in calls)
    assert fetched['metadata']['stripe_account_id'] == STRIPE_ACCOUNT
    assert fetched['metadata']['stripe_snapshot']['mode'] == 'test'
    assert KEY not in json.dumps(fetched)
    row = SimpleNamespace(status='connected', encrypted_credentials='encrypted', metadata_json=connected['metadata'], error=None, last_sync=None)
    descriptor = next(value for value in providers.describe_sources() if value['id'] == 'stripe')
    assert 'PRIVATE_WORKSPACE_STRIPE_KEY' not in core.source_response(descriptor, row)['missing_configuration']


@pytest.mark.parametrize('changes,expected_sync', [
    ({}, True), ({'error': 'Upstream read failed'}, True),
    ({'status': 'error'}, False), ({'status': 'disconnected'}, False),
    ({'encrypted_credentials': None}, False),
    ({'metadata_json': {'stripe_account_id': 'acct_another12345678', 'mode': 'test'}}, False),
    ({'metadata_json': {'stripe_account_id': STRIPE_ACCOUNT, 'mode': 'live'}}, False),
])
def test_stripe_action_contract_requires_bound_credential_without_one_time_setup_key(configured, monkeypatch, changes, expected_sync):
    monkeypatch.setenv('PRIVATE_WORKSPACE_ENCRYPTION_KEY', 'synthetic-private-action-encryption-only')
    monkeypatch.delenv('PRIVATE_WORKSPACE_STRIPE_KEY')
    row = SimpleNamespace(status='connected', encrypted_credentials='synthetic-encrypted',
                          metadata_json=dict(STRIPE_METADATA), error=None, last_sync=None)
    for key, value in changes.items(): setattr(row, key, value)
    descriptor = next(value for value in providers.describe_sources() if value['id'] == 'stripe')
    source = core.source_response(descriptor, row)
    assert source['action_availability'] == {'can_connect': False, 'can_sync': expected_sync}
    assert 'synthetic-encrypted' not in json.dumps(source)


def test_stripe_action_contract_requires_real_setup_or_complete_sync_configuration(configured, monkeypatch):
    monkeypatch.setenv('PRIVATE_WORKSPACE_ENCRYPTION_KEY', 'synthetic-private-action-encryption-only')
    descriptor = next(value for value in providers.describe_sources() if value['id'] == 'stripe')
    assert core.source_response(descriptor)['action_availability'] == {'can_connect': True, 'can_sync': False}
    row = SimpleNamespace(status='connected', encrypted_credentials='synthetic-encrypted',
                          metadata_json=dict(STRIPE_METADATA), error='Upstream read failed', last_sync=None)
    monkeypatch.delenv('PRIVATE_WORKSPACE_ENCRYPTION_KEY')
    assert core.source_response(descriptor, row)['action_availability'] == {'can_connect': False, 'can_sync': False}


@pytest.mark.asyncio
@pytest.mark.parametrize('resource', ['charges', 'refunds', 'disputes', 'payouts'])
async def test_stripe_connect_does_not_claim_success_with_missing_resource_read_permission(configured, resource):
    calls = []
    async def handler(request):
        calls.append(request)
        if request.url.path == '/v1/' + resource:
            return httpx.Response(403, json={'message': KEY + ' private permission details'})
        return httpx.Response(200, json=response_for(request))
    with pytest.raises(providers.ProviderError) as caught:
        await providers.begin_connect('stripe', '', transport=httpx.MockTransport(handler))
    assert caught.value.code == 'access_denied' and KEY not in str(caught.value)
    assert all(request.method == 'GET' for request in calls)


@pytest.mark.asyncio
async def test_stripe_wrong_account_fails_before_balance_or_record_reads(configured):
    calls = []
    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response_for(request, account='acct_another12345678'))
    with pytest.raises(providers.ProviderError) as caught:
        await providers.begin_connect('stripe', '', transport=httpx.MockTransport(handler))
    assert caught.value.code == 'stripe_account_changed' and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('where', ['balance', 'record'])
async def test_stripe_balance_or_record_mode_cannot_cross_live_and_test(configured, where):
    async def handler(request):
        row = {**stripe_row('charges'), 'livemode': where == 'record'}
        return httpx.Response(200, json=response_for(request, live=where == 'balance', charges=[row]))
    with pytest.raises(providers.ProviderError) as caught:
        await providers.fetch_source('stripe', STRIPE_CREDENTIALS, STRIPE_METADATA, transport=httpx.MockTransport(handler))
    assert caught.value.code == 'stripe_account_changed'


def refund_contract_transport(*, live=False, changes=None, missing_mode_resource=None):
    calls = []

    async def handler(request):
        assert request.method == 'GET'
        calls.append(request.url.path)
        if request.url.path in {'/v1/account', '/v1/balance'}:
            return httpx.Response(200, json=response_for(request, live=live))
        resource = request.url.path.rsplit('/', 1)[1]
        row = stripe_row(resource)
        if resource == 'refunds': row.update(changes or {})
        else: row['livemode'] = live
        if resource == missing_mode_resource: row.pop('livemode', None)
        return httpx.Response(200, json={'object': 'list', 'data': [row], 'has_more': False})

    return httpx.MockTransport(handler), calls


async def read_stripe_contract(phase, mode, transport):
    if phase == 'connect': return await providers.begin_connect('stripe', '', transport=transport)
    key = KEY.replace('rk_test_', 'rk_live_') if mode == 'live' else KEY
    return await providers.fetch_source('stripe',
        {**STRIPE_CREDENTIALS, 'api_key': key, 'mode': mode}, {**STRIPE_METADATA, 'mode': mode}, transport=transport)


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['connect', 'sync'])
@pytest.mark.parametrize('mode', ['test', 'live'])
@pytest.mark.parametrize('explicit_mode', [False, True])
async def test_official_refund_contract_uses_verified_request_mode(configured, monkeypatch, phase, mode, explicit_mode):
    live = mode == 'live'
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_MODE', mode)
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_KEY', KEY.replace('rk_test_', 'rk_live_') if live else KEY)
    transport, calls = refund_contract_transport(live=live, changes={'livemode': live} if explicit_mode else None)
    result = await read_stripe_contract(phase, mode, transport)
    assert calls == ['/v1/account', '/v1/balance', '/v1/charges', '/v1/refunds', '/v1/disputes', '/v1/payouts']
    assert result['metadata']['stripe_account_id'] == STRIPE_ACCOUNT and result['metadata']['mode'] == mode
    if phase == 'sync':
        refund = next(row for row in result['items'] if row['kind'] == 'refund')
        assert refund['evidence']['stripe_account_id'] == STRIPE_ACCOUNT and refund['evidence']['stripe_mode'] == mode
        assert refund['evidence']['accounting_effect'] == 'none' and refund['amount_minor'] == 1
        assert refund['source_url'] == 'https://dashboard.stripe.com/' + ('test/' if not live else '') + 'payments/ch_synthetic1'


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['connect', 'sync'])
@pytest.mark.parametrize('changes,code', [
    ({'livemode': None}, 'invalid_response'), ({'livemode': 0}, 'invalid_response'),
    ({'livemode': 'false'}, 'invalid_response'), ({'livemode': True}, 'stripe_account_changed'),
    ({'object': 'charge'}, 'invalid_response'), ({'object': None}, 'invalid_response'),
])
async def test_refund_contract_rejects_explicit_invalid_mode_or_wrong_object(configured, phase, changes, code):
    transport, calls = refund_contract_transport(changes=changes)
    with pytest.raises(providers.ProviderError) as caught:
        await read_stripe_contract(phase, 'test', transport)
    assert caught.value.code == code
    assert calls == ['/v1/account', '/v1/balance', '/v1/charges', '/v1/refunds']


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['connect', 'sync'])
@pytest.mark.parametrize('resource', ['charges', 'disputes', 'payouts'])
async def test_other_stripe_resources_still_require_explicit_livemode(configured, phase, resource):
    transport, _ = refund_contract_transport(missing_mode_resource=resource)
    with pytest.raises(providers.ProviderError) as caught:
        await read_stripe_contract(phase, 'test', transport)
    assert caught.value.code == 'invalid_response'


def charge_contract_transport(*, live=False, changes=None):
    calls = []

    async def handler(request):
        assert request.method == 'GET'
        calls.append(request.url.path)
        if request.url.path in {'/v1/account', '/v1/balance'}:
            return httpx.Response(200, json=response_for(request, live=live))
        resource = request.url.path.rsplit('/', 1)[1]
        row = stripe_row(resource)
        if resource != 'refunds': row['livemode'] = live
        if resource == 'charges': row.update(changes or {})
        return httpx.Response(200, json={'object': 'list', 'data': [row], 'has_more': False})

    return httpx.MockTransport(handler), calls


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['connect', 'sync'])
@pytest.mark.parametrize('mode', ['test', 'live'])
@pytest.mark.parametrize('prefix', ['ch_', 'py_'])
async def test_official_charge_ids_connect_and_sync_with_bound_mode(configured, monkeypatch, phase, mode, prefix):
    live = mode == 'live'
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_MODE', mode)
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_KEY', KEY.replace('rk_test_', 'rk_live_') if live else KEY)
    identity = prefix + 'FICTIONContract'
    transport, calls = charge_contract_transport(live=live, changes={'id': identity})
    result = await read_stripe_contract(phase, mode, transport)
    assert calls == ['/v1/account', '/v1/balance', '/v1/charges', '/v1/refunds', '/v1/disputes', '/v1/payouts']
    assert result['metadata']['stripe_account_id'] == STRIPE_ACCOUNT and result['metadata']['mode'] == mode
    if phase == 'sync':
        charge = next(row for row in result['items'] if row['kind'] == 'payment')
        assert charge['external_id'] == 'charges:' + identity and charge['amount_minor'] == 1
        assert charge['status'] == 'succeeded' and charge['evidence']['payment_state'] == 'captured'
        assert charge['source_url'] == 'https://dashboard.stripe.com/' + ('test/' if not live else '') + 'payments/' + identity
        assert charge['evidence']['stripe_account_id'] == STRIPE_ACCOUNT and charge['evidence']['stripe_mode'] == mode
        assert charge['evidence']['amount_captured_minor'] == 1 and charge['evidence']['accounting_effect'] == 'none'


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['connect', 'sync'])
@pytest.mark.parametrize('changes,code', [
    ({'object': None}, 'invalid_response'), ({'object': 'refund'}, 'invalid_response'),
    ({'id': 're_FICTIONContract'}, 'invalid_response'), ({'id': 'pyr_FICTIONContract'}, 'invalid_response'),
    ({'id': 'ch_'}, 'invalid_response'), ({'id': 'py_'}, 'invalid_response'),
    ({'id': 'py_../../redirect'}, 'invalid_response'), ({'id': 'py_bad-tail'}, 'invalid_response'),
    ({'id': False}, 'invalid_response'), ({'livemode': None}, 'invalid_response'),
    ({'livemode': True}, 'stripe_account_changed'),
])
async def test_charge_contract_rejects_invalid_resource_id_and_mode(configured, phase, changes, code):
    transport, calls = charge_contract_transport(changes=changes)
    with pytest.raises(providers.ProviderError) as caught:
        await read_stripe_contract(phase, 'test', transport)
    assert caught.value.code == code and calls == ['/v1/account', '/v1/balance', '/v1/charges']


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['test', 'live'])
@pytest.mark.parametrize('prefix', ['ch_', 'py_'])
async def test_charge_id_contract_controls_cursor_and_mixed_prefix_pages(configured, monkeypatch, mode, prefix):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_MODE', mode)
    cursors = []
    other_prefix = 'py_' if prefix == 'ch_' else 'ch_'

    async def handler(request):
        assert request.method == 'GET'
        if request.url.path in {'/v1/account', '/v1/balance'}:
            return httpx.Response(200, json=response_for(request, live=mode == 'live'))
        if request.url.path != '/v1/charges':
            return httpx.Response(200, json={'object': 'list', 'data': [], 'has_more': False})
        cursors.append(request.url.params.get('starting_after'))
        identity = prefix + 'First' if len(cursors) == 1 else other_prefix + 'Second'
        row = {**stripe_row('charges'), 'id': identity, 'livemode': mode == 'live'}
        return httpx.Response(200, json={'object': 'list', 'data': [row], 'has_more': len(cursors) == 1})

    result = await read_stripe_contract('sync', mode, httpx.MockTransport(handler))
    assert cursors == [None, prefix + 'First']
    assert [row['external_id'] for row in result['items']] == ['charges:' + prefix + 'First', 'charges:' + other_prefix + 'Second']
    assert result['metadata']['resources']['charges'] == {'fetched': 2, 'partial': False}


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['test', 'live'])
@pytest.mark.parametrize('prefix', ['ch_', 'py_'])
async def test_charge_duplicate_ids_across_pages_still_fail_closed(configured, monkeypatch, mode, prefix):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_MODE', mode)
    requests = []

    async def handler(request):
        assert request.method == 'GET'
        requests.append(request)
        if request.url.path in {'/v1/account', '/v1/balance'}:
            return httpx.Response(200, json=response_for(request, live=mode == 'live'))
        row = {**stripe_row('charges'), 'id': prefix + 'Repeated', 'livemode': mode == 'live'}
        return httpx.Response(200, json={'object': 'list', 'data': [row], 'has_more': True})

    with pytest.raises(providers.ProviderError) as caught:
        await read_stripe_contract('sync', mode, httpx.MockTransport(handler))
    assert caught.value.code == 'invalid_response'
    assert [request.url.path for request in requests] == ['/v1/account', '/v1/balance', '/v1/charges', '/v1/charges']


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['test', 'live'])
@pytest.mark.parametrize('prefix', ['ch_', 'py_'])
@pytest.mark.parametrize('expanded', [False, True])
async def test_refund_links_accept_only_valid_charge_ids_in_both_forms(configured, monkeypatch, mode, prefix, expanded):
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_MODE', mode)
    identity = prefix + 'FICTIONRefundCharge'
    charge = {'id': identity, 'object': 'charge'} if expanded else identity
    transport, calls = refund_contract_transport(live=mode == 'live', changes={'charge': charge})
    result = await read_stripe_contract('sync', mode, transport)
    refund = next(row for row in result['items'] if row['kind'] == 'refund')
    assert calls == ['/v1/account', '/v1/balance', '/v1/charges', '/v1/refunds', '/v1/disputes', '/v1/payouts']
    assert refund['source_url'] == 'https://dashboard.stripe.com/' + ('test/' if mode == 'test' else '') + 'payments/' + identity
    assert refund['evidence']['stripe_account_id'] == STRIPE_ACCOUNT and refund['evidence']['stripe_mode'] == mode
    assert refund['evidence']['accounting_effect'] == 'none'


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['connect', 'sync'])
@pytest.mark.parametrize('charge', ['py_', 'py_../../redirect', 'pi_FICTIONContract', {'id': 'du_FICTIONContract'}])
async def test_refund_charge_link_rejects_invalid_or_cross_resource_ids(configured, phase, charge):
    transport, calls = refund_contract_transport(changes={'charge': charge})
    with pytest.raises(providers.ProviderError) as caught:
        await read_stripe_contract(phase, 'test', transport)
    assert caught.value.code == 'invalid_response'
    assert calls == ['/v1/account', '/v1/balance', '/v1/charges', '/v1/refunds']


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['connect', 'sync'])
@pytest.mark.parametrize('resource', ['refunds', 'disputes', 'payouts'])
async def test_payment_id_prefix_is_not_accepted_for_other_resources(configured, phase, resource):
    async def handler(request):
        if request.url.path in {'/v1/account', '/v1/balance'}:
            return httpx.Response(200, json=response_for(request))
        requested = request.url.path.rsplit('/', 1)[1]
        row = stripe_row(requested)
        if requested == resource: row['id'] = 'py_FICTIONContract'
        return httpx.Response(200, json={'object': 'list', 'data': [row], 'has_more': False})

    with pytest.raises(providers.ProviderError) as caught:
        await read_stripe_contract(phase, 'test', httpx.MockTransport(handler))
    assert caught.value.code == 'invalid_response'


def dispute_contract_transport(*, live=False, changes=None):
    calls = []

    async def handler(request):
        assert request.method == 'GET'
        calls.append(request.url.path)
        if request.url.path in {'/v1/account', '/v1/balance'}:
            return httpx.Response(200, json=response_for(request, live=live))
        resource = request.url.path.rsplit('/', 1)[1]
        row = stripe_row(resource)
        if resource != 'refunds': row['livemode'] = live
        if resource == 'disputes': row.update(changes or {})
        return httpx.Response(200, json={'object': 'list', 'data': [row], 'has_more': False})

    return httpx.MockTransport(handler), calls


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['connect', 'sync'])
@pytest.mark.parametrize('mode', ['test', 'live'])
@pytest.mark.parametrize('prefix', ['du_', 'dp_'])
async def test_dispute_contract_preserves_current_and_existing_ids_in_bound_modes(configured, monkeypatch, phase, mode, prefix):
    live = mode == 'live'
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_MODE', mode)
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_KEY', KEY.replace('rk_test_', 'rk_live_') if live else KEY)
    identity = prefix + '1FICTIONContract'
    transport, calls = dispute_contract_transport(live=live, changes={'id': identity, 'status': 'warning_needs_response'})
    result = await read_stripe_contract(phase, mode, transport)
    assert calls == ['/v1/account', '/v1/balance', '/v1/charges', '/v1/refunds', '/v1/disputes', '/v1/payouts']
    assert result['metadata']['stripe_account_id'] == STRIPE_ACCOUNT and result['metadata']['mode'] == mode
    if phase == 'sync':
        dispute = next(row for row in result['items'] if row['kind'] == 'dispute')
        assert dispute['external_id'] == 'disputes:' + identity
        assert dispute['status'] == 'warning_needs_response' and dispute['priority'] == 'high'
        assert dispute['due_at'] == '2023-11-14T22:30:00+00:00'
        assert dispute['source_url'] == 'https://dashboard.stripe.com/' + ('test/' if not live else '') + 'disputes/' + identity
        assert dispute['evidence']['stripe_account_id'] == STRIPE_ACCOUNT and dispute['evidence']['stripe_mode'] == mode
        assert dispute['evidence']['accounting_effect'] == 'none'


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['connect', 'sync'])
@pytest.mark.parametrize('changes,code', [
    ({'object': None}, 'invalid_response'), ({'object': 'charge'}, 'invalid_response'),
    ({'id': 're_FICTIONContract'}, 'invalid_response'), ({'id': 'du_'}, 'invalid_response'),
    ({'id': 'dp_'}, 'invalid_response'), ({'id': 'du_../../redirect'}, 'invalid_response'),
    ({'id': False}, 'invalid_response'), ({'livemode': None}, 'invalid_response'),
    ({'livemode': 'false'}, 'invalid_response'), ({'livemode': True}, 'stripe_account_changed'),
])
async def test_dispute_contract_rejects_wrong_resource_invalid_id_or_mode(configured, phase, changes, code):
    transport, calls = dispute_contract_transport(changes=changes)
    with pytest.raises(providers.ProviderError) as caught:
        await read_stripe_contract(phase, 'test', transport)
    assert caught.value.code == code
    assert calls == ['/v1/account', '/v1/balance', '/v1/charges', '/v1/refunds', '/v1/disputes']


@pytest.mark.asyncio
@pytest.mark.parametrize('prefix', ['du_', 'dp_'])
async def test_dispute_id_contract_is_used_for_bounded_cursor_pages(configured, prefix):
    cursors = []

    async def handler(request):
        assert request.method == 'GET'
        if request.url.path in {'/v1/account', '/v1/balance'}:
            return httpx.Response(200, json=response_for(request))
        if request.url.path != '/v1/disputes':
            return httpx.Response(200, json={'object': 'list', 'data': [], 'has_more': False})
        cursor = request.url.params.get('starting_after')
        cursors.append(cursor)
        index = len(cursors)
        return httpx.Response(200, json={'object': 'list', 'data': [{**stripe_row('disputes'), 'id': prefix + str(index)}],
                                        'has_more': index == 1})

    result = await providers.fetch_source('stripe', STRIPE_CREDENTIALS, STRIPE_METADATA, transport=httpx.MockTransport(handler))
    assert cursors == [None, prefix + '1']
    assert [row['external_id'] for row in result['items']] == ['disputes:' + prefix + '1', 'disputes:' + prefix + '2']
    assert result['metadata']['resources']['disputes'] == {'fetched': 2, 'partial': False}


@pytest.mark.asyncio
@pytest.mark.parametrize('prefix', ['du_', 'dp_'])
async def test_dispute_duplicate_id_across_pages_still_fails_closed(configured, prefix):
    calls = []

    async def handler(request):
        calls.append(request)
        if request.url.path in {'/v1/account', '/v1/balance'}:
            return httpx.Response(200, json=response_for(request))
        rows = [{**stripe_row('disputes'), 'id': prefix + '1'}] if request.url.path == '/v1/disputes' else []
        return httpx.Response(200, json={'object': 'list', 'data': rows, 'has_more': bool(rows)})

    with pytest.raises(providers.ProviderError) as caught:
        await providers.fetch_source('stripe', STRIPE_CREDENTIALS, STRIPE_METADATA, transport=httpx.MockTransport(handler))
    assert caught.value.code == 'invalid_response'
    assert sum(call.url.path == '/v1/disputes' for call in calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['connect', 'sync'])
@pytest.mark.parametrize('resource', ['charges', 'refunds', 'payouts'])
async def test_dispute_prefix_is_not_accepted_for_other_stripe_resources(configured, phase, resource):
    async def handler(request):
        if request.url.path in {'/v1/account', '/v1/balance'}:
            return httpx.Response(200, json=response_for(request))
        requested = request.url.path.rsplit('/', 1)[1]
        row = stripe_row(requested)
        if requested == resource: row['id'] = 'du_FICTIONContract'
        return httpx.Response(200, json={'object': 'list', 'data': [row], 'has_more': False})

    with pytest.raises(providers.ProviderError) as caught:
        await read_stripe_contract(phase, 'test', httpx.MockTransport(handler))
    assert caught.value.code == 'invalid_response'


@pytest.mark.asyncio
async def test_stripe_server_binding_or_mode_change_is_rejected_before_network(configured, monkeypatch):
    async def forbidden(request): raise AssertionError('No outbound request permitted')
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_ACCOUNT_ID', 'acct_another12345678')
    with pytest.raises(providers.ProviderError) as caught:
        await providers.fetch_source('stripe', STRIPE_CREDENTIALS, STRIPE_METADATA, transport=httpx.MockTransport(forbidden))
    assert caught.value.code == 'stripe_account_changed'
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_ACCOUNT_ID', STRIPE_ACCOUNT)
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_MODE', 'live')
    with pytest.raises(providers.ProviderError) as caught:
        await providers.fetch_source('stripe', STRIPE_CREDENTIALS, STRIPE_METADATA, transport=httpx.MockTransport(forbidden))
    assert caught.value.code == 'stripe_account_changed'


@pytest.mark.asyncio
async def test_stripe_legacy_unbound_credentials_cannot_sync_under_new_account(configured):
    async def forbidden(request): raise AssertionError('Unbound connection must reauthorize')
    with pytest.raises(providers.ProviderError) as caught:
        await providers.fetch_source('stripe', {'api_key': KEY}, {}, transport=httpx.MockTransport(forbidden))
    assert caught.value.code == 'stripe_account_changed'


@pytest.mark.parametrize('changes,state,authorized', [
    ({'captured': False, 'amount_captured': 0}, 'authorized', 1000),
    ({'captured': False, 'amount_captured': 300}, 'partially_captured', 1000),
    ({'captured': True, 'amount_captured': 300}, 'partially_captured', 1000),
    ({}, 'captured', 1000),
    ({'amount_refunded': 200}, 'partially_refunded', 1000),
    ({'amount_refunded': 1000, 'refunded': True}, 'refunded', 1000),
    ({'status': 'failed', 'captured': False, 'paid': False, 'amount_captured': 0}, 'failed', 0),
    ({'status': 'pending', 'captured': False, 'paid': False, 'amount_captured': 0}, 'pending', 0),
])
def test_stripe_charge_capture_and_refund_amounts_remain_authoritative(changes, state, authorized):
    row = {**stripe_row('charges'), 'amount': 1000, 'amount_captured': 1000, **changes}
    normalized = providers._stripe_item(row, 'payment', 'ch_', {'stripe_account_id': STRIPE_ACCOUNT}, 'test', 'synthetic-current-snapshot', '2026-10-11T00:00:00+00:00')
    assert normalized['title'] == 'Stripe 支付' and normalized['amount_minor'] == 1000
    evidence = normalized['evidence']
    assert evidence['payment_state'] == state and evidence['amount_authorized_minor'] == authorized
    assert evidence['amount_captured_minor'] == row['amount_captured'] and evidence['amount_refunded_minor'] == row['amount_refunded']
    assert evidence['accounting_effect'] == 'none'


@pytest.mark.parametrize('changes', [
    {'captured': 1}, {'paid': None}, {'refunded': 'false'}, {'amount_captured': 2},
    {'amount_refunded': 2}, {'paid': False}, {'amount_captured': -1}, {'amount_refunded': 0.1},
    {'livemode': None}, {'livemode': 0}, {'status': 'imagined_payment'},
])
def test_stripe_malformed_capture_refund_or_mode_never_becomes_money_facts(changes):
    with pytest.raises(providers.ProviderError):
        providers._stripe_item({**stripe_row('charges'), **changes}, 'payment', 'ch_', {'stripe_account_id': STRIPE_ACCOUNT}, 'test', 'synthetic-current-snapshot', '2026-10-11T00:00:00+00:00')


@pytest.mark.asyncio
async def test_stripe_snapshot_binds_every_item_and_keeps_four_resource_coverage_counts(configured):
    async def handler(request):
        if request.url.path in {'/v1/account', '/v1/balance'}: return httpx.Response(200, json=response_for(request))
        return httpx.Response(200, json={'object': 'list', 'data': [stripe_row(request.url.path.rsplit('/', 1)[1])], 'has_more': False})
    fetched = await providers.fetch_source('stripe', STRIPE_CREDENTIALS, STRIPE_METADATA, transport=httpx.MockTransport(handler))
    snapshot = fetched['metadata']['stripe_snapshot']
    assert set(fetched['metadata']['resources']) == {'charges', 'refunds', 'disputes', 'payouts'}
    for item in fetched['items']:
        assert item['evidence']['stripe_snapshot_id'] == snapshot['id']
        assert item['evidence']['stripe_observed_at'] == snapshot['observed_at']
        assert item['evidence']['stripe_account_id'] == snapshot['account_id']
        assert item['evidence']['stripe_mode'] == snapshot['mode']


@pytest.mark.asyncio
async def test_stripe_old_account_mode_and_snapshot_are_retained_but_hidden(workspace, monkeypatch):
    client = workspace.client
    await client.post('/api/v1/private-workspace/sources/stripe/connect', headers=headers())
    assert (await client.post('/api/v1/private-workspace/sources/stripe/sync', headers=headers())).status_code == 200
    sessions = await core.private_session_factory()
    async with sessions() as db:
        connection = (await db.execute(select(PrivateConnection).where(PrivateConnection.source_id == 'stripe'))).scalar_one()
        snapshot = connection.metadata_json['stripe_snapshot']
        for identity, changes in [('old-account', {'stripe_account_id': 'acct_another12345678'}),
                                  ('test-live-cross', {'stripe_mode': 'live'}), ('old-snapshot', {'stripe_snapshot_id': 'synthetic-old-snapshot'}),
                                  ('legacy-no-binding', {'stripe_account_id': None})]:
            evidence = {'stripe_account_id': STRIPE_ACCOUNT, 'stripe_mode': 'test', 'stripe_snapshot_id': snapshot['id'], **changes}
            db.add(PrivateItem(owner_id='1', source_id='stripe', external_id=identity, kind='dispute', title=identity,
                summary='', status='needs_response', priority='urgent', evidence=evidence))
        await db.commit()
    listed = (await client.get('/api/v1/private-workspace/items?source_id=stripe', headers=headers())).json()
    overview = (await client.get('/api/v1/private-workspace', headers=headers())).json()
    assert listed['total'] == 1 and len(overview['items']) == 1 and len(overview['balances']) == 1
    async with sessions() as db:
        assert (await db.execute(select(func.count()).select_from(PrivateItem).where(PrivateItem.source_id == 'stripe'))).scalar_one() == 5
    monkeypatch.setenv('PRIVATE_WORKSPACE_STRIPE_ACCOUNT_ID', 'acct_another12345678')
    listed = (await client.get('/api/v1/private-workspace/items?source_id=stripe', headers=headers())).json()
    overview = (await client.get('/api/v1/private-workspace', headers=headers())).json()
    assert listed['total'] == 0 and not overview['items'] and not overview['balances']
    source = next(row for row in overview['sources'] if row['id'] == 'stripe')
    assert source['status'] == 'error'
    assert all(statement.lstrip().upper().startswith('SELECT') for statement in workspace.statements)


@pytest.mark.asyncio
async def test_stripe_new_snapshot_excludes_old_unsynced_status_without_deleting_history(workspace):
    client = workspace.client
    await client.post('/api/v1/private-workspace/sources/stripe/connect', headers=headers())
    await client.post('/api/v1/private-workspace/sources/stripe/sync', headers=headers())
    original = workspace.fake.fetch_source
    async def new_batch(source_id, credentials, metadata):
        result = await original(source_id, credentials, metadata)
        result['items'][0]['external_id'] = 'pi_new_snapshot'
        return result
    workspace.fake.fetch_source = new_batch
    await client.post('/api/v1/private-workspace/sources/stripe/sync', headers=headers())
    listed = (await client.get('/api/v1/private-workspace/items?source_id=stripe', headers=headers())).json()
    assert listed['total'] == 1
    sessions = await core.private_session_factory()
    async with sessions() as db:
        assert (await db.execute(select(func.count()).select_from(PrivateItem).where(PrivateItem.source_id == 'stripe'))).scalar_one() == 2


@pytest.mark.asyncio
async def test_stripe_sync_rejects_forged_batch_identity_atomically(workspace):
    client = workspace.client
    await client.post('/api/v1/private-workspace/sources/stripe/connect', headers=headers())
    await client.post('/api/v1/private-workspace/sources/stripe/sync', headers=headers())
    original = workspace.fake.fetch_source
    async def forged(source_id, credentials, metadata):
        result = await original(source_id, credentials, metadata)
        result['items'][0]['evidence']['stripe_account_id'] = 'acct_another12345678'
        return result
    workspace.fake.fetch_source = forged
    assert (await client.post('/api/v1/private-workspace/sources/stripe/sync', headers=headers())).status_code == 502
    overview = (await client.get('/api/v1/private-workspace', headers=headers())).json()
    assert len(overview['balances']) == 1 and len(overview['items']) == 1
    source = next(row for row in overview['sources'] if row['id'] == 'stripe')
    assert source['status'] == 'error'
