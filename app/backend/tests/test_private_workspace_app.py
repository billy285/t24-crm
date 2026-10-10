"""The deployed sidecar must keep real CRM auth checks and never write its DB."""
import hashlib
import logging
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import text

from core.config import settings
from core.database import db_manager
from services import emp_auth, private_workspace as storage
from services.employee_sessions import _credential_fingerprint
from services.private_workspace_app import create_private_workspace_app


SYNTHETIC_JWT_KEY = "private-sidecar-synthetic-jwt-key-for-tests-only"


def test_standalone_import_does_not_load_crm_or_financial_startup_modules():
    probe = subprocess.run([sys.executable, "-c", (
        "import sys; import services.private_workspace_app; "
        "forbidden={'main','services.database','services.deal_payment_sync',"
        "'services.customer_lifecycle','services.automation_monitor'}; "
        "assert not (forbidden & set(sys.modules)), forbidden & set(sys.modules)"
    )], capture_output=True, text=True)
    assert probe.returncode == 0, probe.stderr


@pytest_asyncio.fixture
async def private_app(monkeypatch, tmp_path):
    business_path = tmp_path / "business.db"
    private_path = tmp_path / "personal" / "workspace.db"
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", SYNTHETIC_JWT_KEY)
    monkeypatch.setattr(emp_auth, "SECRET_KEY", SYNTHETIC_JWT_KEY)
    monkeypatch.setitem(settings.__dict__, "jwt_secret_key", SYNTHETIC_JWT_KEY)
    monkeypatch.setitem(settings.__dict__, "jwt_algorithm", "HS256")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{business_path}")
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{business_path}")
    monkeypatch.setenv("PRIVATE_WORKSPACE_DATABASE_URL", f"sqlite+aiosqlite:///{private_path}")
    monkeypatch.setenv("PRIVATE_WORKSPACE_OWNER_IDS", "1")
    monkeypatch.setenv("PRIVATE_WORKSPACE_ENCRYPTION_KEY", "synthetic-sidecar-encryption-key-for-tests-only")

    # Exercise the production auth SQL and revocable-session fingerprint, with
    # independent synthetic fixture records instead of dependency-auth bypasses.
    with sqlite3.connect(business_path) as db:
        db.execute("CREATE TABLE employees (id INTEGER PRIMARY KEY, user_id TEXT, name TEXT, role TEXT, "
                   "phone TEXT, email TEXT, status TEXT, password TEXT, updated_at TEXT)")
        db.execute("CREATE TABLE employee_auth_sessions (id TEXT PRIMARY KEY, employee_id INTEGER, "
                   "credential_fingerprint TEXT, created_at INTEGER, expires_at INTEGER, revoked_at INTEGER)")
        db.execute("CREATE TABLE finance_sentinel (id INTEGER PRIMARY KEY, amount INTEGER NOT NULL)")
        db.execute("INSERT INTO finance_sentinel VALUES (1, 70000)")
        for employee_id, role, status in ((1, "super_admin", "active"), (2, "super_admin", "active"),
                                          (3, "admin", "active"), (4, "sales", "active"),
                                          (5, "super_admin", "inactive")):
            password = f"synthetic-password-hash-{employee_id}"
            db.execute("INSERT INTO employees VALUES (?, ?, ?, ?, NULL, ?, ?, ?, NULL)",
                       (employee_id, f"synthetic-{employee_id}", f"Fixture {employee_id}", role,
                        f"synthetic-{employee_id}@invalid.test", status, password))
            db.execute("INSERT INTO employee_auth_sessions VALUES (?, ?, ?, ?, ?, NULL)",
                       (f"synthetic-session-{employee_id}", employee_id,
                        _credential_fingerprint({"id": employee_id, "password": password}),
                        int(time.time()), int(time.time()) + 3600))

    async def forbidden_crm_initialization(*unused, **arguments):
        raise AssertionError("Standalone private requests must never initialize CRM")

    monkeypatch.setattr(db_manager, "ensure_initialized", forbidden_crm_initialization)
    monkeypatch.setattr(db_manager, "init_db", forbidden_crm_initialization)
    monkeypatch.setattr(db_manager, "create_tables", forbidden_crm_initialization)
    monkeypatch.setattr(db_manager, "check_and_repair_existing_tables", forbidden_crm_initialization)

    await storage.close_private_workspace_storage()
    app = create_private_workspace_app()

    def headers(employee_id=1, *, sid=None):
        claims = {"emp_id": employee_id, "role": "super_admin",
                  "sid": sid if sid is not None else f"synthetic-session-{employee_id}"}
        return {"Authorization": "Bearer " + emp_auth.create_access_token(claims)}

    async with app.router.lifespan_context(app):
        # Unexpected errors must be contained before the server boundary. With
        # this flag a Starlette handler that re-raises makes the test fail.
        async with AsyncClient(transport=ASGITransport(app, raise_app_exceptions=True), base_url="http://test") as client:
            yield SimpleNamespace(app=app, client=client, business_path=business_path,
                                  private_path=private_path, headers=headers)


@pytest.mark.asyncio
async def test_manual_crud_is_persistent_and_crm_connection_is_read_only(private_app):
    value = private_app
    before = hashlib.sha256(value.business_path.read_bytes()).hexdigest()
    assert (await value.client.get("/ready")).json() == {"ready": True}
    assert (await value.client.get("/api/v1/private-workspace/access", headers=value.headers())).json() == {"allowed": True}
    created = await value.client.post("/api/v1/private-workspace/items", headers=value.headers(),
                                      json={"title": "Synthetic deployment verification", "summary": "Private only"})
    assert created.status_code == 201
    identity = created.json()["item"]["id"]
    changed = await value.client.patch(f"/api/v1/private-workspace/items/{identity}", headers=value.headers(),
                                      json={"title": "Synthetic updated task", "action_status": "done"})
    assert changed.status_code == 200 and changed.json()["item"]["action_status"] == "done"
    assert (await value.client.get("/api/v1/private-workspace/items", headers=value.headers())).json()["items"][0]["title"] == "Synthetic updated task"
    assert (await value.client.delete(f"/api/v1/private-workspace/items/{identity}", headers=value.headers())).json()["item"]["action_status"] == "archived"
    await value.client.patch(f"/api/v1/private-workspace/items/{identity}", headers=value.headers(), json={"action_status": "open"})
    # Re-open the storage, so the test does not only observe in-memory ORM state.
    await storage.close_private_workspace_storage()
    assert (await value.client.get("/api/v1/private-workspace", headers=value.headers())).json()["items"][0]["id"] == identity

    async with value.app.state.private_business_sessions() as business_db:
        with pytest.raises(Exception, match="readonly"):
            await business_db.execute(text("UPDATE finance_sentinel SET amount = 0"))
    assert hashlib.sha256(value.business_path.read_bytes()).hexdigest() == before
    with sqlite3.connect(value.business_path) as db:
        assert db.execute("SELECT amount FROM finance_sentinel").fetchone()[0] == 70000
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'private_%'").fetchall()
    with sqlite3.connect(value.private_path) as db:
        assert db.execute("SELECT local_title, action_status FROM private_items WHERE id = ?", (identity,)).fetchone() == ("Synthetic updated task", "open")


@pytest.mark.asyncio
@pytest.mark.parametrize("employee_id", [2, 3, 4])
async def test_other_admins_and_sales_are_denied_despite_signed_super_admin_claim(private_app, employee_id):
    value = private_app
    assert (await value.client.get("/api/v1/private-workspace/access", headers=value.headers(employee_id))).json() == {"allowed": False}
    response = await value.client.get("/api/v1/private-workspace", headers=value.headers(employee_id))
    assert response.status_code == 403 and response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_missing_revoked_and_refresh_sessions_fail_closed(private_app):
    value = private_app
    for headers in ({}, value.headers(5), value.headers(sid="nonexistent-session"), value.headers(sid="")):
        response = await value.client.get("/api/v1/private-workspace", headers=headers)
        assert response.status_code == 401 and response.headers["cache-control"] == "no-store"
    refresh = jwt.encode({"emp_id": 1, "token_type": "employee_refresh", "sid": "synthetic-session-1",
                          "exp": int(time.time()) + 300}, SYNTHETIC_JWT_KEY, algorithm="HS256")
    assert (await value.client.get("/api/v1/private-workspace", headers={"Authorization": "Bearer " + refresh})).status_code == 401
    legacy = jwt.encode({"sub": "1", "role": "super_admin", "exp": int(time.time()) + 300}, SYNTHETIC_JWT_KEY, algorithm="HS256")
    assert (await value.client.get("/api/v1/private-workspace", headers={"Authorization": "Bearer " + legacy})).status_code == 403
    with sqlite3.connect(value.business_path) as db:
        db.execute("UPDATE employee_auth_sessions SET revoked_at = ? WHERE employee_id = 1", (int(time.time()),))
    assert (await value.client.get("/api/v1/private-workspace", headers=value.headers())).status_code == 401


@pytest.mark.asyncio
async def test_live_owner_role_and_cross_owner_item_boundary(private_app, monkeypatch):
    value = private_app
    item = (await value.client.post("/api/v1/private-workspace/items", headers=value.headers(), json={"title": "Owner 1 only"})).json()["item"]
    monkeypatch.setenv("PRIVATE_WORKSPACE_OWNER_IDS", "1,2")
    assert (await value.client.patch(f"/api/v1/private-workspace/items/{item['id']}", headers=value.headers(2), json={"title": "Intrusion"})).status_code == 404
    with sqlite3.connect(value.business_path) as db:
        db.execute("UPDATE employees SET role = 'admin' WHERE id = 1")
    assert (await value.client.get("/api/v1/private-workspace", headers=value.headers())).status_code == 403


@pytest.mark.asyncio
async def test_errors_are_no_store_and_do_not_echo_private_values(private_app, caplog):
    value = private_app
    secret = "synthetic-rk_test_private-secret-not-to-log"
    @value.app.get("/synthetic-failure")
    async def failing_route():
        raise RuntimeError(secret)
    with caplog.at_level(logging.ERROR):
        failure = await value.client.get("/synthetic-failure?code=" + secret)
    assert failure.status_code == 500 and failure.headers["cache-control"] == "no-store"
    assert secret not in failure.text and secret not in caplog.text
    invalid = await value.client.post("/api/v1/private-workspace/items", headers=value.headers(), json={"title": "", "unknown": secret})
    assert invalid.status_code == 422 and invalid.headers["cache-control"] == "no-store" and secret not in invalid.text
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert (await value.client.get(path)).status_code == 404
    cors = await value.client.options("/api/v1/private-workspace", headers={"Origin": "https://untrusted.invalid", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in cors.headers


@pytest.mark.asyncio
async def test_missing_business_file_is_not_created(private_app, monkeypatch, tmp_path):
    missing = tmp_path / "missing.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{missing}")
    app = create_private_workspace_app()
    with pytest.raises(ValueError, match="not found"):
        async with app.router.lifespan_context(app):
            pass
    assert not missing.exists()


@pytest.mark.asyncio
async def test_private_database_cannot_alias_crm_during_startup(private_app, monkeypatch):
    value = private_app
    before = hashlib.sha256(value.business_path.read_bytes()).hexdigest()
    monkeypatch.setenv("PRIVATE_WORKSPACE_DATABASE_URL", f"sqlite+aiosqlite:///{value.business_path}")
    app = create_private_workspace_app()
    with pytest.raises(Exception, match="客户管理系统数据库"):
        async with app.router.lifespan_context(app):
            pass
    assert hashlib.sha256(value.business_path.read_bytes()).hexdigest() == before
