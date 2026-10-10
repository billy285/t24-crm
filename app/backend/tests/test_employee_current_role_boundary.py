"""Current database roles must control the global sales boundary, not JWT history."""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from core.database import Base, db_manager, get_db
from models.employees import Employees
from services.emp_auth import create_access_token
from services.employee_sessions import create_employee_session, revoke_employee_sessions


@pytest_asyncio.fixture
async def current_role_client(monkeypatch):
    monkeypatch.setenv("ENFORCE_EMPLOYEE_STATUS", "true")
    monkeypatch.setenv("ENFORCE_EMPLOYEE_SESSIONS", "true")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add(Employees(id=901, user_id="boundary-901", name="Fixture Sales", role="admin", status="active", email="fixture@example.test", password="synthetic-credential-fingerprint"))
        await db.commit()
        session_id = await create_employee_session(db, {"id":901,"password":"synthetic-credential-fingerprint"})

    async def override_db():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(db_manager, "async_session_maker", sessions)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, sessions, session_id
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


def headers(session_id, role="admin"):
    return {"Authorization":"Bearer "+create_access_token({"emp_id":901,"role":role,"sid":session_id})}


@pytest.mark.asyncio
async def test_demoted_admin_old_claim_cannot_bypass_sales_boundary(current_role_client):
    client, sessions, session_id = current_role_client
    async with sessions() as db:
        employee = await db.get(Employees,901)
        employee.role = "sales"
        await db.commit()
    response = await client.get("/api/v1/entities/employees/directory",headers=headers(session_id))
    assert response.status_code == 403
    assert response.json()["detail"] == "电话销售账号只能访问电话销售中心"
    allowed = await client.get("/api/v1/sales-leads/stats",headers=headers(session_id))
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_promoted_sales_old_claim_does_not_remain_restricted(current_role_client):
    client, _, session_id = current_role_client
    response = await client.get("/api/v1/entities/employees/directory",headers=headers(session_id,"sales"))
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_revoked_session_is_denied_before_role_based_route_guard(current_role_client):
    client, sessions, session_id = current_role_client
    async with sessions() as db:
        await revoke_employee_sessions(db,901,session_id)
        await db.commit()
    response = await client.get("/api/v1/entities/employees/directory",headers=headers(session_id,"sales"))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_old_header_does_not_prevent_fresh_password_login(current_role_client):
    client, _, session_id = current_role_client
    response = await client.post("/api/v1/emp-auth/login",headers=headers("revoked-or-missing","sales"),json={"email":"missing@example.test","password":"not-a-real-password"})
    assert response.status_code == 401
    assert response.json()["detail"] == "邮箱或密码错误"
