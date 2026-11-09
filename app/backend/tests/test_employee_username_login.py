"""Username/email auth regressions use synthetic accounts and an isolated DB."""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.main import app
from core.database import Base, db_manager, get_db
from models.employee_auth_sessions import EmployeeAuthSession
from models.employees import Employees
from models.ringcentral_connections import RingCentralConnections
from routers import emp_auth as login_routes
from services.emp_auth import decode_access_token, hash_password
from services.login_rate_limit import LoginRateLimiter

PASSWORD = "Synthetic-login-only-2026!"
PASSWORD_HASH = hash_password(PASSWORD)
API = "/api/v1/emp-auth/login"


@pytest_asyncio.fixture
async def login_api(tmp_path, monkeypatch):
    monkeypatch.setenv("ENFORCE_EMPLOYEE_STATUS", "true")
    monkeypatch.setenv("ENFORCE_EMPLOYEE_SESSIONS", "true")
    limiter = LoginRateLimiter()
    monkeypatch.setattr(login_routes, "login_rate_limiter", limiter)
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "username-login.sqlite"))
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=[Employees.__table__, EmployeeAuthSession.__table__, RingCentralConnections.__table__])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add_all([
            Employees(id=901, user_id="synthetic-leo", name="Synthetic Leo", login_username="Leo", email=None,
                      role="sales", status="active", password=PASSWORD_HASH),
            Employees(id=902, user_id="synthetic-owner", name="Synthetic Owner", login_username="Owner",
                      email="owner@login.test", role="super_admin", status="active", password=PASSWORD_HASH),
            Employees(id=903, user_id="synthetic-disabled", name="Synthetic Disabled", login_username="Disabled",
                      email="disabled@login.test", role="sales", status="disabled", password=PASSWORD_HASH),
            Employees(id=904, user_id="synthetic-probation", name="Synthetic Probation", login_username="Trainee",
                      email="trainee@login.test", role="sales", status="probation", password=PASSWORD_HASH),
            Employees(id=905, user_id="synthetic-same", name="Synthetic Same", login_username="same@login.test",
                      email="same@login.test", role="sales", status="active", password=PASSWORD_HASH),
        ])
        await db.commit()

    async def override_db():
        async with sessions() as db:
            yield db

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(db_manager, "async_session_maker", sessions)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
            yield client, sessions, limiter
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"email": "Leo"},  # Historical client field now accepts its advertised username.
    {"email": "  lEO  "},
    {"username": "Leo"},
    {"email": " leo ", "username": "LEO"},
])
async def test_username_without_email_issues_real_session_and_keeps_password(login_api, payload):
    client, sessions, _ = login_api
    result = await client.post(API, json={**payload, "password": PASSWORD})
    assert result.status_code == 200, result.text
    assert result.json()["employee"] == {
        "id": 901, "name": "Synthetic Leo", "role": "sales", "email": None, "phone": None, "status": "active",
    }
    token = result.json()["token"]
    claims = decode_access_token(token)
    assert claims["emp_id"] == 901 and claims["sid"] and claims["email"] is None
    me = await client.get("/api/v1/emp-auth/me", headers={"Authorization": "Bearer " + token})
    assert me.status_code == 200 and me.json()["id"] == 901, me.text
    business = await client.get("/api/ringcentral/team-status", headers={"Authorization": "Bearer " + token})
    assert business.status_code == 200, business.text
    assert [item["employee_id"] for item in business.json()["items"]] == [901]
    refresh = await client.post("/api/v1/emp-auth/set_refresh", json={"remember_me": True},
                                headers={"Authorization": "Bearer " + token})
    assert refresh.status_code == 200, refresh.text
    refreshed = await client.post("/api/v1/emp-auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    assert decode_access_token(refreshed.json()["access_token"])["emp_id"] == 901
    async with sessions() as db:
        employee = await db.get(Employees, 901)
        session = await db.get(EmployeeAuthSession, claims["sid"])
        assert employee.password == PASSWORD_HASH and session.employee_id == 901
    assert PASSWORD not in result.text and PASSWORD_HASH not in result.text


@pytest.mark.asyncio
@pytest.mark.parametrize("identity,employee_id", [
    (" OWNER@LOGIN.TEST ", 902), ("Owner", 902), ("same@login.test", 905), (" Trainee ", 904),
])
async def test_email_compatibility_and_single_employee_same_alias(login_api, identity, employee_id):
    client, _, _ = login_api
    result = await client.post(API, json={"email": identity, "password": PASSWORD})
    assert result.status_code == 200, result.text
    assert result.json()["employee"]["id"] == employee_id


@pytest.mark.asyncio
@pytest.mark.parametrize("collision", [
    {"login_username": "  lEO "},
    {"email": " LEO "},
])
async def test_cross_employee_ambiguity_fails_even_with_one_matching_password(login_api, collision):
    client, sessions, _ = login_api
    async with sessions() as db:
        db.add(Employees(id=906, user_id="synthetic-collision", name="Private Other Account", role="sales",
                         status="active", password=hash_password("Different-synthetic-password!"), **collision))
        await db.commit()
    result = await client.post(API, json={"email": "Leo", "password": PASSWORD})
    assert result.status_code == 401 and result.json()["detail"] == "账号或密码错误", result.text
    assert "Private Other Account" not in result.text
    async with sessions() as db:
        assert (await db.execute(select(EmployeeAuthSession))).scalars().all() == []


@pytest.mark.asyncio
async def test_username_wrong_password_unknown_account_and_disabled_remain_denied(login_api):
    client, sessions, _ = login_api
    wrong = await client.post(API, json={"username": "Leo", "password": "Wrong-synthetic-password!"})
    missing = await client.post(API, json={"username": "missing", "password": PASSWORD})
    disabled = await client.post(API, json={"username": "Disabled", "password": PASSWORD})
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json() == missing.json() == {"detail": "账号或密码错误"}
    assert disabled.status_code == 403 and disabled.json()["detail"] == "账号已被停用，请联系管理员"
    async with sessions() as db:
        assert (await db.execute(select(EmployeeAuthSession))).scalars().all() == []
        assert (await db.get(Employees, 901)).password == PASSWORD_HASH


@pytest.mark.asyncio
async def test_username_variants_do_not_bypass_existing_rate_limit(login_api):
    client, _, limiter = login_api
    limiter.max_failures = 2
    wrong = {"password": "Wrong-synthetic-password!"}
    first = await client.post(API, json={"username": "Leo", **wrong})
    second = await client.post(API, json={"email": "  LEO  ", **wrong})
    blocked = await client.post(API, json={"username": "Leo", "password": PASSWORD})
    assert first.status_code == 401 and second.status_code == blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("identities", [
    {"email": "owner@login.test", "username": "Leo"}, {"email": " ", "username": " "}, {},
])
async def test_bad_identifier_parameters_do_not_echo_credentials(login_api, identities):
    client, sessions, _ = login_api
    result = await client.post(API, json={**identities, "password": PASSWORD})
    assert result.status_code == 400, result.text
    assert set(result.json()) == {"detail"}
    assert PASSWORD not in result.text and "input" not in result.text
    async with sessions() as db:
        assert (await db.execute(select(EmployeeAuthSession))).scalars().all() == []


@pytest.mark.asyncio
async def test_username_without_email_also_works_in_non_enforced_dev_auth(login_api, monkeypatch):
    client, _, _ = login_api
    result = await client.post(API, json={"username": "Leo", "password": PASSWORD})
    assert result.status_code == 200, result.text
    monkeypatch.setenv("ENFORCE_EMPLOYEE_STATUS", "false")
    monkeypatch.setenv("ENFORCE_EMPLOYEE_SESSIONS", "false")
    business = await client.get("/api/ringcentral/team-status", headers={"Authorization": "Bearer " + result.json()["token"]})
    assert business.status_code == 200, business.text
    assert [item["employee_id"] for item in business.json()["items"]] == [901]
