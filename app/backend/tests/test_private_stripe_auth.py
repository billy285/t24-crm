"""Real standalone owner/session checks around synthetic Stripe network waits."""
import asyncio
from datetime import timedelta
import hashlib
import os
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from routers import private_workspace as routes
from services import emp_auth, private_workspace as core, private_workspace_providers as providers
from test_private_bank_auth import changed_identity
from test_private_stripe_connection import response_for
from test_private_workspace_app import private_app
from test_private_workspace_providers import configured, settings, stripe_row


@pytest_asyncio.fixture
async def stripe_auth(private_app, configured, monkeypatch):
    value = private_app
    monkeypatch.setenv('PRIVATE_WORKSPACE_OWNER_IDS', '4')
    with sqlite3.connect(value.business_path) as db:
        db.execute("UPDATE employees SET role='super_admin' WHERE id=4")
    phase = {'value': None, 'checks': 0}
    pause, release = asyncio.Event(), asyncio.Event()
    requests = []
    original_validator = routes.revalidate_private_owner

    async def fresh_validator(request, owner_id):
        phase['checks'] += 1
        if ((phase['value'] in {'connect-commit', 'sync-commit'} and phase['checks'] == 3) or
                (phase['value'] in {'connect-response', 'sync-response'} and phase['checks'] == 4)):
            pause.set()
            await release.wait()
        return await original_validator(request, owner_id)

    async def handler(request):
        assert request.method == 'GET'
        requests.append(request.url.path)
        if phase['value'] in {'connect-network', 'sync-network'} and request.url.path == '/v1/payouts':
            pause.set()
            await release.wait()
        charge = {**stripe_row('charges'), 'id': 'ch_synthetic' + str(len(requests))}
        return httpx.Response(200, json=response_for(request, charges=[charge]))

    transport = httpx.MockTransport(handler)
    original_begin, original_fetch = providers.begin_connect, providers.fetch_source

    async def begin(source_id, state):
        return await original_begin(source_id, state, transport=transport)

    async def fetch(source_id, credentials, metadata):
        return await original_fetch(source_id, credentials, metadata, transport=transport)

    monkeypatch.setattr(routes, 'revalidate_private_owner', fresh_validator)
    monkeypatch.setattr(providers, 'begin_connect', begin)
    monkeypatch.setattr(providers, 'fetch_source', fetch)
    yield SimpleNamespace(value=value, phase=phase, pause=pause, release=release, requests=requests)
    release.set()


def private_financial_state(value):
    with sqlite3.connect(value.private_path) as db:
        connection = db.execute("SELECT status,encrypted_credentials,metadata_json,generation,last_sync "
            "FROM private_connections WHERE source_id='stripe'").fetchall()
        items = db.execute("SELECT * FROM private_items WHERE source_id='stripe' ORDER BY id").fetchall()
    return connection, items


async def prepare_sync(auth):
    value = auth.value
    connected = await value.client.post('/api/v1/private-workspace/sources/stripe/connect', headers=value.headers(4))
    assert connected.status_code == 200, connected.text
    synced = await value.client.post('/api/v1/private-workspace/sources/stripe/sync', headers=value.headers(4))
    assert synced.status_code == 200, synced.text


async def held_request(auth, phase, *, token_expiry=False):
    if phase.startswith('sync'):
        await prepare_sync(auth)
    before = private_financial_state(auth.value)
    auth.phase.update(value=phase, checks=0)
    headers = auth.value.headers(4)
    if token_expiry:
        headers = {'Authorization': 'Bearer ' + emp_auth.create_access_token(
            {'emp_id': 4, 'role': 'super_admin', 'sid': 'synthetic-session-4'},
            expires_delta=timedelta(seconds=2))}
    action = 'connect' if phase.startswith('connect') else 'sync'
    running = asyncio.create_task(auth.value.client.post('/api/v1/private-workspace/sources/stripe/' + action,
                                                       headers=headers))
    await asyncio.wait_for(auth.pause.wait(), timeout=3)
    return before, running


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['connect-network', 'connect-commit', 'sync-network', 'sync-commit'])
@pytest.mark.parametrize('change', ['logout', 'expired_session', 'role', 'inactive', 'password', 'allowlist'])
async def test_stripe_wait_cancels_before_credentials_or_financial_batch_commit(stripe_auth, monkeypatch, phase, change):
    auth, value = stripe_auth, stripe_auth.value
    before_private, running = await held_request(auth, phase)
    try:
        changed_identity(value, change, monkeypatch)
        before_business = hashlib.sha256(value.business_path.read_bytes()).hexdigest()
        auth.release.set()
        response = await asyncio.wait_for(running, timeout=3)
        assert response.status_code == 403, response.text
        assert response.json() == {'detail': '私人空间访问权限已失效'}
        assert response.headers['cache-control'] == 'no-store'
        assert 'source' not in response.json() and 'counts' not in response.json()
        assert private_financial_state(value) == before_private
        assert hashlib.sha256(value.business_path.read_bytes()).hexdigest() == before_business
        with sqlite3.connect(value.business_path) as db:
            assert db.execute('SELECT amount FROM finance_sentinel').fetchone() == (70000,)
        with sqlite3.connect(value.private_path) as db:
            assert not db.execute("SELECT sync_lease_until FROM private_connections WHERE sync_lease_until IS NOT NULL").fetchall()
            if phase.startswith('sync'):
                assert db.execute("SELECT status FROM private_sync_runs").fetchall().count(('failed',)) == 1
    finally:
        auth.release.set()
        if not running.done():
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['connect-network', 'sync-network'])
async def test_stripe_jwt_expiry_during_network_wait_is_rechecked_without_saving(stripe_auth, phase):
    before, running = await held_request(stripe_auth, phase, token_expiry=True)
    await asyncio.sleep(2.1)
    stripe_auth.release.set()
    response = await asyncio.wait_for(running, timeout=3)
    assert response.status_code == 403 and response.json() == {'detail': '私人空间访问权限已失效'}
    assert private_financial_state(stripe_auth.value) == before


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['connect-response', 'sync-response'])
@pytest.mark.parametrize('change', ['logout', 'expired_session', 'role'])
async def test_stripe_completed_operation_does_not_disclose_result_after_session_ends(stripe_auth, monkeypatch, phase, change):
    _, running = await held_request(stripe_auth, phase)
    changed_identity(stripe_auth.value, change, monkeypatch)
    stripe_auth.release.set()
    response = await asyncio.wait_for(running, timeout=3)
    assert response.status_code == 403 and response.json() == {'detail': '私人空间访问权限已失效'}
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.asyncio
async def test_unchanged_owner_session_can_connect_and_sync_with_customer_file_unchanged(stripe_auth):
    value = stripe_auth.value
    before = hashlib.sha256(value.business_path.read_bytes()).hexdigest()
    await prepare_sync(stripe_auth)
    connection, items = private_financial_state(value)
    assert connection[0][0] == 'connected' and connection[0][1] and connection[0][4]
    assert len(items) == 1 and len(stripe_auth.requests) == 12
    assert hashlib.sha256(value.business_path.read_bytes()).hexdigest() == before


@pytest.mark.asyncio
async def test_first_sync_is_not_started_when_request_owner_validator_already_failed(stripe_auth):
    value = stripe_auth.value
    assert (await value.client.post('/api/v1/private-workspace/sources/stripe/connect', headers=value.headers(4))).status_code == 200
    before, network_calls = private_financial_state(value), len(stripe_auth.requests)
    factory = await core.private_session_factory()
    async def denied(): return False
    async with factory() as db:
        with pytest.raises(Exception) as caught:
            await core.sync_source(db, '4', 'stripe', owner_validator=denied)
    assert caught.value.status_code == 403
    assert len(stripe_auth.requests) == network_calls
    assert private_financial_state(value) == before


@pytest.mark.asyncio
async def test_bound_stripe_failed_read_can_retry_without_reconnect_or_environment_key(stripe_auth, monkeypatch):
    auth, value = stripe_auth, stripe_auth.value
    await prepare_sync(auth)
    monkeypatch.delenv('PRIVATE_WORKSPACE_STRIPE_KEY')
    original_fetch = providers.fetch_source
    failure = {'next': True}

    async def transient_read(source_id, credentials, metadata):
        if failure['next']:
            failure['next'] = False
            raise providers.ProviderError('upstream_unavailable')
        return await original_fetch(source_id, credentials, metadata)

    monkeypatch.setattr(providers, 'fetch_source', transient_read)
    business_before = hashlib.sha256(value.business_path.read_bytes()).hexdigest()
    before = private_financial_state(value)
    failed = await value.client.post('/api/v1/private-workspace/sources/stripe/sync', headers=value.headers(4))
    assert failed.status_code == 502
    overview = await value.client.get('/api/v1/private-workspace', headers=value.headers(4))
    assert overview.status_code == 200
    source = next(row for row in overview.json()['sources'] if row['id'] == 'stripe')
    assert source['status'] == 'error' and source['action_availability'] == {'can_connect': False, 'can_sync': True}
    assert not source['missing_configuration']
    assert private_financial_state(value) == before
    retried = await value.client.post('/api/v1/private-workspace/sources/stripe/sync', headers=value.headers(4))
    assert retried.status_code == 200, retried.text
    assert retried.json()['source']['status'] == 'connected'
    assert retried.json()['source']['action_availability'] == {'can_connect': False, 'can_sync': True}
    saved, _ = private_financial_state(value)
    assert saved[0][1] == before[0][0][1] and saved[0][3] == before[0][0][3]
    assert 'PRIVATE_WORKSPACE_STRIPE_KEY' not in os.environ
    assert hashlib.sha256(value.business_path.read_bytes()).hexdigest() == business_before
