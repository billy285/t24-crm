"""Security regressions use only synthetic employees and isolated SQLite."""
import asyncio
import importlib.util
import time
from datetime import date, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, inspect, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from core.database import Base, db_manager, get_db
from models.employee_auth_sessions import EmployeeAuthSession
from models.employees import Employees
from models.commissions import SalesPartner
from routers.emp_auth_tokens import COOKIE_NAME, _secure_cookie_enabled
from routers import employees as employee_routes
from services.emp_auth import EmpAuthService, create_access_token, decode_access_token, hash_password
from services.employee_sessions import create_employee_session, session_enforcement_enabled
from services.security_tokens import create_refresh_token
from services import employee_sessions
from services import emp_auth, security_tokens


PASSWORD = "test-sales-password-123"


@pytest_asyncio.fixture
async def session_auth(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("ENFORCE_EMPLOYEE_STATUS", "true")
    monkeypatch.setenv("ENFORCE_EMPLOYEE_SESSIONS", "true")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        for employee_id, role, status in ((301, "sales", "active"), (302, "sales", "probation"), (303, "super_admin", "active")):
            db.add(Employees(
                id=employee_id, user_id=f"fixture-{employee_id}", name=f"Fixture {employee_id}",
                email=f"sales-{employee_id}@example.test", password=hash_password(PASSWORD), role=role, status=status,
            ))
        await db.commit()

    async def override_db():
        async with sessions() as db:
            yield db

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(db_manager, "async_session_maker", sessions)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        yield client, sessions
    if previous_override is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous_override
    await engine.dispose()


@pytest_asyncio.fixture
async def file_identity_auth(monkeypatch, tmp_path):
    """Actual endpoints share a file DB through independent request connections."""
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("ENFORCE_EMPLOYEE_STATUS", "true")
    monkeypatch.setenv("ENFORCE_EMPLOYEE_SESSIONS", "true")
    locked, release, waiter_started = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class ControlledSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            identity_lock = str(statement) == "UPDATE employees SET id = id WHERE 1 = 0"
            if identity_lock and self.info.get("identity_order") == "second":
                waiter_started.set()
            result = await super().execute(statement, *args, **kwargs)
            if identity_lock and self.info.get("identity_order") == "first":
                locked.set()
                await release.wait()
            return result

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'identity-order.sqlite'}", connect_args={"timeout": 5})
    sessions = async_sessionmaker(engine, class_=ControlledSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    password_hash = hash_password(PASSWORD)
    async with sessions() as db:
        for employee_id, role in ((301, "sales"), (302, "sales"), (303, "super_admin")):
            db.add(Employees(id=employee_id, user_id=f"identity-{employee_id}", name=f"Identity {employee_id}",
                email=f"sales-{employee_id}@example.test", password=password_hash, role=role, status="active"))
        await db.commit()

    async def override_db(request: Request = None):
        # Middleware invokes the override directly; dependency injection supplies
        # the Request for the route's separate transaction.
        async with sessions(info={"identity_order": request.headers.get("X-Test-Identity-Order") if request else None}) as db:
            yield db

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(db_manager, "async_session_maker", sessions)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
            yield client, sessions, locked, release, waiter_started
    finally:
        release.set()
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        await engine.dispose()


async def sign_in(client, employee_id=301, password=PASSWORD):
    response = await client.post("/api/v1/emp-auth/login", json={
        "email": f"sales-{employee_id}@example.test", "password": password,
    })
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    assert decode_access_token(token)["sid"]
    return token


def headers(token):
    return {"Authorization": f"Bearer {token}"}


async def issue_refresh(client, token):
    response = await client.post("/api/v1/emp-auth/set_refresh", headers=headers(token), json={"remember_me": True})
    assert response.status_code == 200, response.text
    return client.cookies.get(COOKIE_NAME)


async def check_access(client, token, expected):
    response = await client.get("/api/v1/emp-auth/me", headers=headers(token))
    assert response.status_code == expected, response.text
    return response


@pytest.mark.asyncio
async def test_security_upgrade_rejects_legacy_sessions_and_requires_password_login(session_auth):
    client, _ = session_auth
    legacy = create_access_token({"emp_id": 301, "role": "sales"})
    await check_access(client, legacy, 401)
    response = await client.post("/api/v1/emp-auth/set_refresh", headers=headers(legacy), json={"remember_me": True})
    assert response.status_code == 401
    client.cookies.set(COOKIE_NAME, create_refresh_token(subject="301"))
    assert (await client.post("/api/v1/emp-auth/refresh")).status_code == 401
    client.cookies.clear()
    token = await sign_in(client)
    await check_access(client, token, 200)
    await issue_refresh(client, token)
    response = await client.post("/api/v1/emp-auth/refresh")
    assert response.status_code == 200
    await check_access(client, response.json()["access_token"], 200)


@pytest.mark.asyncio
async def test_password_change_revokes_all_devices_without_affecting_another_sales_account(session_auth):
    client, _ = session_auth
    sales_a_device_one = await sign_in(client, 301)
    sales_a_device_two = await sign_in(client, 301)
    sales_b = await sign_in(client, 302)
    old_refresh = await issue_refresh(client, sales_a_device_one)
    changed = await client.post("/api/v1/emp-auth/change-password", headers=headers(sales_a_device_two), json={
        "current_password": PASSWORD, "new_password": "updated-test-password-456",
    })
    assert changed.status_code == 200
    await check_access(client, sales_a_device_one, 401)
    await check_access(client, sales_a_device_two, 401)
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, old_refresh)
    assert (await client.post("/api/v1/emp-auth/refresh")).status_code == 401
    await check_access(client, sales_b, 200)
    failed = await client.post("/api/v1/emp-auth/login", json={"email": "sales-301@example.test", "password": PASSWORD})
    assert failed.status_code == 401
    await check_access(client, await sign_in(client, 301, "updated-test-password-456"), 200)


@pytest.mark.asyncio
async def test_admin_password_reset_revokes_target_sessions_and_keeps_admin_and_other_sales(session_auth):
    client, _ = session_auth
    target = await sign_in(client, 301)
    other_sales = await sign_in(client, 302)
    admin = await sign_in(client, 303)
    refresh = await issue_refresh(client, target)
    denied = await client.post("/api/v1/emp-auth/set-password", headers=headers(other_sales), json={
        "employee_id": 301, "new_password": "reset-test-password-456",
    })
    assert denied.status_code == 403
    await check_access(client, target, 200)
    reset = await client.post("/api/v1/emp-auth/set-password", headers=headers(admin), json={
        "employee_id": 301, "new_password": "reset-test-password-456",
    })
    assert reset.status_code == 200
    await check_access(client, target, 401)
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, refresh)
    assert (await client.post("/api/v1/emp-auth/refresh")).status_code == 401
    await check_access(client, other_sales, 200)
    await check_access(client, admin, 200)


@pytest.mark.asyncio
async def test_cookie_only_logout_prevents_refresh_replay_and_keeps_other_device(session_auth):
    client, _ = session_auth
    current_device = await sign_in(client)
    other_device = await sign_in(client)
    cookie = await issue_refresh(client, current_device)
    refreshed = await client.post("/api/v1/emp-auth/refresh")
    assert refreshed.status_code == 200
    refreshed_access = refreshed.json()["access_token"]
    response = await client.post("/api/v1/emp-auth/logout")
    assert response.status_code == 200
    assert not client.cookies.get(COOKIE_NAME)
    await check_access(client, current_device, 401)
    await check_access(client, refreshed_access, 401)
    assert (await client.get("/api/v1/sales-leads/stats", headers=headers(refreshed_access))).status_code == 401
    await check_access(client, other_device, 200)
    client.cookies.set(COOKIE_NAME, cookie)
    assert (await client.post("/api/v1/emp-auth/refresh")).status_code == 401
    assert (await client.post("/api/v1/emp-auth/set_refresh", headers=headers(current_device), json={"remember_me": True})).status_code == 401


@pytest.mark.asyncio
async def test_header_only_logout_and_cross_employee_session_binding(session_auth):
    client, _ = session_auth
    sales_a = await sign_in(client, 301)
    sales_b = await sign_in(client, 302)
    wrong_identity = create_access_token({"emp_id": 302, "role": "super_admin", "sid": decode_access_token(sales_a)["sid"]})
    await check_access(client, wrong_identity, 401)
    # Even a signed token cannot revoke a session belonging to a different ID.
    assert (await client.post("/api/v1/emp-auth/logout", headers=headers(wrong_identity))).status_code == 200
    await check_access(client, sales_a, 200)
    assert (await client.post("/api/v1/emp-auth/logout", headers=headers(sales_a))).status_code == 200
    await check_access(client, sales_a, 401)
    await check_access(client, sales_b, 200)


@pytest.mark.asyncio
async def test_expired_access_can_only_revoke_its_signed_session(session_auth):
    client, _ = session_auth
    current = await sign_in(client)
    cookie = await issue_refresh(client, current)
    expired = create_access_token({"emp_id": 301, "role": "sales", "sid": decode_access_token(current)["sid"]}, expires_delta=timedelta(seconds=-1))
    await check_access(client, expired, 401)
    client.cookies.clear()
    assert (await client.post("/api/v1/emp-auth/logout", headers=headers(expired))).status_code == 200
    await check_access(client, current, 401)
    client.cookies.set(COOKIE_NAME, cookie)
    assert (await client.post("/api/v1/emp-auth/refresh")).status_code == 401


@pytest.mark.asyncio
async def test_employee_status_role_and_session_expiry_are_read_from_current_database(session_auth):
    client, sessions = session_auth
    token = await sign_in(client, 302)
    await check_access(client, token, 200)  # Probation employees can log in.
    cookie = await issue_refresh(client, token)
    async with sessions() as db:
        await db.execute(update(Employees).where(Employees.id == 302).values(role="sales_manager"))
        await db.commit()
    assert (await check_access(client, token, 200)).json()["role"] == "sales_manager"
    response = await client.post("/api/v1/emp-auth/refresh")
    assert response.status_code == 200
    assert decode_access_token(response.json()["access_token"])["role"] == "sales_manager"
    async with sessions() as db:
        await db.execute(update(Employees).where(Employees.id == 302).values(status="disabled"))
        await db.commit()
    await check_access(client, token, 401)
    assert (await client.post("/api/v1/emp-auth/refresh")).status_code == 401
    async with sessions() as db:
        await db.execute(update(Employees).where(Employees.id == 302).values(status="active"))
        await db.execute(update(EmployeeAuthSession).where(EmployeeAuthSession.id == decode_access_token(token)["sid"]).values(expires_at=int(time.time()) - 1))
        await db.commit()
    await check_access(client, token, 401)
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, cookie)
    assert (await client.post("/api/v1/emp-auth/refresh")).status_code == 401


@pytest.mark.asyncio
async def test_password_write_outside_auth_service_cannot_preserve_a_stale_session(session_auth):
    client, sessions = session_auth
    token = await sign_in(client)
    await issue_refresh(client, token)
    async with sessions() as db:
        await db.execute(update(Employees).where(Employees.id == 301).values(password=hash_password("external-test-password-456")))
        await db.commit()
    await check_access(client, token, 401)
    assert (await client.post("/api/v1/emp-auth/refresh")).status_code == 401


@pytest.mark.asyncio
async def test_password_reset_rolls_back_if_session_revocation_fails(session_auth, monkeypatch):
    client, _ = session_auth
    token = await sign_in(client)

    async def fail_revocation(*_args, **_kwargs):
        raise RuntimeError("fixture revocation failure")

    monkeypatch.setattr("services.employee_sessions.revoke_employee_sessions", fail_revocation)
    response = await client.post("/api/v1/emp-auth/change-password", headers=headers(token), json={
        "current_password": PASSWORD, "new_password": "must-not-be-persisted-456",
    })
    assert response.status_code == 500
    await check_access(client, token, 200)
    await check_access(client, await sign_in(client, 301, PASSWORD), 200)
    rejected = await client.post("/api/v1/emp-auth/login", json={"email": "sales-301@example.test", "password": "must-not-be-persisted-456"})
    assert rejected.status_code == 401


@pytest.mark.asyncio
async def test_login_using_stale_password_snapshot_cannot_race_password_reset(session_auth):
    client, sessions = session_auth
    async with sessions() as db:
        stale_employee = await EmpAuthService(db).get_employee_by_id(301)
    async with sessions() as db:
        assert await EmpAuthService(db).update_password(301, "race-test-password-456")
    async with sessions() as db:
        with pytest.raises(HTTPException) as denied:
            await create_employee_session(db, stale_employee)
        assert denied.value.status_code == 401
        assert not (await db.scalars(select(EmployeeAuthSession))).all()


@pytest.mark.asyncio
@pytest.mark.parametrize("reactivate", [False, True])
async def test_authenticated_login_snapshot_cannot_finish_after_offboarding(session_auth, reactivate):
    client, sessions = session_auth
    async with sessions() as db:
        stale_employee = await EmpAuthService(db).authenticate("sales-301@example.test", PASSWORD)
        assert stale_employee["status"] == "active"
    admin = await sign_in(client, 303)
    disabled = await client.put("/api/v1/entities/employees/301", headers=headers(admin), json={"status": "disabled"})
    assert disabled.status_code == 200, disabled.text
    if reactivate:
        resumed = await client.put("/api/v1/entities/employees/301", headers=headers(admin), json={"status": "active"})
        assert resumed.status_code == 200, resumed.text
    async with sessions() as db:
        with pytest.raises(HTTPException) as denied:
            await create_employee_session(db, stale_employee)
        assert denied.value.status_code == 401
        assert not (await db.scalars(select(EmployeeAuthSession).where(EmployeeAuthSession.employee_id == 301))).all()
    if reactivate:
        await check_access(client, await sign_in(client, 301), 200)


@pytest.mark.asyncio
async def test_authenticated_login_snapshot_cannot_finish_after_employee_delete(session_auth):
    client, sessions = session_auth
    async with sessions() as db:
        stale_employee = await EmpAuthService(db).authenticate("sales-301@example.test", PASSWORD)
    admin = await sign_in(client, 303)
    deleted = await client.delete("/api/v1/entities/employees/301", headers=headers(admin))
    assert deleted.status_code == 200, deleted.text
    async with sessions() as db:
        with pytest.raises(HTTPException) as denied:
            await create_employee_session(db, stale_employee)
        assert denied.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["disable", "disable-reenable", "password", "delete"])
async def test_login_endpoint_cannot_complete_a_paused_outdated_authentication(session_auth, monkeypatch, change):
    client, sessions = session_auth
    admin = await sign_in(client, 303)
    authenticated = asyncio.Event()
    continue_login = asyncio.Event()
    original_authenticate = EmpAuthService.authenticate
    pause_next = True

    async def paused_authenticate(self, email, password):
        nonlocal pause_next
        employee = await original_authenticate(self, email, password)
        if email == "sales-301@example.test" and pause_next:
            pause_next = False
            authenticated.set()
            await continue_login.wait()
        return employee

    monkeypatch.setattr(EmpAuthService, "authenticate", paused_authenticate)
    pending_login = asyncio.create_task(client.post("/api/v1/emp-auth/login", json={
        "email": "sales-301@example.test", "password": PASSWORD,
    }))
    try:
        await asyncio.wait_for(authenticated.wait(), 5)
        if change.startswith("disable"):
            assert (await client.put("/api/v1/entities/employees/301", headers=headers(admin), json={"status": "disabled"})).status_code == 200
            if change == "disable-reenable":
                assert (await client.put("/api/v1/entities/employees/301", headers=headers(admin), json={"status": "active"})).status_code == 200
        elif change == "password":
            assert (await client.post("/api/v1/emp-auth/set-password", headers=headers(admin), json={
                "employee_id": 301, "new_password": "paused-test-password-456",
            })).status_code == 200
        else:
            assert (await client.delete("/api/v1/entities/employees/301", headers=headers(admin))).status_code == 200
    finally:
        continue_login.set()
    denied = await asyncio.wait_for(pending_login, 5)
    assert denied.status_code == 401, denied.text
    async with sessions() as db:
        assert not (await db.scalars(select(EmployeeAuthSession).where(EmployeeAuthSession.employee_id == 301))).all()
    if change == "disable-reenable":
        await check_access(client, await sign_in(client, 301), 200)


@pytest.mark.asyncio
async def test_employee_update_generation_is_server_owned_but_does_not_revoke_valid_sessions(session_auth):
    client, sessions = session_auth
    token = await sign_in(client, 301)
    admin = await sign_in(client, 303)
    async with sessions() as db:
        stale_employee = await EmpAuthService(db).authenticate("sales-301@example.test", PASSWORD)
    edited = await client.put("/api/v1/entities/employees/301", headers=headers(admin), json={
        "name": "Updated Fixture", "updated_at": "2000-01-01T00:00:00Z",
    })
    assert edited.status_code == 200, edited.text
    assert not edited.json()["updated_at"].startswith("2000-")
    await check_access(client, token, 200)
    async with sessions() as db:
        with pytest.raises(HTTPException) as denied:
            await create_employee_session(db, stale_employee)
        assert denied.value.status_code == 401
    await check_access(client, await sign_in(client, 301), 200)


@pytest.mark.asyncio
@pytest.mark.parametrize("first_writer", ["login", "offboarding"])
async def test_session_issuance_and_offboarding_serialize_across_real_sqlite_connections(tmp_path, first_writer):
    from services.employees import EmployeesService

    locked = asyncio.Event()
    release = asyncio.Event()
    second_started = asyncio.Event()

    class ControlledSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            sql = str(statement)
            is_guard = sql.startswith("UPDATE employees SET id = id WHERE id = :id AND status IN")
            is_revoke_lock = sql == "UPDATE employees SET id = id WHERE id = :id"
            should_pause = self.info.get("pause") and ((first_writer == "login" and is_guard) or (first_writer == "offboarding" and is_revoke_lock))
            result = await super().execute(statement, *args, **kwargs)
            if should_pause:
                locked.set()
                await release.wait()
            return result

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'session-order.sqlite'}", connect_args={"timeout": 5})
    sessions = async_sessionmaker(engine, class_=ControlledSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: Base.metadata.create_all(conn, tables=[Employees.__table__, EmployeeAuthSession.__table__]))
    async with sessions() as db:
        db.add(Employees(id=801, user_id="isolated-order", name="Isolated Order", role="sales", status="active", password="synthetic-password-hash"))
        await db.commit()
        authenticated = await EmpAuthService(db).get_employee_by_id(801)

    async def login(*, pause=False):
        async with sessions(info={"pause": pause}) as db:
            if not pause:
                second_started.set()
            return await create_employee_session(db, authenticated)

    async def offboard(*, pause=False):
        async with sessions(info={"pause": pause}) as db:
            if not pause:
                second_started.set()
            await EmployeesService(db).update(801, {"status": "disabled"})

    first = asyncio.create_task(login(pause=True) if first_writer == "login" else offboard(pause=True))
    second = None
    try:
        await asyncio.wait_for(locked.wait(), 5)
        second = asyncio.create_task(offboard() if first_writer == "login" else login())
        await asyncio.wait_for(second_started.wait(), 5)
        await asyncio.sleep(0.05)
        assert not second.done(), "The second writer must wait for the employee transaction"
        release.set()
        first_result = await asyncio.wait_for(first, 5)
        if first_writer == "login":
            await asyncio.wait_for(second, 5)
            async with sessions() as db:
                issued = await db.get(EmployeeAuthSession, first_result)
                assert issued is not None and issued.revoked_at is not None
        else:
            with pytest.raises(HTTPException) as denied:
                await asyncio.wait_for(second, 5)
            assert denied.value.status_code == 401
            async with sessions() as db:
                assert not (await db.scalars(select(EmployeeAuthSession))).all()
        async with sessions() as db:
            await EmployeesService(db).update(801, {"status": "active"})
            if first_writer == "login":
                current_employee = await EmpAuthService(db).get_employee_by_id(801)
                with pytest.raises(HTTPException) as denied:
                    await employee_sessions.require_employee_session(db, current_employee, {"sid": first_result, "token_type": "employee_access"})
                assert denied.value.status_code == 401
    finally:
        release.set()
        await asyncio.gather(first, *([second] if second is not None else []), return_exceptions=True)
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["disabled", "inactive", "resigned", "terminated"])
async def test_offboarding_permanently_revokes_sessions_even_after_reactivation(session_auth, status):
    client, _ = session_auth
    target = await sign_in(client, 301)
    admin = await sign_in(client, 303)
    cookie = await issue_refresh(client, target)
    response = await client.put("/api/v1/entities/employees/301", headers=headers(admin), json={"status": status})
    assert response.status_code == 200, response.text
    await check_access(client, target, 401)
    response = await client.put("/api/v1/entities/employees/301", headers=headers(admin), json={"status": "active"})
    assert response.status_code == 200, response.text
    await check_access(client, target, 401)
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, cookie)
    assert (await client.post("/api/v1/emp-auth/refresh")).status_code == 401
    await check_access(client, await sign_in(client, 301), 200)


@pytest.mark.asyncio
async def test_batch_disabling_revokes_each_account_and_reactivation_does_not_restore_sessions(session_auth):
    client, _ = session_auth
    sales_a = await sign_in(client, 301)
    sales_b = await sign_in(client, 302)
    admin = await sign_in(client, 303)
    response = await client.put("/api/v1/entities/employees/batch", headers=headers(admin), json={
        "items": [{"id": employee_id, "updates": {"status": "disabled"}} for employee_id in (301, 302)],
    })
    assert response.status_code == 200, response.text
    response = await client.put("/api/v1/entities/employees/batch", headers=headers(admin), json={
        "items": [{"id": employee_id, "updates": {"status": "active"}} for employee_id in (301, 302)],
    })
    assert response.status_code == 200, response.text
    await check_access(client, sales_a, 401)
    await check_access(client, sales_b, 401)
    await check_access(client, admin, 200)


@pytest.mark.asyncio
async def test_batch_disabling_and_revocations_roll_back_together_on_failure(session_auth, monkeypatch):
    client, sessions = session_auth
    sales_a = await sign_in(client, 301)
    sales_b = await sign_in(client, 302)
    admin = await sign_in(client, 303)
    original_revoke = employee_sessions.revoke_employee_sessions

    async def fail_second_revocation(db, employee_id, session_id=None):
        if employee_id == 302:
            raise RuntimeError("fixture batch failure")
        await original_revoke(db, employee_id, session_id)

    monkeypatch.setattr(employee_sessions, "revoke_employee_sessions", fail_second_revocation)
    response = await client.put("/api/v1/entities/employees/batch", headers=headers(admin), json={
        "items": [{"id": employee_id, "updates": {"status": "disabled"}} for employee_id in (301, 302)],
    })
    assert response.status_code == 500
    await check_access(client, sales_a, 200)
    await check_access(client, sales_b, 200)
    async with sessions() as db:
        assert (await db.get(Employees, 301)).status == "active"
        assert (await db.get(Employees, 302)).status == "probation"
        assert not any(row.revoked_at for row in (await db.scalars(select(EmployeeAuthSession))).all())


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [False, True])
async def test_delete_revokes_sessions_before_employee_id_can_be_reused(session_auth, batch):
    client, sessions = session_auth
    old_token = await sign_in(client, 301)
    admin = await sign_in(client, 303)
    if batch:
        response = await client.request("DELETE", "/api/v1/entities/employees/batch", headers=headers(admin), json={"ids": [301]})
    else:
        response = await client.delete("/api/v1/entities/employees/301", headers=headers(admin))
    assert response.status_code == 200, response.text
    async with sessions() as db:
        assert await db.get(Employees, 301) is None
        session = await db.get(EmployeeAuthSession, decode_access_token(old_token)["sid"])
        assert session.revoked_at is not None
        db.add(Employees(id=301, user_id="replacement-fixture", name="Replacement", email="sales-301@example.test", role="sales", status="active", password=hash_password(PASSWORD)))
        await db.commit()
    await check_access(client, old_token, 401)
    await check_access(client, await sign_in(client), 200)


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [False, True])
async def test_partner_delete_deactivation_revokes_sessions_and_preserves_partner_record(session_auth, batch):
    client, sessions = session_auth
    async with sessions() as db:
        db.add(Employees(id=304, user_id="partner-fixture", name="Partner Fixture", email="sales-304@example.test", role="sales_partner", status="active", password=hash_password(PASSWORD)))
        db.add(SalesPartner(id=604, employee_id=304, partner_code="TEST-PARTNER-304", name="Partner Fixture", partner_type="partner", status="active", joined_at=date(2026, 1, 1)))
        await db.commit()
    partner_token = await sign_in(client, 304)
    admin = await sign_in(client, 303)
    if batch:
        response = await client.request("DELETE", "/api/v1/entities/employees/batch", headers=headers(admin), json={"ids": [304]})
    else:
        response = await client.delete("/api/v1/entities/employees/304", headers=headers(admin))
    assert response.status_code == 200, response.text
    async with sessions() as db:
        assert (await db.get(Employees, 304)).status == "disabled"
        assert await db.get(SalesPartner, 604) is not None
        assert (await db.get(EmployeeAuthSession, decode_access_token(partner_token)["sid"])).revoked_at is not None
    response = await client.put("/api/v1/entities/employees/304", headers=headers(admin), json={"status": "active"})
    assert response.status_code == 200, response.text
    await check_access(client, partner_token, 401)


@pytest.mark.asyncio
async def test_batch_delete_and_revocations_roll_back_together_on_failure(session_auth, monkeypatch):
    client, sessions = session_auth
    sales_a = await sign_in(client, 301)
    sales_b = await sign_in(client, 302)
    admin = await sign_in(client, 303)
    original_revoke = employee_sessions.revoke_employee_sessions

    async def fail_second_revocation(db, employee_id, session_id=None):
        if employee_id == 302:
            raise RuntimeError("fixture delete failure")
        await original_revoke(db, employee_id, session_id)

    monkeypatch.setattr(employee_sessions, "revoke_employee_sessions", fail_second_revocation)
    response = await client.request("DELETE", "/api/v1/entities/employees/batch", headers=headers(admin), json={"ids": [301, 302]})
    assert response.status_code == 500
    await check_access(client, sales_a, 200)
    await check_access(client, sales_b, 200)
    async with sessions() as db:
        assert await db.get(Employees, 301) is not None
        assert await db.get(Employees, 302) is not None
        assert not any(row.revoked_at for row in (await db.scalars(select(EmployeeAuthSession))).all())


@pytest.mark.asyncio
async def test_malformed_signed_identity_is_401_and_logout_still_clears_cookie(session_auth):
    client, _ = session_auth
    token = await sign_in(client)
    await issue_refresh(client, token)
    malformed = create_access_token({"emp_id": "not-an-integer", "sid": decode_access_token(token)["sid"], "role": "sales"})
    assert (await client.get("/api/v1/sales-leads/stats", headers=headers(malformed))).status_code == 401
    response = await client.post("/api/v1/emp-auth/logout", headers=headers(malformed))
    assert response.status_code == 200
    assert not client.cookies.get(COOKIE_NAME)


@pytest.mark.asyncio
async def test_refresh_token_cannot_be_used_as_access_even_if_signing_keys_are_misconfigured(session_auth, monkeypatch):
    client, _ = session_auth
    monkeypatch.setattr(emp_auth, "SECRET_KEY", security_tokens.REFRESH_TOKEN_SECRET)
    token = await sign_in(client)
    refresh_cookie = await issue_refresh(client, token)
    await check_access(client, refresh_cookie, 401)
    assert (await client.get("/api/v1/sales-leads/stats", headers=headers(refresh_cookie))).status_code == 401
    assert (await client.post("/api/v1/emp-auth/refresh")).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("same_employee", [False, True])
async def test_refresh_cannot_switch_to_a_cookie_from_another_account_or_session(session_auth, same_employee):
    client, _ = session_auth
    current_bearer = await sign_in(client, 301)
    stale_cookie_session = await sign_in(client, 301 if same_employee else 302)
    await issue_refresh(client, stale_cookie_session)
    response = await client.post("/api/v1/emp-auth/refresh", headers=headers(current_bearer))
    assert response.status_code == 401
    assert response.json()["detail"] == "Employee session identity mismatch"
    await check_access(client, current_bearer, 200)
    await check_access(client, stale_cookie_session, 200)


@pytest.mark.asyncio
async def test_refresh_allows_expired_matching_bearer_identity_and_cookie_only_cold_start(session_auth):
    client, _ = session_auth
    current = await sign_in(client)
    await issue_refresh(client, current)
    expired = create_access_token({"emp_id": 301, "role": "sales", "sid": decode_access_token(current)["sid"]}, expires_delta=timedelta(seconds=-1))
    await check_access(client, expired, 401)
    response = await client.post("/api/v1/emp-auth/refresh", headers=headers(expired))
    assert response.status_code == 200
    await check_access(client, response.json()["access_token"], 200)
    assert (await client.post("/api/v1/emp-auth/refresh")).status_code == 200
    assert (await client.post("/api/v1/emp-auth/refresh", headers={"Authorization": "Bearer invalid-signature"})).status_code == 401


def test_configured_refresh_signing_key_must_differ_from_access_signing_key(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "fixture-strong-jwt-secret-01234567890123456789")
    monkeypatch.setenv("REFRESH_TOKEN_SECRET", "fixture-strong-jwt-secret-01234567890123456789")
    with pytest.raises(RuntimeError, match="must differ"):
        security_tokens._resolve_refresh_token_secret()


@pytest.mark.asyncio
async def test_login_normalizes_current_and_legacy_email_case_and_whitespace(session_auth):
    client, sessions = session_auth
    async with sessions() as db:
        await db.execute(update(Employees).where(Employees.id == 301).values(email="  SALES-301@EXAMPLE.TEST  "))
        await db.commit()
    response = await client.post("/api/v1/emp-auth/login", json={"email": " Sales-301@Example.Test ", "password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["employee"]["id"] == 301


@pytest.mark.asyncio
async def test_ambiguous_legacy_email_accounts_never_select_first_identity(session_auth):
    client, sessions = session_auth
    async with sessions() as db:
        await db.execute(update(Employees).where(Employees.id == 302).values(email=" SALES-301@EXAMPLE.TEST "))
        await db.commit()
    response = await client.post("/api/v1/emp-auth/login", json={"email": "sales-301@example.test", "password": PASSWORD})
    assert response.status_code == 401
    assert response.json()["detail"] == "邮箱或密码错误"
    async with sessions() as db:
        assert not (await db.scalars(select(EmployeeAuthSession))).all()


@pytest.mark.asyncio
async def test_employee_create_and_edit_standardize_email_and_reject_existing_identity(session_auth):
    client, sessions = session_auth
    admin = await sign_in(client, 303)
    response = await client.post("/api/v1/entities/employees", headers=headers(admin), json={
        "name": "New Sales", "role": "sales", "status": "active", "email": "  NEW-SALES@EXAMPLE.TEST  ",
    })
    assert response.status_code == 201, response.text
    assert response.json()["email"] == "new-sales@example.test"
    created_id = response.json()["id"]
    response = await client.post("/api/v1/entities/employees", headers=headers(admin), json={
        "name": "Must Not Be Created", "role": "sales", "email": " SALES-301@EXAMPLE.TEST ",
    })
    assert response.status_code == 409
    response = await client.put(f"/api/v1/entities/employees/{created_id}", headers=headers(admin), json={"email": " CHANGED-SALES@EXAMPLE.TEST "})
    assert response.status_code == 200
    assert response.json()["email"] == "changed-sales@example.test"
    response = await client.put(f"/api/v1/entities/employees/{created_id}", headers=headers(admin), json={"email": " SALES-301@EXAMPLE.TEST ", "status": "disabled"})
    assert response.status_code == 409
    async with sessions() as db:
        employee = await db.get(Employees, created_id)
        assert employee.email == "changed-sales@example.test"
        assert employee.status == "active"
        assert len((await db.scalars(select(Employees))).all()) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict_with_existing", [False, True])
async def test_batch_create_duplicate_emails_fails_atomically(session_auth, conflict_with_existing):
    client, sessions = session_auth
    admin = await sign_in(client, 303)
    other_email = " SALES-301@EXAMPLE.TEST " if conflict_with_existing else " NEW-BATCH@EXAMPLE.TEST "
    response = await client.post("/api/v1/entities/employees/batch", headers=headers(admin), json={"items": [
        {"name": "Must Not Be Partially Created", "role": "sales", "email": "new-batch@example.test"},
        {"name": "Conflicting Identity", "role": "sales", "email": other_email},
    ]})
    assert response.status_code == 409
    async with sessions() as db:
        assert len((await db.scalars(select(Employees))).all()) == 3


@pytest.mark.asyncio
async def test_batch_email_edits_check_final_unique_identity_before_any_status_changes(session_auth):
    client, sessions = session_auth
    sales_a = await sign_in(client, 301)
    sales_b = await sign_in(client, 302)
    admin = await sign_in(client, 303)
    response = await client.put("/api/v1/entities/employees/batch", headers=headers(admin), json={"items": [
        {"id": 301, "updates": {"email": " Same-Identity@Example.Test ", "status": "disabled"}},
        {"id": 302, "updates": {"email": "same-identity@example.test", "status": "disabled"}},
    ]})
    assert response.status_code == 409
    await check_access(client, sales_a, 200)
    await check_access(client, sales_b, 200)
    async with sessions() as db:
        assert (await db.get(Employees, 301)).email == "sales-301@example.test"
        assert (await db.get(Employees, 302)).email == "sales-302@example.test"
    response = await client.put("/api/v1/entities/employees/batch", headers=headers(admin), json={"items": [
        {"id": 301, "updates": {"email": " NEW-301@EXAMPLE.TEST "}},
        {"id": 302, "updates": {"email": " NEW-302@EXAMPLE.TEST "}},
    ]})
    assert response.status_code == 200, response.text
    assert {row["email"] for row in response.json()} == {"new-301@example.test", "new-302@example.test"}


async def run_identity_requests(fixture, admin, first_request, second_request):
    client, _, locked, release, waiter_started = fixture
    first_method, first_path, first_payload = first_request
    second_method, second_path, second_payload = second_request
    first = asyncio.create_task(client.request(first_method, first_path, json=first_payload,
        headers={**headers(admin), "X-Test-Identity-Order": "first"}))
    second = None
    try:
        await asyncio.wait_for(locked.wait(), 5)
        second = asyncio.create_task(client.request(second_method, second_path, json=second_payload,
            headers={**headers(admin), "X-Test-Identity-Order": "second"}))
        await asyncio.wait_for(waiter_started.wait(), 5)
        await asyncio.sleep(0.05)
        assert not second.done(), "The identity lock must hold through commit/rollback"
        release.set()
        return await asyncio.wait_for(first, 5), await asyncio.wait_for(second, 5)
    finally:
        release.set()
        await asyncio.gather(first, *([second] if second is not None else []), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("first_kind,second_kind", [
    ("create", "create"), ("create", "update"), ("update", "create"), ("update", "update"),
    ("batch_create", "create"), ("create", "batch_create"),
    ("batch_update", "create"), ("update", "batch_update"),
])
async def test_employee_email_identity_serializes_real_file_requests(file_identity_auth, first_kind, second_kind):
    client, sessions, *_ = file_identity_auth
    admin = await sign_in(client, 303)
    sales_tokens = [await sign_in(client, employee_id) for employee_id in (301, 302)]
    async with sessions() as db:
        owner = await db.get(Employees, 303)
        owner_before = (owner.email, owner.name, owner.password, owner.role, owner.status, owner.updated_at, owner.notes)

    prefix = "/api/v1/entities/employees"
    def request(kind, first):
        email = "  SHARED-IDENTITY@EXAMPLE.TEST  " if first else "shared-identity@example.test"
        if kind == "create":
            return "POST", prefix, {"name": "Identity Winner" if first else "Rejected Create", "role": "sales", "email": email}
        if kind == "update":
            return "PUT", prefix + ("/301" if first or first_kind == "create" else "/302"), {
                "email": email, **({} if first else {"status": "disabled", "notes": "must not persist"}),
            }
        if kind == "batch_create":
            return "POST", prefix + "/batch", {"items": [
                {"name": "First Batch Other" if first else "Rejected Batch Other", "role": "sales",
                    "email": "first-other@example.test" if first else "second-unused@example.test"},
                {"name": "First Batch Shared" if first else "Rejected Batch Shared", "role": "sales", "email": email},
            ]}
        if first:
            return "PUT", prefix + "/batch", {"items": [
                {"id": 301, "updates": {"email": email}},
                {"id": 302, "updates": {"email": "first-other@example.test"}},
            ]}
        return "PUT", prefix + "/batch", {"items": [
            {"id": 302, "updates": {"email": email, "status": "disabled"}},
            {"id": 303, "updates": {"notes": "must not persist"}},
        ]}

    first, second = await run_identity_requests(file_identity_auth, admin, request(first_kind, True), request(second_kind, False))
    assert first.status_code == (201 if "create" in first_kind else 200), first.text
    assert second.status_code == 409, second.text
    async with sessions() as db:
        rows = (await db.scalars(select(Employees))).all()
        emails = [str(row.email).strip().lower() for row in rows if row.email]
        assert len(emails) == len(set(emails))
        assert emails.count("shared-identity@example.test") == 1
        assert "second-unused@example.test" not in emails
        assert not any(row.name.startswith("Rejected") for row in rows)
        owner = await db.get(Employees, 303)
        assert (owner.email, owner.name, owner.password, owner.role, owner.status, owner.updated_at, owner.notes) == owner_before
        for employee_id in (301, 302):
            assert (await db.get(Employees, employee_id)).status == "active"
    for token in [admin, *sales_tokens]:
        await check_access(client, token, 200)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["batch_create", "batch_update"])
async def test_employee_identity_failed_batch_rolls_back_and_releases_lock(file_identity_auth, monkeypatch, kind):
    from services.employees import EmployeesService

    client, sessions, *_ = file_identity_auth
    admin = await sign_in(client, 303)
    sales = await sign_in(client, 301)
    prefix = "/api/v1/entities/employees"
    if kind == "batch_create":
        original = EmployeesService.create
        async def fail_second(self, data, **kwargs):
            if data.get("name") == "Trigger Failure":
                raise RuntimeError("synthetic employee create failure")
            return await original(self, data, **kwargs)
        monkeypatch.setattr(EmployeesService, "create", fail_second)
        first = "POST", prefix + "/batch", {"items": [
            {"name": "Must Roll Back", "role": "sales", "email": "rollback-identity@example.test"},
            {"name": "Trigger Failure", "role": "sales", "email": "second-rollback@example.test"},
        ]}
    else:
        original = EmployeesService.update
        async def fail_second(self, employee_id, data, **kwargs):
            if employee_id == 302:
                raise RuntimeError("synthetic employee update failure")
            return await original(self, employee_id, data, **kwargs)
        monkeypatch.setattr(EmployeesService, "update", fail_second)
        first = "PUT", prefix + "/batch", {"items": [
            {"id": 301, "updates": {"email": "rollback-identity@example.test", "status": "disabled"}},
            {"id": 302, "updates": {"email": "second-rollback@example.test"}},
        ]}
    second = "POST", prefix, {"name": "After Rollback", "role": "sales", "email": "rollback-identity@example.test"}
    failed, accepted = await run_identity_requests(file_identity_auth, admin, first, second)
    assert failed.status_code == 500, failed.text
    assert accepted.status_code == 201, accepted.text
    async with sessions() as db:
        rows = (await db.scalars(select(Employees))).all()
        assert len(rows) == 4
        assert not any(row.name == "Must Roll Back" for row in rows)
        assert (await db.get(Employees, 301)).email == "sales-301@example.test"
        assert (await db.get(Employees, 301)).status == "active"
        assert (await db.get(Employees, 302)).email == "sales-302@example.test"
        assert not any(row.email == "second-rollback@example.test" for row in rows)
    await check_access(client, sales, 200)
    await check_access(client, admin, 200)


@pytest.mark.asyncio
async def test_employee_identity_preflight_refreshes_cached_target_after_lock(file_identity_auth):
    _, sessions, *_ = file_identity_auth
    async with sessions() as cached_db:
        cached = await cached_db.get(Employees, 301)
        assert cached.status == "active"
        async with sessions() as other_db:
            await other_db.execute(update(Employees).where(Employees.id == 301).values(status="disabled", email="fresh@example.test"))
            await other_db.commit()
        await employee_routes._lock_employee_identity_mutation(cached_db)
        targets = await employee_routes._load_employee_targets(cached_db, [301])
        assert targets[301] is cached
        assert cached.status == "disabled" and cached.email == "fresh@example.test"
        await cached_db.rollback()


@pytest.mark.asyncio
async def test_sqlite_employee_identity_lock_works_with_empty_table_without_changing_rows(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'empty-identity.sqlite'}")
    sessions = async_sessionmaker(engine)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: Base.metadata.create_all(conn, tables=[Employees.__table__]))
        async with sessions() as db:
            await employee_routes._lock_employee_identity_mutation(db)
            assert not (await db.scalars(select(Employees))).all()
            await db.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("dialect", ["postgresql", "unsupported"])
async def test_employee_identity_lock_is_transaction_owned_or_fails_closed(dialect):
    from types import SimpleNamespace

    class Probe:
        def __init__(self):
            self.calls = []
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name=dialect))
        async def execute(self, statement, parameters):
            self.calls.append((str(statement), parameters))
        async def commit(self):
            raise AssertionError("identity helper must not commit")
        async def rollback(self):
            raise AssertionError("identity helper must not release caller transaction")

    db = Probe()
    if dialect == "postgresql":
        await employee_routes._lock_employee_identity_mutation(db)
        assert db.calls == [("SELECT pg_advisory_xact_lock(:namespace, :identity)", {"namespace": 0x543234, "identity": 1})]
    else:
        with pytest.raises(HTTPException) as denied:
            await employee_routes._lock_employee_identity_mutation(db)
        assert denied.value.status_code == 503
        assert not db.calls


def test_production_cannot_disable_session_checks_or_secure_refresh_cookies(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENFORCE_EMPLOYEE_SESSIONS", "false")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    assert session_enforcement_enabled() is True
    assert _secure_cookie_enabled() is True
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert session_enforcement_enabled() is True
    assert _secure_cookie_enabled() is True


def test_session_migration_is_additive_idempotent_and_preserves_business_records(tmp_path):
    migration_path = Path(__file__).parents[1] / "alembic/versions/ab6d8e2f0411_employee_auth_sessions.py"
    spec = importlib.util.spec_from_file_location("session_migration_fixture", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'isolated-migration.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE employees (id INTEGER PRIMARY KEY, password TEXT)"))
        connection.execute(text("CREATE TABLE payments (id INTEGER PRIMARY KEY, amount TEXT)"))
        connection.execute(text("INSERT INTO employees VALUES (1, 'unchanged-fixture-hash')"))
        connection.execute(text("INSERT INTO payments VALUES (1, '263.94')"))
        before_employees = list(connection.execute(text("SELECT * FROM employees")))
        before_payments = list(connection.execute(text("SELECT * FROM payments")))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
        assert list(connection.execute(text("SELECT * FROM employees"))) == before_employees
        assert list(connection.execute(text("SELECT * FROM payments"))) == before_payments
        assert "employee_auth_sessions" in inspect(connection).get_table_names()
        assert connection.execute(text("SELECT COUNT(*) FROM employee_auth_sessions")).scalar_one() == 0
    engine.dispose()
