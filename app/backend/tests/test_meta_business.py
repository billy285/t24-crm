"""Synthetic Meta connection checks; no browser, production or provider access."""
import asyncio
import copy
import importlib.util
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy import create_engine, inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations

from core.database import get_db
from dependencies.auth import get_current_user
from models.employees import Employees
from models.customers import Customers
from models.meta_business import MetaBusinessConnection as Connection, MetaBusinessOAuthState as State, MetaBusinessAsset as Asset, MetaBusinessBinding as Binding, MetaBusinessRequest as Request
from routers.meta_business import router, MetaOAuthAccessLogFilter
from services import meta_business as service, meta_business_provider as provider
from test_google_business import OWNER, OPS, ADMIN, SECOND_OWNER, actors, gbp_env

PREFIX = "/api/v1/meta-business"


@pytest_asyncio.fixture
async def meta_env(gbp_env, monkeypatch):
    env = gbp_env
    for key, value in {"ENABLED": "true", "APP_ID": "123456789", "APP_SECRET": "SYNTHETIC-META-APP-SECRET", "CONFIG_ID": "987654321",
                       "GRAPH_VERSION": "v26.0", "TOKEN_KEY": Fernet.generate_key().decode(), "PUBLIC_URL": "https://t24-crm.com",
                       "EXPECTED_SCOPES": "pages_show_list,pages_read_engagement,instagram_basic", "LOGIN_CONFIG_REVIEWED": "true"}.items():
        monkeypatch.setenv("T24_META_" + key, value)
    fake = SimpleNamespace(reads=[], exchanges=[], failure=None, started=None, release=None,
        items=[{"platform": "facebook", "external_id": "111", "page_id": "111", "name": "Synthetic Page", "observations": ["Meta 返回 Page 任务：CREATE_CONTENT"]},
               {"platform": "instagram", "external_id": "222", "page_id": "111", "name": "Synthetic Page · Instagram", "linked_page_name": "Synthetic Page", "observations": []}])
    real_client = provider.MetaClient
    class FakeClient:
        def __init__(self, token_encrypted=None): self.token = token_encrypted
        async def assets(self):
            fake.reads.append("assets")
            if fake.started is not None: fake.started.set(); await fake.release.wait()
            if fake.failure: raise provider.ProviderError(fake.failure)
            return {"items": copy.deepcopy(fake.items), "truncated": False}
        async def exchange(self, code):
            fake.exchanges.append(code)
            if fake.started is not None: fake.started.set(); await fake.release.wait()
            if fake.failure: raise provider.ProviderError(fake.failure)
            return {"access_token": "SYNTHETIC-META-LONG-TOKEN", "expires_at": service.now().timestamp() + 86400,
                    "configuration": provider.configuration_fingerprint(), "user_id": "100"}
    monkeypatch.setattr(provider, "MetaClient", FakeClient)
    async with env.sessions() as db:
        db.add_all([Connection(id=1, owner_id=1, label="Owner Meta", token_encrypted=provider.encrypt({"access_token": "SYNTHETIC-META-USER-TOKEN", "expires_at": service.now().timestamp() + 86400, "configuration": provider.configuration_fingerprint()}), active=True, needs_reconnect=False, revision=1, connected_at=service.now()),
                    Connection(id=2, owner_id=9, label="SECRET-OTHER-META", token_encrypted="SECRET-OTHER-TOKEN", active=True, needs_reconnect=False, revision=1, connected_at=service.now())])
        await db.commit()
    app = FastAPI(); app.include_router(router)
    async def database():
        async with env.sessions() as db: yield db
    async def actor(): return env.user
    app.dependency_overrides[get_db] = database; app.dependency_overrides[get_current_user] = actor
    env.meta, env.meta_real_client = fake, real_client
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://t24-crm.com", follow_redirects=False) as client:
        env.meta_client = client
        yield env


async def assets(env, connection=1):
    value = await env.meta_client.get(f"{PREFIX}/connections/{connection}/assets")
    assert value.status_code == 200, value.text
    return value.json()["items"]


async def bind(env, asset=None, **updates):
    if asset is None: asset = (await assets(env))[0]
    body = {"request_id": str(uuid4()), "customer_id": 10, "connection_id": 1, "asset_ref": asset["asset_ref"], "confirmed": True, **updates}
    return await env.meta_client.post(PREFIX + "/bindings", json=body), body


async def protected_snapshot(env):
    async with env.sessions() as db:
        names = (await db.scalars(text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'meta_business_%' ORDER BY name"))).all()
        return {name: sorted(repr(tuple(row)) for row in (await db.execute(text('SELECT * FROM "' + name.replace('"', '""') + '"'))).all()) for name in names}


@pytest.mark.asyncio
async def test_status_owner_redaction_and_stage_one_has_no_staff_or_public_capabilities(meta_env):
    env = meta_env
    response = await env.meta_client.get(PREFIX + "/status"); value = response.json()
    assert response.status_code == 200 and value["phase"] == "connection" and value["configured"]
    assert value["publishing_implemented"] is False and value["comments_implemented"] is False
    assert [x["id"] for x in value["connections"]] == [1]
    assert value["authorization"]["redirect_uri"] == provider.CALLBACK and value["authorization"]["token_type"] == "user"
    assert response.headers["cache-control"] == "private, no-store" and response.headers["referrer-policy"] == "no-referrer"
    assert all(x not in response.text for x in ("SYNTHETIC-META-USER-TOKEN", "SECRET-OTHER", "SECRET-PRIVATE-NOTES", "token_encrypted"))
    for user in (OPS, ADMIN):
        env.user = user; value = (await env.meta_client.get(PREFIX + "/status")).json()
        assert value["is_owner"] is False and value["bindings"] == value["connections"] == [] and value["authorization"] is None
        for path in ("/options", "/connections/1/assets", "/requests/" + str(uuid4())):
            assert (await env.meta_client.get(PREFIX + path)).status_code == 403
    assert not env.meta.reads and not env.meta.exchanges


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["finance", "sales", "design", "sales_partner"])
async def test_unrelated_roles_cannot_probe_even_with_broad_role_config(meta_env, role):
    env = meta_env; env.user = next(x for x in actors() if x.role == role)
    assert (await env.meta_client.get(PREFIX + "/status")).status_code == 403
    assert (await env.meta_client.post(PREFIX + "/oauth/start", json={"request_id": str(uuid4()), "confirmed": True})).status_code == 403
    assert not env.meta.reads and not env.meta.exchanges


@pytest.mark.asyncio
async def test_assets_are_opaque_connection_bound_and_binding_is_idempotent_without_shared_mutations(meta_env):
    env = meta_env; before = await protected_snapshot(env)
    items = await assets(env)
    assert {x["platform"] for x in items} == {"facebook", "instagram"}
    assert all("external_id" not in x and "page_id" not in x and len(x["asset_ref"]) == 32 for x in items)
    first, body = await bind(env, items[0]); assert first.status_code == 201, first.text
    again = await env.meta_client.post(PREFIX + "/bindings", json=body)
    recovered = await env.meta_client.get(PREFIX + "/requests/" + body["request_id"])
    assert first.json() == again.json() == recovered.json()
    assert len(env.meta.reads) == 2  # initial discovery + live bind verification, never replay
    response, _ = await bind(env, items[1]); assert response.status_code == 201
    assert response.json()["platform"] == "instagram"
    assert await protected_snapshot(env) == before
    assert not env.fake.reads and not env.fake.writes and not env.meta.exchanges
    for endpoint in ("/bindings/1/posts", "/bindings/1/comments", "/bindings/1/comment-replies"):
        assert (await env.meta_client.post(PREFIX + endpoint, json={})).status_code == 404


@pytest.mark.asyncio
async def test_foreign_owner_raw_ids_stale_refs_and_global_duplicates_are_rejected(meta_env):
    env = meta_env
    assert (await env.meta_client.get(PREFIX + "/connections/2/assets")).status_code == 404
    response, _ = await bind(env, {"asset_ref": "111"}); assert response.status_code == 422
    old = (await assets(env))[0]; fresh = (await assets(env))[0]
    response, _ = await bind(env, old); assert response.status_code == 409
    response, body = await bind(env, fresh); assert response.status_code == 201
    mismatch = {**body, "customer_id": 20}
    assert (await env.meta_client.post(PREFIX + "/bindings", json=mismatch)).status_code == 409
    response, _ = await bind(env, fresh, customer_id=20); assert response.status_code == 409
    env.user = SECOND_OWNER
    assert (await env.meta_client.get(PREFIX + "/requests/" + body["request_id"])).status_code == 404
    assert (await env.meta_client.post(PREFIX + "/bindings/1/disconnect", json={"confirmed": True, "expected_revision": 1})).status_code == 404


@pytest.mark.asyncio
async def test_connection_discovery_and_bind_recheck_live_access(meta_env):
    env = meta_env; selected = (await assets(env))[0]; env.meta.items = []
    response, _ = await bind(env, selected); assert response.status_code == 409
    async with env.sessions() as db: assert (await db.scalar(select(func_count(Binding)))) == 0


def func_count(model):
    from sqlalchemy import func
    return func.count(model.id)


@pytest.mark.asyncio
async def test_disconnect_preserves_history_and_replay_cannot_restore_binding(meta_env):
    env = meta_env; response, body = await bind(env); row = response.json()
    disconnected = await env.meta_client.post(f"{PREFIX}/bindings/{row['id']}/disconnect", json={"confirmed": True, "expected_revision": row["revision"]})
    assert disconnected.status_code == 200 and disconnected.json()["active"] is False
    replay = await env.meta_client.post(PREFIX + "/bindings", json=body)
    assert replay.json()["active"] is False
    assert (await env.meta_client.post(f"{PREFIX}/bindings/{row['id']}/disconnect", json={"confirmed": True, "expected_revision": row["revision"]})).status_code == 409
    assert (await env.meta_client.post(PREFIX + "/connections/1/disconnect", json={"confirmed": True, "expected_revision": 1})).status_code == 200
    async with env.sessions() as db:
        connection = await db.get(Connection, 1); assert connection.token_encrypted is None and not connection.active
        assert not (await db.scalars(select(Asset).where(Asset.connection_id == 1, Asset.active.is_(True)))).all()


async def start(env, **updates):
    body = {"request_id": str(uuid4()), "confirmed": True, **updates}
    response = await env.meta_client.post(PREFIX + "/oauth/start", json=body)
    assert response.status_code == 200, response.text
    state = parse_qs(urlsplit(response.json()["authorization_url"]).query)["state"][0]
    return response, body, state


@pytest.mark.asyncio
async def test_oauth_exact_config_cookie_one_use_and_safe_same_request_recovery(meta_env):
    env = meta_env; before = await protected_snapshot(env)
    response, body, state = await start(env)
    url = urlsplit(response.json()["authorization_url"]); query = parse_qs(url.query)
    assert url.netloc == "www.facebook.com" and url.path == "/v26.0/dialog/oauth"
    assert set(query) == {"client_id", "config_id", "redirect_uri", "response_type", "state"} and query["redirect_uri"] == [provider.CALLBACK]
    cookie = response.headers["set-cookie"]; assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    recovered = await env.meta_client.get(PREFIX + "/oauth/requests/" + body["request_id"])
    assert recovered.json()["authorization_url"] == response.json()["authorization_url"]
    replay = await env.meta_client.post(PREFIX + "/oauth/start", json=body)
    assert replay.json()["authorization_url"] == response.json()["authorization_url"]
    async with env.sessions() as db:
        record = await db.scalar(select(State).where(State.request_id == body["request_id"]))
        assert state not in record.flow_encrypted and record.state_hash == service.hash_text(state)
    callback = await env.meta_client.get(PREFIX + "/oauth/callback", params={"state": state, "code": "SYNTHETIC-ONE-USE-CODE"})
    assert callback.status_code == 303 and callback.headers["location"] == "/media-ops?meta=connected"
    assert len(env.meta.exchanges) == 1
    second = await env.meta_client.get(PREFIX + "/oauth/callback", params={"state": state, "code": "SYNTHETIC-ONE-USE-CODE"})
    assert second.headers["location"] == "/media-ops?meta=failed" and len(env.meta.exchanges) == 1
    assert (await env.meta_client.get(PREFIX + "/oauth/requests/" + body["request_id"])).status_code == 409
    assert await protected_snapshot(env) == before


@pytest.mark.asyncio
async def test_wrong_cookie_expired_state_and_foreign_reconnect_never_exchange(meta_env):
    env = meta_env; _, body, state = await start(env)
    env.meta_client.cookies.clear()
    response = await env.meta_client.get(PREFIX + "/oauth/callback", params={"state": state, "code": "SECRET-CODE"})
    assert response.headers["location"].endswith("failed") and not env.meta.exchanges
    async with env.sessions() as db:
        row = await db.scalar(select(State).where(State.request_id == body["request_id"])); row.expires_at = service.now() - service.timedelta(seconds=1); await db.commit()
    assert (await env.meta_client.get(PREFIX + "/oauth/requests/" + body["request_id"])).status_code == 409
    assert (await env.meta_client.post(PREFIX + "/oauth/start", json={"request_id": str(uuid4()), "confirmed": True, "reconnect_connection_id": 2})).status_code == 404


@pytest.mark.asyncio
async def test_reconnect_invalidates_discovery_and_bindings_until_explicit_rebind(meta_env):
    env = meta_env; response, _ = await bind(env); original = response.json()
    _, _, state = await start(env, reconnect_connection_id=1)
    response = await env.meta_client.get(PREFIX + "/oauth/callback", params={"state": state, "code": "RECONNECT-CODE"})
    assert response.headers["location"].endswith("connected")
    current = (await env.meta_client.get(PREFIX + "/status")).json()
    assert current["bindings"][0]["active"] is False and current["bindings"][0]["revision"] > original["revision"]
    selected = (await assets(env))[0]; rebound, _ = await bind(env, selected)
    assert rebound.status_code == 201 and rebound.json()["id"] != original["id"] and rebound.json()["active"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["disable_owner", "change_role", "disconnect", "revision"])
async def test_slow_read_releases_finance_writer_and_rechecks_current_owner_connection(meta_env, mutation):
    env = meta_env; env.meta.started, env.meta.release = asyncio.Event(), asyncio.Event()
    operation = asyncio.create_task(env.meta_client.get(PREFIX + "/connections/1/assets")); await env.meta.started.wait()
    async with env.sessions() as db:
        await asyncio.wait_for(db.execute(text("UPDATE financial_canary SET amount='199.01' WHERE id=1")), 1)
        if mutation in {"disable_owner", "change_role"}:
            owner = await db.get(Employees, 1); setattr(owner, "status" if mutation == "disable_owner" else "role", "disabled" if mutation == "disable_owner" else "ops")
        else:
            connection = await db.get(Connection, 1)
            if mutation == "disconnect": connection.active = False; connection.token_encrypted = None
            else: connection.revision += 1
        await db.commit()
    env.meta.release.set(); result = await operation
    assert result.status_code in {403, 404, 409}
    async with env.sessions() as db: assert (await db.scalar(select(func_count(Asset)))) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["disconnect", "owner_disabled", "configuration"])
async def test_slow_callback_cannot_overwrite_newer_disconnect_or_persist_after_owner_revocation(meta_env, monkeypatch, change):
    env = meta_env; _, _, state = await start(env, reconnect_connection_id=1)
    env.meta.started, env.meta.release = asyncio.Event(), asyncio.Event()
    operation = asyncio.create_task(env.meta_client.get(PREFIX + "/oauth/callback", params={"state": state, "code": "SLOW-CODE"})); await env.meta.started.wait()
    async with env.sessions() as db:
        if change == "disconnect":
            row = await db.get(Connection, 1); row.active = False; row.token_encrypted = None; row.revision += 1
        elif change == "owner_disabled":
            owner = await db.get(Employees, 1); owner.status = "disabled"
        else: monkeypatch.setenv("T24_META_CONFIG_ID", "987654322")
        await db.commit()
    env.meta.release.set(); result = await operation
    assert result.headers["location"].endswith("failed")
    async with env.sessions() as db:
        row = await db.get(Connection, 1)
        if change == "disconnect": assert row.token_encrypted is None and not row.active
        else: assert row.revision == 1 and "SYNTHETIC-META-USER-TOKEN" in provider.decrypt(row.token_encrypted)["access_token"]


@pytest.mark.asyncio
async def test_explicit_disconnect_frees_asset_and_customer_but_retains_old_request_history(meta_env):
    env = meta_env; before = await protected_snapshot(env)
    first, original_request = await bind(env); original = first.json()
    assert (await env.meta_client.post(f"{PREFIX}/bindings/{original['id']}/disconnect", json={"confirmed": True, "expected_revision": 1})).status_code == 200
    original_assets = copy.deepcopy(env.meta.items)
    env.meta.items = [{"platform": "facebook", "external_id": "444", "page_id": "444", "name": "Replacement Page", "observations": []}]
    replacement, _ = await bind(env); assert replacement.status_code == 201 and replacement.json()["id"] != original["id"]
    env.meta.items = original_assets
    reassigned, _ = await bind(env, customer_id=20); assert reassigned.status_code == 201
    assert reassigned.json()["customer_id"] == 20 and reassigned.json()["id"] != original["id"]
    old = await env.meta_client.post(PREFIX + "/bindings", json=original_request)
    assert old.status_code == 201 and old.json()["id"] == original["id"] and old.json()["active"] is False
    assert await protected_snapshot(env) == before


@pytest.mark.asyncio
async def test_old_disconnect_tab_cannot_wipe_reauthorized_connection(meta_env):
    env = meta_env
    first = await env.meta_client.post(PREFIX + "/connections/1/disconnect", json={"confirmed": True, "expected_revision": 1})
    assert first.status_code == 200
    assert (await env.meta_client.post(PREFIX + "/connections/1/disconnect", json={"confirmed": True, "expected_revision": 1})).json() == first.json()
    _, _, state = await start(env, reconnect_connection_id=1)
    assert (await env.meta_client.get(PREFIX + "/oauth/callback", params={"state": state, "code": "NEWER-REAUTH"})).headers["location"].endswith("connected")
    assert (await env.meta_client.post(PREFIX + "/connections/1/disconnect", json={"confirmed": True, "expected_revision": 1})).status_code == 409
    async with env.sessions() as db:
        row = await db.get(Connection, 1); assert row.active and row.token_encrypted and row.revision == 3


@pytest.mark.asyncio
async def test_slow_bind_rechecks_customer_cooperation_before_creating_binding(meta_env):
    env = meta_env; selected = (await assets(env))[0]
    env.meta.started, env.meta.release = asyncio.Event(), asyncio.Event()
    operation = asyncio.create_task(bind(env, selected)); await env.meta.started.wait()
    async with env.sessions() as db:
        customer = await db.get(Customers, 10); customer.status = "lost"; await db.commit()
    env.meta.release.set(); response, _ = await operation
    assert response.status_code == 409
    async with env.sessions() as db: assert (await db.scalar(select(func_count(Binding)))) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("same_request", [True, False])
async def test_concurrent_binding_requests_have_one_active_effect_and_durable_recovery(meta_env, same_request):
    env = meta_env; selected = (await assets(env))[0]; request = str(uuid4())
    first, second = await asyncio.gather(bind(env, selected, request_id=request),
        bind(env, selected, request_id=request if same_request else str(uuid4())))
    assert sorted([first[0].status_code, second[0].status_code]) == ([201, 201] if same_request else [201, 409])
    async with env.sessions() as db:
        assert (await db.scalar(select(func_count(Binding)).where(Binding.active.is_(True)))) == 1
        assert (await db.scalar(select(func_count(Request)))) == 1
    assert (await env.meta_client.get(PREFIX + "/requests/" + (first[1]["request_id"] if first[0].status_code == 201 else second[1]["request_id"]))).status_code == 200


@pytest.mark.asyncio
async def test_strict_input_and_uncooperating_customer_are_not_bindable(meta_env):
    env = meta_env; selected = (await assets(env))[0]
    for changes in ({"confirmed": "true"}, {"customer_id": True}, {"asset_id": "111"}):
        response, _ = await bind(env, selected, **changes); assert response.status_code == 422
    async with env.sessions() as db:
        customer = await db.get(Customers, 10); customer.status = "lost"; await db.commit()
    response, _ = await bind(env, selected); assert response.status_code == 409


def test_callback_log_filter_redacts_only_meta_query_in_actual_formatter():
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 1, '%s - "%s %s HTTP/%s" %d', ("client", "GET", PREFIX + "/oauth/callback?code=SECRET&state=SECRET", "1.1", 303), None)
    MetaOAuthAccessLogFilter().filter(record); value = record.getMessage()
    assert "SECRET" not in value and PREFIX + "/oauth/callback" in value
    other = logging.LogRecord("uvicorn.access", logging.INFO, "", 1, "%s %s %s", ("client", "GET", "/api/v1/google-business/oauth/callback?untouched=1"), None)
    MetaOAuthAccessLogFilter().filter(other); assert "untouched=1" in other.getMessage()


def test_additive_migration_only_adds_five_empty_tables_and_keeps_existing_rows_schema_sequence(tmp_path):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/bde8da01f247_meta_business_connections.py"
    spec = importlib.util.spec_from_file_location("actual_meta_connection_migration", path); migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///" + str(tmp_path / "migration.db"))
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE finance_canary(id INTEGER PRIMARY KEY AUTOINCREMENT,amount TEXT)")
        conn.exec_driver_sql("INSERT INTO finance_canary VALUES(42,'198.00')")
        conn.exec_driver_sql("CREATE TABLE google_canary(id INTEGER PRIMARY KEY,state TEXT)")
        conn.exec_driver_sql("INSERT INTO google_canary VALUES(7,'LIVE')")
        conn.exec_driver_sql("PRAGMA application_id=43"); conn.exec_driver_sql("PRAGMA user_version=17")
        before = conn.exec_driver_sql("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY name").all()
        sequence = conn.exec_driver_sql("SELECT * FROM sqlite_sequence").all()
        with Operations.context(MigrationContext.configure(conn)): migration.upgrade()
        assert migration.down_revision == "acd7c9d0e136" and migration.revision == "bde8da01f247"
        assert set(inspect(conn).get_table_names()) - {"finance_canary", "google_canary"} == service.TABLES
        for name in service.TABLES: assert conn.exec_driver_sql('SELECT COUNT(*) FROM "' + name + '"').scalar() == 0
        assert conn.exec_driver_sql("SELECT * FROM finance_canary").all() == [(42, "198.00")]
        assert conn.exec_driver_sql("SELECT * FROM google_canary").all() == [(7, "LIVE")]
        assert conn.exec_driver_sql("SELECT * FROM sqlite_sequence").all() == sequence
        after = conn.exec_driver_sql("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY name").all()
        assert all(row in after for row in before)
        assert conn.exec_driver_sql("PRAGMA application_id").scalar() == 43 and conn.exec_driver_sql("PRAGMA user_version").scalar() == 17
    engine.dispose()
