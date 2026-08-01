import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.services.emp_auth import create_access_token
from core.database import Base, get_db
from models.employees import Employees


def headers(role: str, employee_id: int, name: str) -> dict[str, str]:
    token = create_access_token({"emp_id": employee_id, "email": f"{employee_id}@test.local", "role": role, "name": name})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def payroll_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add(Employees(id=20, user_id="emp20", name="张三", role="ops", status="active", employee_code="T024", department="运营部", hire_date="2026-01-01"))
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
async def test_payroll_role_workflow_and_lock(payroll_client):
    admin = headers("admin", 1, "管理员")
    finance = headers("finance", 2, "财务")
    sales = headers("sales", 3, "销售")

    assert (await payroll_client.get("/api/v1/payroll?month=2026-08", headers=sales)).status_code == 403
    created = await payroll_client.post("/api/v1/payroll/2026-08/items", headers=finance, json={
        "employee_id": 20, "employee_name": "ignored", "payment_method": "bank_card", "payment_account": "6222021234567890",
        "base_salary": 5000, "fixed_performance": 500, "bonus": 200, "absence_deduction": 100,
        "payment_status": "pending",
    })
    assert created.status_code == 200
    assert created.json()["employee_name"] == "张三"
    assert created.json()["payment_account_masked"] == "•••• 7890"
    assert "payment_account" not in created.json()
    assert created.json()["net_amount"] == 5600

    denied_confirm = await payroll_client.post("/api/v1/payroll/2026-08/transition", headers=finance, json={"action": "confirm"})
    assert denied_confirm.status_code == 403
    assert (await payroll_client.post("/api/v1/payroll/2026-08/transition", headers=admin, json={"action": "confirm"})).status_code == 200

    item_id = created.json()["id"]
    paid_item = await payroll_client.put(f"/api/v1/payroll/2026-08/items/{item_id}", headers=finance, json={
        "employee_id": 20, "employee_name": "张三", "payment_method": "bank_card", "base_salary": 5000,
        "fixed_performance": 500, "bonus": 200, "absence_deduction": 100, "payment_status": "paid",
        "payment_date": "2026-08-31", "payment_reference": "BANK-001",
    })
    assert paid_item.status_code == 200
    assert (await payroll_client.post("/api/v1/payroll/2026-08/transition", headers=finance, json={"action": "mark_paid"})).status_code == 200
    locked = await payroll_client.put(f"/api/v1/payroll/2026-08/items/{item_id}", headers=finance, json={"employee_name": "张三"})
    assert locked.status_code == 409
    no_reason = await payroll_client.post("/api/v1/payroll/2026-08/transition", headers=admin, json={"action": "reopen"})
    assert no_reason.status_code == 400
    reopened = await payroll_client.post("/api/v1/payroll/2026-08/transition", headers=admin, json={"action": "reopen", "reason": "银行退回，需要更正账号"})
    assert reopened.status_code == 200
    audit = await payroll_client.get("/api/v1/payroll/2026-08/audit", headers=admin)
    assert {entry["action"] for entry in audit.json()} >= {"item_created", "confirm", "mark_paid", "reopen"}
