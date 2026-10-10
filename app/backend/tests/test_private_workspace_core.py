"""Real employee JWTs with independent private storage and mocked read providers."""
import asyncio
import os
import stat
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient, MockTransport, Response
from jose import jwt
from sqlalchemy import event, inspect, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import settings
from core.database import Base, get_db
from models.employees import Employees
from models.private_workspace import PrivateConnection, PrivateItem, PrivateSyncRun, PrivateWorkspaceBase, utcnow
from routers.private_workspace import router
from services import emp_auth, private_workspace as service, private_workspace_providers as real_providers


def headers(employee_id=1, role="super_admin"):
    return {"Authorization": "Bearer " + emp_auth.create_access_token({"emp_id": employee_id, "role": role})}


class FakeProviders:
    def __init__(self):
        self.fetches = []
        self.exchanges = []
        self.fail_sources = set()
        self.provider_status = "succeeded"

    def describe_sources(self):
        return [{"id": source_id, "name": source_id, "capabilities": ["readonly"], "missing_configuration": []}
                for source_id in service.SOURCE_IDS]

    async def begin_connect(self, source_id, state):
        if source_id == "stripe":
            return {"credentials": {"key": "rk_test_mockprivateonly"}, "metadata": {"secret": "hidden-metadata"}}
        return {"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {"state": state, "response_type": "code", "client_id": "synthetic-client"})}

    async def complete_connect(self, source_id, code):
        self.exchanges.append((source_id, code))
        return {"credentials": {"access_token": "private-synthetic-access", "refresh_token": "private-synthetic-refresh"},
                "metadata": {"provider_account_id": "synthetic-account"}}

    async def fetch_source(self, source_id, credentials, metadata):
        self.fetches.append((source_id, credentials))
        if source_id in self.fail_sources:
            raise RuntimeError("Bearer private-synthetic-access raw-response-body")
        return {"items": [{"external_id": "pi_synthetic", "kind": "payment", "title": "测试收款",
                           "summary": "来源快照", "status": self.provider_status, "priority": "high",
                           "amount_minor": 1000, "currency": "usd", "occurred_at": utcnow().isoformat(),
                           "source_url": "https://dashboard.stripe.com/payments/pi_synthetic",
                           "evidence": {"provider_id": "pi_synthetic", "access_token": "private-synthetic-access", "raw_body": "hidden-body"}}],
                "balances": [{"currency": "USD", "available_minor": 900, "pending_minor": 100}] if source_id == "stripe" else [],
                "metadata": {"partial": False}}


@pytest_asyncio.fixture
async def workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("ENFORCE_EMPLOYEE_STATUS", "false")
    monkeypatch.setenv("ENFORCE_EMPLOYEE_SESSIONS", "false")
    monkeypatch.setenv("PRIVATE_WORKSPACE_OWNER_IDS", "1")
    monkeypatch.setenv("PRIVATE_WORKSPACE_ENCRYPTION_KEY", "synthetic-private-encryption-key-for-local-tests-only")
    private_path = tmp_path / "private" / "private-workspace.db"
    monkeypatch.setenv("PRIVATE_WORKSPACE_DATABASE_URL", f"sqlite+aiosqlite:///{private_path}")
    business_path = tmp_path / "business.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{business_path}")
    business_engine = create_async_engine(settings.database_url)
    business_sessions = async_sessionmaker(business_engine, expire_on_commit=False)
    async with business_engine.begin() as connection:
        await connection.run_sync(lambda sync: Employees.__table__.create(sync))
        await connection.execute(text("CREATE TABLE finance_guard (id INTEGER PRIMARY KEY, amount INTEGER NOT NULL)"))
        await connection.execute(text("INSERT INTO finance_guard VALUES (1, 123456)"))
    async with business_sessions() as db:
        db.add_all([Employees(id=employee_id, user_id=f"employee-{employee_id}", name=f"Fixture {employee_id}",
                             role=role, status="active")
                    for employee_id, role in [(1, "super_admin"), (2, "super_admin"), (3, "admin"), (4, "sales"), (5, "finance")]])
        await db.commit()
    business_statements = []
    event.listen(business_engine.sync_engine, "before_cursor_execute",
                 lambda conn, cursor, statement, parameters, context, executemany: business_statements.append(statement))
    fake = FakeProviders()
    monkeypatch.setattr(service, "providers", lambda: fake)
    app = FastAPI()
    app.include_router(router)

    async def business_db():
        async with business_sessions() as db:
            yield db

    app.dependency_overrides[get_db] = business_db
    await service.close_private_workspace_storage()
    try:
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            yield SimpleNamespace(client=client, private_path=private_path, business_path=business_path,
                                  business_sessions=business_sessions, fake=fake, statements=business_statements)
    finally:
        await service.close_private_workspace_storage()
        await business_engine.dispose()


@pytest.mark.asyncio
async def test_allowlist_and_live_employee_role_are_required(workspace, monkeypatch):
    client = workspace.client
    for employee_id in (2, 3, 4, 5):
        access = await client.get("/api/v1/private-workspace/access", headers=headers(employee_id))
        assert access.status_code == 200 and access.json() == {"allowed": False}
        assert (await client.get("/api/v1/private-workspace", headers=headers(employee_id))).status_code == 403
    assert not workspace.private_path.exists()
    monkeypatch.delenv("PRIVATE_WORKSPACE_OWNER_IDS")
    assert (await client.get("/api/v1/private-workspace/access", headers=headers())).json() == {"allowed": False}
    monkeypatch.setenv("PRIVATE_WORKSPACE_OWNER_IDS", "1,invalid")
    assert (await client.get("/api/v1/private-workspace/access", headers=headers())).json() == {"allowed": False}
    monkeypatch.setenv("PRIVATE_WORKSPACE_OWNER_IDS", "1")
    assert (await client.get("/api/v1/private-workspace/access", headers=headers(1, "sales"))).json() == {"allowed": True}
    assert (await client.get("/api/v1/private-workspace/access", headers=headers())).headers["cache-control"] == "no-store"
    async with workspace.business_sessions() as db:
        await db.execute(update(Employees).where(Employees.id == 1).values(role="admin"))
        await db.commit()
    assert (await client.get("/api/v1/private-workspace/access", headers=headers())).json() == {"allowed": False}
    async with workspace.business_sessions() as db:
        await db.execute(update(Employees).where(Employees.id == 1).values(role="super_admin", status="inactive"))
        await db.commit()
    assert (await client.get("/api/v1/private-workspace/access", headers=headers())).json() == {"allowed": False}


@pytest.mark.asyncio
async def test_legacy_refresh_and_unsigned_tokens_cannot_open_private_space(workspace, monkeypatch):
    client = workspace.client
    monkeypatch.setitem(settings.__dict__, "jwt_secret_key", emp_auth.SECRET_KEY)
    monkeypatch.setitem(settings.__dict__, "jwt_algorithm", "HS256")
    cases = [
        {"sub": "1", "role": "super_admin"},
        {"emp_id": 1, "role": "super_admin", "token_type": "employee_refresh"},
        {"emp_id": 1, "role": "super_admin"},
    ]
    for claims in cases:
        token = jwt.encode(claims, emp_auth.SECRET_KEY, algorithm="HS256")
        response = await client.get("/api/v1/private-workspace", headers={"Authorization": "Bearer " + token})
        assert response.status_code in {401, 403}
    assert (await client.get("/api/v1/private-workspace")).status_code == 401
    assert (await client.get("/api/v1/private-workspace", headers={"Authorization": "Bearer forged"})).status_code == 401


@pytest.mark.asyncio
async def test_empty_state_and_physical_database_isolation(workspace):
    response = await workspace.client.get("/api/v1/private-workspace", headers=headers())
    assert response.status_code == 200
    result = response.json()
    assert result["items"] == [] and result["balances"] == [] and result["last_sync"] is None
    assert [source["id"] for source in result["sources"]] == list(service.SOURCE_IDS)
    assert "private_items" not in Base.metadata.tables
    assert set(PrivateWorkspaceBase.metadata.tables) == {"private_connections", "private_items", "private_preferences", "private_sync_runs"}
    assert stat.S_IMODE(workspace.private_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(workspace.private_path.parent.stat().st_mode) == 0o700
    async with workspace.business_sessions() as db:
        tables = await db.run_sync(lambda session: inspect(session.bind).get_table_names())
        assert not any(name.startswith("private_") for name in tables)
        assert await db.scalar(text("SELECT amount FROM finance_guard WHERE id = 1")) == 123456
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in workspace.statements)


@pytest.mark.asyncio
async def test_same_business_database_rejected_even_with_different_sqlite_syntax(workspace, monkeypatch):
    monkeypatch.setenv("PRIVATE_WORKSPACE_DATABASE_URL", f"sqlite:///{workspace.business_path.parent}/./business.db")
    response = await workspace.client.get("/api/v1/private-workspace", headers=headers())
    assert response.status_code == 503 and "客户管理" in response.json()["detail"]
    alias = workspace.business_path.parent / "linked-private.db"
    os.link(workspace.business_path, alias)
    monkeypatch.setenv("PRIVATE_WORKSPACE_DATABASE_URL", f"sqlite+aiosqlite:///{alias}")
    assert (await workspace.client.get("/api/v1/private-workspace", headers=headers())).status_code == 503


@pytest.mark.asyncio
async def test_manual_archive_restore_and_cross_owner_isolation(workspace, monkeypatch):
    client = workspace.client
    monkeypatch.setenv("PRIVATE_WORKSPACE_OWNER_IDS", "1,2")
    created = await client.post("/api/v1/private-workspace/items", headers=headers(), json={"title": "我的事项"})
    assert created.status_code == 201
    item_id = created.json()["item"]["id"]
    assert (await client.get("/api/v1/private-workspace/items", headers=headers(2))).json()["items"] == []
    for method in ("PATCH", "DELETE"):
        response = await client.request(method, f"/api/v1/private-workspace/items/{item_id}", headers=headers(2),
                                        json={"action_status": "done"} if method == "PATCH" else None)
        assert response.status_code == 404
    archived = await client.delete(f"/api/v1/private-workspace/items/{item_id}", headers=headers())
    assert archived.json()["item"]["action_status"] == "archived"
    assert (await client.get("/api/v1/private-workspace/items", headers=headers())).json()["items"] == []
    assert len((await client.get("/api/v1/private-workspace/items?action_status=archived", headers=headers())).json()["items"]) == 1
    restored = await client.patch(f"/api/v1/private-workspace/items/{item_id}", headers=headers(), json={"action_status": "open"})
    assert restored.json()["item"]["action_status"] == "open"
    assert (await client.post("/api/v1/private-workspace/items", headers=headers(), json={"source_id": "stripe", "title": "伪造收款"})).status_code == 422
    await client.post("/api/v1/private-workspace/sources/stripe/connect", headers=headers())
    assert (await client.post("/api/v1/private-workspace/sources/stripe/sync", headers=headers(2))).status_code == 409


@pytest.mark.asyncio
async def test_canceled_oauth_is_consumed_and_malicious_authorization_urls_rejected(workspace):
    state = await oauth_state(workspace.client)
    canceled = await workspace.client.get("/api/v1/private-workspace/oauth/gmail/callback", params={"state": state, "error": "access_denied"})
    assert canceled.status_code == 303 and canceled.headers["location"].endswith("connection=incomplete")
    replay = await workspace.client.get("/api/v1/private-workspace/oauth/gmail/callback", params={"state": state, "code": "synthetic-code"})
    assert replay.status_code == 400 and workspace.fake.exchanges == []

    async def malicious_connect(source_id, state):
        return {"authorization_url": "https://evil.test/?state=" + state}

    workspace.fake.begin_connect = malicious_connect
    assert (await workspace.client.post("/api/v1/private-workspace/sources/gmail/connect", headers=headers())).status_code == 502


@pytest.mark.asyncio
async def test_sync_upserts_and_never_overwrites_local_actions_or_finance(workspace):
    client = workspace.client
    connected = await client.post("/api/v1/private-workspace/sources/stripe/connect", headers=headers())
    assert connected.status_code == 200 and not connected.json()["requires_redirect"]
    first = await client.post("/api/v1/private-workspace/sources/stripe/sync", headers=headers())
    assert first.json()["counts"] == {"created": 1, "updated": 0}
    item = (await client.get("/api/v1/private-workspace/items", headers=headers())).json()["items"][0]
    changed = await client.patch(f"/api/v1/private-workspace/items/{item['id']}", headers=headers(),
                                 json={"title": "我的备注标题", "action_status": "done"})
    assert changed.status_code == 200
    for forbidden in ({"status": "paid"}, {"amount_minor": 5}, {"source_id": "manual"}, {"evidence": {}}):
        assert (await client.patch(f"/api/v1/private-workspace/items/{item['id']}", headers=headers(), json=forbidden)).status_code == 422
    workspace.fake.provider_status = "failed"
    second = await client.post("/api/v1/private-workspace/sources/stripe/sync", headers=headers())
    assert second.json()["counts"] == {"created": 0, "updated": 1}
    result = (await client.get("/api/v1/private-workspace", headers=headers())).json()
    assert result["items"] == []
    details = (await client.get("/api/v1/private-workspace/items?source_id=stripe", headers=headers())).json()
    assert len(details["items"]) == 1
    assert details["items"][0]["title"] == "我的备注标题"
    assert details["items"][0]["action_status"] == "done" and details["items"][0]["status"] == "failed"
    assert result["balances"] == [{"source_id": "stripe", "currency": "USD", "available_minor": 900, "pending_minor": 100}]
    assert (await client.delete(f"/api/v1/private-workspace/items/{item['id']}", headers=headers())).status_code == 409
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in workspace.statements)


@pytest.mark.asyncio
async def test_credentials_errors_and_provider_raw_data_never_return(workspace):
    client = workspace.client
    await client.post("/api/v1/private-workspace/sources/stripe/connect", headers=headers())
    await client.post("/api/v1/private-workspace/sources/stripe/sync", headers=headers())
    result = await client.get("/api/v1/private-workspace", headers=headers())
    for secret in ("rk_test_mockprivateonly", "private-synthetic-access", "hidden-body", "hidden-metadata", "encrypted_credentials", "owner_id"):
        assert secret not in result.text
    sessions = await service.private_session_factory()
    async with sessions() as db:
        row = (await db.execute(select(PrivateConnection))).scalar_one()
        assert "rk_test_mockprivateonly" not in row.encrypted_credentials
        assert service.decrypt_credentials(row.encrypted_credentials) == {"key": "rk_test_mockprivateonly"}
    workspace.fake.fail_sources.add("stripe")
    failure = await client.post("/api/v1/private-workspace/sources/stripe/sync", headers=headers())
    assert failure.status_code == 502 and "private-synthetic" not in failure.text
    result = await client.get("/api/v1/private-workspace", headers=headers())
    assert len(result.json()["items"]) == 1 and result.json()["sources"][3]["status"] == "error"


async def oauth_state(client):
    result = await client.post("/api/v1/private-workspace/sources/gmail/connect", headers=headers())
    assert result.status_code == 200
    return parse_qs(urlsplit(result.json()["authorization_url"]).query)["state"][0]


@pytest.mark.asyncio
async def test_oauth_state_is_owner_bound_single_use_and_source_bound(workspace):
    state = await oauth_state(workspace.client)
    wrong_source = await workspace.client.get("/api/v1/private-workspace/oauth/bofa/callback", params={"state": state, "code": "synthetic-code"})
    assert wrong_source.status_code == 400
    completed = await workspace.client.get("/api/v1/private-workspace/oauth/gmail/callback", params={"state": state, "code": "synthetic-code"})
    assert completed.status_code == 303 and completed.headers["location"] == "/private-workspace?source=gmail&connection=connected"
    replay = await workspace.client.get("/api/v1/private-workspace/oauth/gmail/callback", params={"state": state, "code": "synthetic-code"})
    assert replay.status_code == 400 and len(workspace.fake.exchanges) == 1
    sessions = await service.private_session_factory()
    async with sessions() as db:
        connection = (await db.execute(select(PrivateConnection))).scalar_one()
        assert connection.oauth_state_hash != state
        assert connection.oauth_used_at is not None


@pytest.mark.asyncio
async def test_wrong_gmail_profile_does_not_save_credentials_or_touch_crm(workspace, monkeypatch):
    monkeypatch.setenv('GOOGLE_WORKSPACE_CLIENT_ID', 'synthetic-client.apps.googleusercontent.com')
    monkeypatch.setenv('GOOGLE_WORKSPACE_CLIENT_SECRET', 'synthetic-client-secret')
    monkeypatch.setenv('PRIVATE_WORKSPACE_PUBLIC_URL', 'https://t24-crm.com')
    monkeypatch.setenv('PRIVATE_WORKSPACE_GMAIL_EXPECTED_ACCOUNT', 'owner@example.com')
    requests = []
    async def provider_http(request):
        requests.append(request)
        if request.url.host == 'oauth2.googleapis.com':
            return Response(200, json={'access_token': 'wrong-account-private-token', 'refresh_token': 'wrong-account-refresh',
                                       'scope': real_providers.GMAIL_SCOPE})
        return Response(200, json={'emailAddress': 'other@example.com'})
    async def actual_exchange(source_id, code):
        return await real_providers.complete_connect(source_id, code, transport=MockTransport(provider_http))
    workspace.fake.complete_connect = actual_exchange
    state = await oauth_state(workspace.client)
    response = await workspace.client.get('/api/v1/private-workspace/oauth/gmail/callback',
                                          params={'state': state, 'code': 'synthetic-code'})
    assert response.status_code == 303 and 'connection=incomplete' in response.headers['location']
    sessions = await service.private_session_factory()
    async with sessions() as db:
        connection = (await db.execute(select(PrivateConnection))).scalar_one()
        assert connection.status == 'disconnected' and connection.encrypted_credentials is None
        assert connection.oauth_used_at is not None and not connection.metadata_json.get('account_label')
    assert len(requests) == 2
    assert all(statement.lstrip().upper().startswith('SELECT') for statement in workspace.statements)


@pytest.mark.asyncio
async def test_sync_preserves_confirmed_account_scope_and_mode(workspace):
    stable = {'account_label': 'owner@example.com', 'scope': real_providers.GMAIL_SCOPE, 'connection_mode': 'oauth',
              'read_only_adapter': True, 'mode': 'test'}
    sessions = await service.private_session_factory()
    async with sessions() as db:
        db.add(PrivateConnection(owner_id='1', source_id='gmail', status='connected', metadata_json=stable,
                                 encrypted_credentials=service.encrypt_credentials({'key': 'synthetic'})))
        await db.commit()
    original_fetch = workspace.fake.fetch_source
    async def fetched_snapshot(source_id, credentials, metadata):
        assert metadata == stable
        result = await original_fetch(source_id, credentials, metadata)
        result['metadata'] = {'account_label': 'different@example.com', 'scope': 'mail-write', 'connection_mode': 'write',
                              'read_only_adapter': False, 'mode': 'live', 'partial': True, 'sync_window': 'last_60_days'}
        return result
    workspace.fake.fetch_source = fetched_snapshot
    response = await workspace.client.post('/api/v1/private-workspace/sources/gmail/sync', headers=headers())
    assert response.status_code == 200
    visible = response.json()['source']['metadata']
    assert visible['account_label'] == stable['account_label'] and visible['read_only_adapter'] is True and visible['mode'] == 'test'
    assert visible['sync_window'] == 'last_60_days' and visible['partial'] is True
    assert 'scope' not in visible and 'encrypted_credentials' not in response.text
    async with sessions() as db:
        connection = (await db.execute(select(PrivateConnection))).scalar_one()
        assert all(connection.metadata_json[key] == value for key, value in stable.items())
        assert connection.last_sync is not None
    assert all(statement.lstrip().upper().startswith('SELECT') for statement in workspace.statements)


@pytest.mark.asyncio
async def test_sync_cannot_invent_an_authorized_account_from_snapshot(workspace):
    await workspace.client.post('/api/v1/private-workspace/sources/stripe/connect', headers=headers())
    original_fetch = workspace.fake.fetch_source
    async def fetched_snapshot(source_id, credentials, metadata):
        result = await original_fetch(source_id, credentials, metadata)
        result['metadata']['account_label'] = 'not-a-confirmed-account@example.com'
        result['metadata']['connection_mode'] = 'unconfirmed-mode'
        result['metadata']['scope'] = 'unconfirmed-scope'
        return result
    workspace.fake.fetch_source = fetched_snapshot
    response = await workspace.client.post('/api/v1/private-workspace/sources/stripe/sync', headers=headers())
    assert response.status_code == 200 and 'account_label' not in response.json()['source']['metadata']
    sessions = await service.private_session_factory()
    async with sessions() as db:
        connection = (await db.execute(select(PrivateConnection))).scalar_one()
        assert all(key not in connection.metadata_json for key in ('account_label', 'scope', 'connection_mode'))


@pytest.mark.asyncio
async def test_expired_and_demoted_owner_oauth_state_never_exchanges(workspace):
    state = await oauth_state(workspace.client)
    sessions = await service.private_session_factory()
    async with sessions() as db:
        await db.execute(update(PrivateConnection).values(oauth_expires_at=utcnow() - timedelta(seconds=1)))
        await db.commit()
    expired = await workspace.client.get("/api/v1/private-workspace/oauth/gmail/callback", params={"state": state, "code": "synthetic-code"})
    assert expired.status_code == 400
    state = await oauth_state(workspace.client)
    async with workspace.business_sessions() as db:
        await db.execute(update(Employees).where(Employees.id == 1).values(role="admin"))
        await db.commit()
    denied = await workspace.client.get("/api/v1/private-workspace/oauth/gmail/callback", params={"state": state, "code": "synthetic-code"})
    assert denied.status_code == 403 and workspace.fake.exchanges == []


@pytest.mark.asyncio
async def test_background_sync_skips_inactive_owners_and_isolates_source_failure(workspace, monkeypatch):
    monkeypatch.setenv("PRIVATE_WORKSPACE_OWNER_IDS", "1,2")
    sessions = await service.private_session_factory()
    async with sessions() as db:
        for owner_id, source_id in [("1", "gmail"), ("1", "stripe"), ("2", "stripe")]:
            db.add(PrivateConnection(owner_id=owner_id, source_id=source_id, status="connected",
                                     encrypted_credentials=service.encrypt_credentials({"key": "synthetic"})))
        await db.commit()
    async with workspace.business_sessions() as db:
        await db.execute(update(Employees).where(Employees.id == 2).values(status="inactive"))
        await db.commit()
    workspace.fake.fail_sources.add("gmail")
    async with workspace.business_sessions() as business_db, sessions() as db:
        result = await service.sync_due_sources(business_db, db)
        assert result == {"attempted": 2, "succeeded": 1, "failed": 1, "skipped": 1}
        repeated = await service.sync_due_sources(business_db, db)
        assert repeated == {"attempted": 0, "succeeded": 0, "failed": 0, "skipped": 3}
    assert all(credentials == {"key": "synthetic"} for _, credentials in workspace.fake.fetches)
    assert len(workspace.fake.fetches) == 2


@pytest.mark.asyncio
async def test_disconnect_during_sync_prevents_old_snapshot_writes_and_parallel_sync(workspace):
    client = workspace.client
    await client.post("/api/v1/private-workspace/sources/stripe/connect", headers=headers())
    started, release = asyncio.Event(), asyncio.Event()
    original_fetch = workspace.fake.fetch_source

    async def delayed_fetch(source_id, credentials, metadata):
        started.set()
        await release.wait()
        return await original_fetch(source_id, credentials, metadata)

    workspace.fake.fetch_source = delayed_fetch
    in_progress = asyncio.create_task(client.post("/api/v1/private-workspace/sources/stripe/sync", headers=headers()))
    await asyncio.wait_for(started.wait(), timeout=5)
    parallel = await client.post("/api/v1/private-workspace/sources/stripe/sync", headers=headers())
    assert parallel.status_code == 409
    disconnected = await client.post("/api/v1/private-workspace/sources/stripe/disconnect", headers=headers())
    assert disconnected.json()["source"]["status"] == "disconnected"
    release.set()
    response = await in_progress
    assert response.status_code == 502
    overview = (await client.get("/api/v1/private-workspace", headers=headers())).json()
    assert overview["items"] == [] and overview["balances"] == []
    assert overview["sources"][3]["status"] == "disconnected"


@pytest.mark.asyncio
async def test_preferences_minimum_interval_and_safe_url_filter(workspace):
    assert (await workspace.client.patch("/api/v1/private-workspace/preferences", headers=headers(), json={"sync_interval_seconds": 299})).status_code == 422
    result = await workspace.client.patch("/api/v1/private-workspace/preferences", headers=headers(), json={"sync_interval_seconds": 600})
    assert result.json() == {"sync_interval_seconds": 600}
    assert service.safe_source_url("stripe", "http://127.0.0.1/private") is None
    assert service.safe_source_url("stripe", "https://dashboard.stripe.com.evil.test/") is None
    assert service.safe_source_url("stripe", "https://dashboard.stripe.com/?access_token=private") is None
    with pytest.raises(HTTPException):
        service.safe_authorization_url("https://accounts.google.com.evil.test/o/oauth2/v2/auth?state=s&response_type=code")


@pytest.mark.asyncio
async def test_overview_keeps_old_urgent_work_when_recent_completed_and_normal_records_exceed_limit(workspace):
    sessions = await service.private_session_factory()
    now = utcnow()
    old = now - timedelta(days=40)

    def item(external_id, **values):
        defaults = {"owner_id": "1", "source_id": "manual", "external_id": external_id, "kind": "task",
                    "title": external_id, "summary": "", "status": "manual", "priority": "normal",
                    "action_status": "open", "created_at": now, "evidence": {}}
        return PrivateItem(**{**defaults, **values})

    async with sessions() as db:
        db.add(item("old-urgent-dispute", source_id="stripe", kind="dispute", status="needs_response",
                    priority="urgent", due_at=now + timedelta(hours=5), created_at=old))
        db.add(item("old-high-early", priority="high", due_at=now - timedelta(days=2), created_at=old))
        db.add(item("old-high-later", priority="high", due_at=now + timedelta(days=2), created_at=old))
        db.add(item("due-snoozed", priority="urgent", action_status="snoozed", snoozed_until=now - timedelta(minutes=1), created_at=old))
        db.add(item("future-snoozed", priority="urgent", action_status="snoozed", snoozed_until=now + timedelta(days=1)))
        db.add(item("another-owner", owner_id="2", priority="urgent"))
        db.add_all(item(f"completed-{index}", action_status="done", priority="urgent") for index in range(120))
        db.add_all(item(f"normal-payout-{index}", source_id="stripe", kind="payout", status="paid",
                        due_at=now - timedelta(days=1)) for index in range(120))
        db.add_all(item(f"normal-task-{index}") for index in range(120))
        db.add(item("bank-latest", source_id="bofa", kind="email_alert", status="unverified", occurred_at=now,
                    evidence={"type": "email_alert", "verification": "unverified"}))
        await db.commit()

    result = (await workspace.client.get("/api/v1/private-workspace", headers=headers())).json()
    work = [row for row in result["items"] if row["source_id"] != "bofa"]
    assert len(work) == 100
    assert [row["title"] for row in work[:4]] == ["old-urgent-dispute", "due-snoozed", "old-high-early", "old-high-later"]
    assert all(row["action_status"] in {"open", "snoozed"} for row in work)
    assert not any(row["kind"] == "payout" for row in work)
    assert not any(row["title"] in {"future-snoozed", "another-owner"} for row in work)
    assert result["items"][-1]["title"] == "bank-latest"
    # Source detail retains its separate recent-record view, including completed records.
    details = (await workspace.client.get("/api/v1/private-workspace/items?source_id=stripe", headers=headers())).json()
    assert len(details["items"]) == 100 and all(row["kind"] == "payout" for row in details["items"])
