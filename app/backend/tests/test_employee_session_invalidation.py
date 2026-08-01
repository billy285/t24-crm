import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.routers.emp_auth_tokens import COOKIE_NAME
from backend.services.emp_auth import create_access_token
from backend.services.security_tokens import create_refresh_token
from core.database import Base, get_db
from models.employees import Employees


def auth_headers(employee_id: int, role: str = "admin") -> dict[str, str]:
    token = create_access_token(
        {
            "emp_id": employee_id,
            "email": f"{employee_id}@test.local",
            "role": role,
            "name": f"Employee {employee_id}",
        }
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def employee_auth_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add_all(
            [
                Employees(
                    id=81,
                    user_id="inactive-81",
                    name="Inactive Employee",
                    role="admin",
                    status="inactive",
                    email="81@test.local",
                ),
                Employees(
                    id=82,
                    user_id="active-82",
                    name="Active Employee",
                    role="admin",
                    status="active",
                    email="82@test.local",
                ),
            ]
        )
        await session.commit()

    async def override_db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_inactive_employee_access_token_is_rejected_immediately(employee_auth_client, monkeypatch):
    monkeypatch.setenv("ENFORCE_EMPLOYEE_STATUS", "true")

    inactive = await employee_auth_client.get(
        "/api/v1/entities/customers?limit=1",
        headers=auth_headers(81),
    )
    active = await employee_auth_client.get(
        "/api/v1/entities/customers?limit=1",
        headers=auth_headers(82),
    )

    assert inactive.status_code == 401
    assert inactive.json()["detail"] == "Employee account is inactive"
    assert active.status_code == 200


@pytest.mark.asyncio
async def test_inactive_employee_cannot_refresh_or_create_refresh_cookie(employee_auth_client):
    refresh = create_refresh_token(subject="81")
    employee_auth_client.cookies.set(COOKIE_NAME, refresh)

    refresh_response = await employee_auth_client.post("/api/v1/emp-auth/refresh")
    cookie_response = await employee_auth_client.post(
        "/api/v1/emp-auth/set_refresh",
        headers=auth_headers(81),
        json={"remember_me": True},
    )
    set_password_response = await employee_auth_client.post(
        "/api/v1/emp-auth/set-password",
        headers=auth_headers(81),
        json={"employee_id": 82, "new_password": "new-password"},
    )

    assert refresh_response.status_code == 401
    assert refresh_response.json()["detail"] == "Employee account is inactive"
    assert cookie_response.status_code == 401
    assert cookie_response.json()["detail"] == "Employee account is inactive"
    assert set_password_response.status_code == 401
    assert set_password_response.json()["detail"] == "账号已被停用"
