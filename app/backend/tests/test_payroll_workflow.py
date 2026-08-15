import asyncio
from dataclasses import dataclass

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.services.emp_auth import create_access_token
from core.database import Base, get_db
from models.company_expenses import Company_expenses
from models.employees import Employees


def headers(role: str, employee_id: int, name: str) -> dict[str, str]:
    token = create_access_token({"emp_id": employee_id, "email": f"{employee_id}@test.local", "role": role, "name": name})
    return {"Authorization": f"Bearer {token}"}


@dataclass
class PayrollTestContext:
    client: AsyncClient
    sessions: async_sessionmaker[AsyncSession]


@pytest_asyncio.fixture
async def payroll_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add_all([
            Employees(id=20, user_id="emp20", name="张三", role="ops", status="active", employee_code="T024", department="运营部", hire_date="2026-01-01"),
            Employees(id=21, user_id="emp21", name="李四", role="ops", status="active", employee_code="T025", department="运营部", hire_date="2026-02-01"),
        ])
        await session.commit()

    async def override_db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield PayrollTestContext(client=client, sessions=sessions)
    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


async def create_payroll_item(
    client: AsyncClient,
    finance_headers: dict[str, str],
    month: str,
    employee_id: int,
    payment_status: str,
):
    response = await client.post(
        f"/api/v1/payroll/{month}/items",
        headers=finance_headers,
        json={
            "employee_id": employee_id,
            "employee_name": "ignored",
            "payment_method": "bank_card",
            "base_salary": 5000,
            "payment_status": payment_status,
        },
    )
    assert response.status_code == 200
    return response.json()


async def confirm_payroll(client: AsyncClient, admin_headers: dict[str, str], month: str):
    response = await client.post(
        f"/api/v1/payroll/{month}/transition",
        headers=admin_headers,
        json={"action": "confirm"},
    )
    assert response.status_code == 200


async def company_expense_count(context: PayrollTestContext) -> int:
    async with context.sessions() as session:
        return int((await session.execute(select(func.count(Company_expenses.id)))).scalar_one())


@pytest.mark.asyncio
async def test_payroll_role_workflow_and_lock(payroll_client):
    client = payroll_client.client
    admin = headers("admin", 1, "管理员")
    finance = headers("finance", 2, "财务")
    sales = headers("sales", 3, "销售")

    assert (await client.get("/api/v1/payroll?month=2026-08", headers=sales)).status_code == 403
    created = await client.post("/api/v1/payroll/2026-08/items", headers=finance, json={
        "employee_id": 20, "employee_name": "ignored", "payment_method": "bank_card", "payment_account": "6222021234567890",
        "base_salary": 5000, "fixed_performance": 500, "bonus": 200, "absence_deduction": 100,
        "payment_status": "pending",
    })
    assert created.status_code == 200
    assert created.json()["employee_name"] == "张三"
    assert created.json()["payment_account_masked"] == "•••• 7890"
    assert "payment_account" not in created.json()
    assert created.json()["net_amount"] == 5600

    denied_confirm = await client.post("/api/v1/payroll/2026-08/transition", headers=finance, json={"action": "confirm"})
    assert denied_confirm.status_code == 403
    assert (await client.post("/api/v1/payroll/2026-08/transition", headers=admin, json={"action": "confirm"})).status_code == 200

    item_id = created.json()["id"]
    paid_item = await client.put(f"/api/v1/payroll/2026-08/items/{item_id}", headers=finance, json={
        "employee_id": 20, "employee_name": "张三", "payment_method": "bank_card", "base_salary": 5000,
        "fixed_performance": 500, "bonus": 200, "absence_deduction": 100, "payment_status": "paid",
        "payment_date": "2026-08-31", "payment_reference": "BANK-001",
    })
    assert paid_item.status_code == 200
    assert (await client.post("/api/v1/payroll/2026-08/transition", headers=finance, json={"action": "mark_paid"})).status_code == 200
    locked = await client.put(f"/api/v1/payroll/2026-08/items/{item_id}", headers=finance, json={"employee_name": "张三"})
    assert locked.status_code == 409
    no_reason = await client.post("/api/v1/payroll/2026-08/transition", headers=admin, json={"action": "reopen"})
    assert no_reason.status_code == 400
    reopened = await client.post("/api/v1/payroll/2026-08/transition", headers=admin, json={"action": "reopen", "reason": "银行退回，需要更正账号"})
    assert reopened.status_code == 200
    audit = await client.get("/api/v1/payroll/2026-08/audit", headers=admin)
    assert {entry["action"] for entry in audit.json()} >= {"item_created", "confirm", "mark_paid", "reopen"}

    report = await client.get("/api/v1/payroll/reports?year=2026", headers=admin)
    assert report.status_code == 200
    payload = report.json()
    assert payload["independent_accounting"] is True
    assert payload["totals"]["headcount"] == 1
    assert payload["totals"]["gross"] == 5700
    assert payload["totals"]["deductions"] == 100
    assert payload["totals"]["net"] == 5600
    assert payload["totals"]["paid_amount"] == 5600
    assert next(row for row in payload["monthly"] if row["month"] == "2026-08")["net"] == 5600
    assert payload["departments"][0]["department"] == "运营部"
    assert payload["employees"][0]["employee_name"] == "张三"
    assert payload["employees"][0]["latest_payment_status"] == "paid"
    assert (await client.get("/api/v1/payroll/reports?year=2026", headers=sales)).status_code == 403


@pytest.mark.asyncio
async def test_mark_paid_can_confirm_all_pending_once_without_finance_side_effects(payroll_client):
    client = payroll_client.client
    admin = headers("admin", 1, "管理员")
    finance = headers("finance", 2, "财务")
    month = "2026-09"
    payment_date = "2026-09-30"

    await create_payroll_item(client, finance, month, employee_id=20, payment_status="pending")
    await create_payroll_item(client, finance, month, employee_id=21, payment_status="pending")
    await confirm_payroll(client, admin, month)
    expenses_before = await company_expense_count(payroll_client)

    missing_confirmation = await client.post(
        f"/api/v1/payroll/{month}/transition",
        headers=finance,
        json={"action": "mark_paid", "payment_date": payment_date},
    )
    assert missing_confirmation.status_code == 409

    payload = {
        "action": "mark_paid",
        "confirm_all_pending": True,
        "payment_date": payment_date,
    }
    completed = await client.post(f"/api/v1/payroll/{month}/transition", headers=finance, json=payload)
    assert completed.status_code == 200
    assert completed.json()["status"] == "paid"

    sheet = (await client.get(f"/api/v1/payroll?month={month}", headers=admin)).json()
    assert sheet["sheet"]["status"] == "paid"
    assert len(sheet["items"]) == 2
    assert {item["payment_status"] for item in sheet["items"]} == {"paid"}
    assert {item["payment_date"] for item in sheet["items"]} == {payment_date}

    repeated = await client.post(f"/api/v1/payroll/{month}/transition", headers=finance, json=payload)
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "paid"

    audit = await client.get(f"/api/v1/payroll/{month}/audit", headers=admin)
    mark_paid_events = [entry for entry in audit.json() if entry["action"] == "mark_paid"]
    assert len(mark_paid_events) == 1
    assert await company_expense_count(payroll_client) == expenses_before

    report = await client.get("/api/v1/payroll/reports?year=2026", headers=admin)
    assert report.status_code == 200
    assert report.json()["independent_accounting"] is True


@pytest.mark.asyncio
async def test_legacy_all_paid_rows_without_payment_date_can_still_lock(payroll_client):
    client = payroll_client.client
    admin = headers("admin", 1, "管理员")
    finance = headers("finance", 2, "财务")
    month = "2026-11"

    await create_payroll_item(client, finance, month, employee_id=20, payment_status="paid")
    await confirm_payroll(client, admin, month)

    completed = await client.post(
        f"/api/v1/payroll/{month}/transition",
        headers=finance,
        json={"action": "mark_paid"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "paid"


@pytest.mark.asyncio
async def test_concurrent_mark_paid_is_idempotent_and_audited_once(tmp_path):
    database_path = tmp_path / "payroll-concurrency.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        connect_args={"timeout": 30},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add_all([
            Employees(id=20, user_id="emp20", name="张三", role="ops", status="active", employee_code="T024", department="运营部", hire_date="2026-01-01"),
            Employees(id=21, user_id="emp21", name="李四", role="ops", status="active", employee_code="T025", department="运营部", hire_date="2026-02-01"),
        ])
        await session.commit()

    async def override_db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            admin = headers("admin", 1, "管理员")
            finance = headers("finance", 2, "财务")
            month = "2026-12"
            payment_date = "2026-12-31"
            await create_payroll_item(client, finance, month, employee_id=20, payment_status="pending")
            await create_payroll_item(client, finance, month, employee_id=21, payment_status="pending")
            await confirm_payroll(client, admin, month)

            payload = {
                "action": "mark_paid",
                "confirm_all_pending": True,
                "payment_date": payment_date,
            }
            responses = await asyncio.gather(
                client.post(f"/api/v1/payroll/{month}/transition", headers=finance, json=payload),
                client.post(f"/api/v1/payroll/{month}/transition", headers=finance, json=payload),
            )

            assert [response.status_code for response in responses] == [200, 200]
            assert sorted(response.json()["updated_items"] for response in responses) == [0, 2]

            sheet = (await client.get(f"/api/v1/payroll?month={month}", headers=admin)).json()
            assert sheet["sheet"]["status"] == "paid"
            assert {item["payment_status"] for item in sheet["items"]} == {"paid"}
            assert {item["payment_date"] for item in sheet["items"]} == {payment_date}

            audit = (await client.get(f"/api/v1/payroll/{month}/audit", headers=admin)).json()
            assert len([entry for entry in audit if entry["action"] == "mark_paid"]) == 1
            assert len([entry for entry in audit if entry["action"] == "bulk_mark_paid"]) == 2
            async with sessions() as session:
                assert (await session.execute(select(func.count(Company_expenses.id)))).scalar_one() == 0
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.parametrize("blocking_status", ["partial", "failed", "returned", "supplemental"])
@pytest.mark.asyncio
async def test_mark_paid_does_not_override_non_pending_payment_states(payroll_client, blocking_status):
    client = payroll_client.client
    admin = headers("admin", 1, "管理员")
    finance = headers("finance", 2, "财务")
    month = "2026-10"

    await create_payroll_item(client, finance, month, employee_id=20, payment_status=blocking_status)
    await confirm_payroll(client, admin, month)

    response = await client.post(
        f"/api/v1/payroll/{month}/transition",
        headers=finance,
        json={
            "action": "mark_paid",
            "confirm_all_pending": True,
            "payment_date": "2026-10-31",
        },
    )
    assert response.status_code == 409

    sheet = (await client.get(f"/api/v1/payroll?month={month}", headers=admin)).json()
    assert sheet["sheet"]["status"] == "confirmed"
    assert sheet["items"][0]["payment_status"] == blocking_status

    audit = await client.get(f"/api/v1/payroll/{month}/audit", headers=admin)
    assert not [entry for entry in audit.json() if entry["action"] == "mark_paid"]
