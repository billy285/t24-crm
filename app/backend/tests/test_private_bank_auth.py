"""Real private HTTP auth with synthetic outbound bank responses and revocations."""
import asyncio
from datetime import timedelta
import hashlib
import sqlite3
import time
from types import SimpleNamespace

from fastapi import Request
import httpx
import pytest
import pytest_asyncio

from dependencies.private_workspace import revalidate_private_owner
from services import emp_auth, private_bank_provider as bank
from test_private_bank_provider import bank_config, BankMock
from test_private_workspace_app import private_app


@pytest_asyncio.fixture
async def bank_auth(private_app, bank_config, monkeypatch):
    value = private_app
    monkeypatch.setenv('PRIVATE_WORKSPACE_OWNER_IDS', '4')
    with sqlite3.connect(value.business_path) as db:
        db.execute("UPDATE employees SET role='super_admin' WHERE id=4")
    mock = BankMock(); pause = asyncio.Event(); release = asyncio.Event(); boundary = {'path': None}

    async def handle(request):
        if request.url.path == boundary['path']:
            pause.set(); await release.wait()
        return await mock(request)

    transport = httpx.MockTransport(handle)
    create, exchange = bank.create_hosted_link, bank.exchange_completed_link

    async def mocked_create(owner, session, **kwargs):
        return await create(owner, session, transport=transport)

    async def mocked_exchange(context, **kwargs):
        kwargs['transport'] = transport
        return await exchange(context, **kwargs)

    monkeypatch.setattr(bank, 'create_hosted_link', mocked_create)
    monkeypatch.setattr(bank, 'exchange_completed_link', mocked_exchange)
    yield SimpleNamespace(value=value, pause=pause, release=release, boundary=boundary, mock=mock)
    release.set()


def changed_identity(value, change, monkeypatch):
    if change == 'allowlist':
        monkeypatch.setenv('PRIVATE_WORKSPACE_OWNER_IDS', '1'); return
    statements = {
        'logout': "UPDATE employee_auth_sessions SET revoked_at=1 WHERE employee_id=4",
        'expired_session': "UPDATE employee_auth_sessions SET expires_at=1 WHERE employee_id=4",
        'deleted_session': "DELETE FROM employee_auth_sessions WHERE employee_id=4",
        'password': "UPDATE employees SET password='new-synthetic-credential' WHERE id=4",
        'inactive': "UPDATE employees SET status='inactive' WHERE id=4",
        'role': "UPDATE employees SET role='sales' WHERE id=4",
    }
    with sqlite3.connect(value.business_path) as db: db.execute(statements[change])


async def wait_at_boundary(auth, phase, headers):
    route = '/api/v1/private-workspace/bank/link/'
    if phase == 'start':
        auth.boundary['path'] = '/link/token/create'
        running = asyncio.create_task(auth.value.client.post(route + 'start', headers=headers))
    else:
        start = await auth.value.client.post(route + 'start', headers=headers)
        assert start.status_code == 200, start.text
        auth.boundary['path'] = '/item/public_token/exchange' if phase == 'exchange' else '/item/get'
        running = asyncio.create_task(auth.value.client.post(route + 'complete', headers=headers,
            json={'session_id': start.json()['session_id']}))
    await asyncio.wait_for(auth.pause.wait(), timeout=3)
    return running


def assert_canceled_without_credentials(value):
    with sqlite3.connect(value.private_path) as db:
        assert db.execute("SELECT status,encrypted_credentials FROM private_connections WHERE source_id='bofa_bank'").fetchall() == [('disconnected', None)]
        assert db.execute('SELECT state,encrypted_context,lease_until FROM private_bank_links').fetchall() == [('canceled', None, None)]


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['start', 'exchange', 'verification'])
@pytest.mark.parametrize('change', ['logout', 'expired_session', 'deleted_session', 'password', 'inactive', 'role', 'allowlist'])
async def test_bank_wait_rechecks_real_session_and_owner_before_saving_authorization(bank_auth, monkeypatch, phase, change):
    value = bank_auth.value
    running = await wait_at_boundary(bank_auth, phase, value.headers(4))
    changed_identity(value, change, monkeypatch)
    # The only customer change is the deliberate independent security fixture.
    before = hashlib.sha256(value.business_path.read_bytes()).hexdigest()
    bank_auth.release.set(); response = await asyncio.wait_for(running, timeout=3)
    assert response.status_code == 403 and response.headers['cache-control'] == 'no-store'
    assert_canceled_without_credentials(value)
    assert hashlib.sha256(value.business_path.read_bytes()).hexdigest() == before
    with sqlite3.connect(value.business_path) as db:
        assert db.execute('SELECT amount FROM finance_sentinel').fetchone() == (70000,)
    assert 'synthetic_private_only' not in response.text


@pytest.mark.asyncio
async def test_bank_boundary_cannot_opt_out_of_persistent_session_checks(bank_auth, monkeypatch):
    for name in ('APP_ENV', 'ENVIRONMENT', 'ENV'): monkeypatch.setenv(name, 'test')
    monkeypatch.setenv('ENFORCE_EMPLOYEE_STATUS', 'false'); monkeypatch.setenv('ENFORCE_EMPLOYEE_SESSIONS', 'false')
    running = await wait_at_boundary(bank_auth, 'exchange', bank_auth.value.headers(4))
    changed_identity(bank_auth.value, 'logout', monkeypatch)
    bank_auth.release.set(); response = await asyncio.wait_for(running, timeout=3)
    assert response.status_code == 403
    assert_canceled_without_credentials(bank_auth.value)


@pytest.mark.asyncio
async def test_token_expiring_during_bank_wait_is_decoded_again_and_not_saved(bank_auth):
    headers = {'Authorization': 'Bearer ' + emp_auth.create_access_token(
        {'emp_id': 4, 'role': 'super_admin', 'sid': 'synthetic-session-4'}, expires_delta=timedelta(seconds=2))}
    running = await wait_at_boundary(bank_auth, 'start', headers)
    await asyncio.sleep(2.1)
    bank_auth.release.set(); response = await asyncio.wait_for(running, timeout=3)
    assert response.status_code == 403
    assert_canceled_without_credentials(bank_auth.value)


@pytest.mark.asyncio
async def test_unchanged_real_session_can_complete_and_crm_file_is_unchanged(bank_auth):
    value = bank_auth.value; before = hashlib.sha256(value.business_path.read_bytes()).hexdigest()
    started = await value.client.post('/api/v1/private-workspace/bank/link/start', headers=value.headers(4))
    assert started.status_code == 200
    completed = await value.client.post('/api/v1/private-workspace/bank/link/complete', headers=value.headers(4),
        json={'session_id': started.json()['session_id']})
    assert completed.status_code == 200 and completed.json()['state'] == 'connected'
    assert hashlib.sha256(value.business_path.read_bytes()).hexdigest() == before


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['missing', 'legacy', 'refresh', 'missing_sid', 'other_employee', 'no_factory'])
async def test_revalidation_fails_closed_before_private_connector_for_invalid_credentials(bank_auth, kind):
    value = bank_auth.value
    if kind == 'missing': headers = {}
    elif kind == 'legacy':
        from jose import jwt
        headers = {'Authorization': 'Bearer ' + jwt.encode({'sub': '4', 'exp': int(time.time()) + 3600}, emp_auth.SECRET_KEY, algorithm=emp_auth.ALGORITHM)}
    else:
        claims = {'emp_id': 4 if kind != 'other_employee' else 2, 'sid': 'synthetic-session-4',
                  'token_type': 'employee_refresh' if kind == 'refresh' else 'employee_access', 'exp': int(time.time()) + 3600}
        if kind == 'missing_sid': claims.pop('sid')
        from jose import jwt
        headers = {'Authorization': 'Bearer ' + jwt.encode(claims, emp_auth.SECRET_KEY, algorithm=emp_auth.ALGORITHM)}
    request = Request({'type': 'http', 'method': 'POST', 'path': '/api/v1/private-workspace/bank/link/start',
        'headers': [(name.lower().encode(), content.encode()) for name, content in headers.items()], 'app': value.app})
    if kind == 'no_factory':
        factory = value.app.state.private_business_sessions; value.app.state.private_business_sessions = None
        try: assert await revalidate_private_owner(request, '4') is False
        finally: value.app.state.private_business_sessions = factory
    else: assert await revalidate_private_owner(request, '4') is False
    assert bank_auth.mock.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['logout', 'expired_session', 'token_expiry'])
async def test_bank_sync_wait_does_not_return_bank_result_after_session_ends(bank_auth, monkeypatch, change):
    from routers import private_workspace as routes

    value = bank_auth.value
    started, release = asyncio.Event(), asyncio.Event()
    marker = 'synthetic-bank-sync-result-must-not-be-returned'

    async def waiting_sync(private_db, owner, source_id):
        assert owner == '4' and source_id == 'bofa_bank'
        started.set()
        await release.wait()
        return {'source_id': 'bofa_bank', 'private_result': marker}

    monkeypatch.setattr(routes, 'sync_source', waiting_sync)
    headers = value.headers(4)
    if change == 'token_expiry':
        headers = {'Authorization': 'Bearer ' + emp_auth.create_access_token(
            {'emp_id': 4, 'role': 'super_admin', 'sid': 'synthetic-session-4'},
            expires_delta=timedelta(seconds=2))}
    running = asyncio.create_task(value.client.post(
        '/api/v1/private-workspace/sources/bofa_bank/sync', headers=headers))
    try:
        await asyncio.wait_for(started.wait(), timeout=3)
        if change == 'token_expiry':
            await asyncio.sleep(2.1)
        else:
            changed_identity(value, change, monkeypatch)
        # Revalidation must not write to the customer DB after the independent
        # security mutation, and must withhold the mock private sync result.
        before = hashlib.sha256(value.business_path.read_bytes()).hexdigest()
        release.set()
        response = await asyncio.wait_for(running, timeout=3)
        assert response.status_code == 403
        assert response.json() == {'detail': '私人空间访问权限已失效'}
        assert response.headers['cache-control'] == 'no-store'
        assert marker not in response.text and 'bofa_bank' not in response.text
        assert hashlib.sha256(value.business_path.read_bytes()).hexdigest() == before
        with sqlite3.connect(value.business_path) as db:
            assert db.execute('SELECT amount FROM finance_sentinel').fetchone() == (70000,)
        assert bank_auth.mock.calls == []
    finally:
        release.set()
        if not running.done():
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
