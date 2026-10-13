import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.main import app
from backend.services.emp_auth import create_access_token
from core.database import Base, get_db
from models.employees import Employees
from services.employee_sessions import create_employee_session


def _partner_headers(session_id: str) -> dict[str, str]:
    token = create_access_token({
        "emp_id": 9901,
        "email": "partner@example.com",
        "role": "sales_partner",
        "name": "Partner",
        "sid": session_id,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def partner_api(monkeypatch):
    monkeypatch.setenv("ENFORCE_EMPLOYEE_STATUS", "true")
    monkeypatch.setenv("ENFORCE_EMPLOYEE_SESSIONS", "true")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add(Employees(id=9901, user_id="partner-fixture", role="sales_partner", name="Synthetic Partner",
                         status="active", email="partner@example.com", password="synthetic-fingerprint"))
        await db.commit()
        session_id = await create_employee_session(db, {"id": 9901, "password": "synthetic-fingerprint"})

    async def override_db():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, _partner_headers(session_id)
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_sales_partner_api_allowlist_blocks_internal_business_entities(partner_api):
    ac, headers = partner_api
    customers = await ac.get("/api/v1/entities/customers", headers=headers)
    deals = await ac.get("/api/v1/entities/deals", headers=headers)
    finance = await ac.get("/api/v1/entities/payments", headers=headers)
    config = await ac.get("/api/v1/app-config", headers=headers)
    concrete_configs = [
        await ac.get(f"/api/v1/app-config/{key}", headers=headers)
        for key in ("role_permissions", "company_info", "security_config", "notification_config", "payroll_sheets_v1")
    ]

    assert [customers.status_code, deals.status_code, finance.status_code] == [403, 403, 403]
    assert config.status_code == 200
    assert config.json() == {"items": {}}
    assert [response.status_code for response in concrete_configs] == [403, 403, 403, 403, 403]


@pytest.mark.asyncio
async def test_partner_cannot_access_new_management_or_binding_routes(partner_api):
    ac, headers = partner_api
    endpoints = [
        ("GET", "/api/v1/commissions/partner-login-options"),
        ("GET", "/api/v1/commissions/unbound-partners"),
        ("GET", "/api/v1/commissions/payments/1/preview"),
        ("POST", "/api/v1/commissions/attributions/preview"),
        ("POST", "/api/v1/commissions/partners/1/login-account"),
        ("POST", "/api/v1/commissions/entries/1/transition"),
        ("POST", "/api/v1/entities/employees"),
    ]
    for method, path in endpoints:
        response = await ac.request(method, path, headers=headers, json={} if method == "POST" else None)
        assert response.status_code == 403, (path, response.text)
