from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.services.emp_auth import create_access_token
from core.database import Base, get_db
from models.customers import Customers
from models.payments import Payments
from services.customer_lifecycle import _kaplan_meier_median_months


def auth_headers(role: str = "admin", employee_id: int = 1) -> dict[str, str]:
    token = create_access_token({
        "emp_id": employee_id,
        "email": f"{employee_id}@test.local",
        "role": role,
        "name": role,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def lifecycle_context():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add_all([
            Customers(
                id=11,
                customer_code="C-0011",
                business_name="The Q",
                contact_name="Owner",
                phone="555-0011",
                status="closed",
                created_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
            ),
            Payments(
                id=101,
                customer_id=11,
                customer_name="The Q",
                income_type="ads_fee",
                amount_due=3000,
                amount_paid=3000,
                currency="USD",
                payment_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
                user_id="1",
            ),
            Payments(
                id=102,
                customer_id=11,
                customer_name="The Q",
                income_type="management_fee",
                amount_due=198,
                amount_paid=198,
                currency="USD",
                payment_date=datetime(2026, 2, 10, tzinfo=timezone.utc),
                user_id="1",
            ),
        ])
        await session.commit()

    async def override_db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, sessions
    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_first_positive_payment_starts_lifecycle_and_package_dates_do_not_matter(lifecycle_context):
    client, _ = lifecycle_context
    overview = await client.get(
        "/api/v1/customer-lifecycle/overview?start_date=2026-01-01&as_of=2026-08-02",
        headers=auth_headers("finance", 2),
    )
    assert overview.status_code == 200
    payload = overview.json()
    assert payload["summary"]["new_customers"] == 1
    assert payload["summary"]["current_active"] == 1
    assert payload["summary"]["retention_3m"] == 100.0
    assert payload["summary"]["retention_6m"] == 100.0
    row = payload["customers"][0]
    assert row["first_payment_id"] == 101
    assert row["started_at"].startswith("2026-01-10")


@pytest.mark.asyncio
async def test_stop_requires_admin_reason_and_reactivation_uses_new_payment(lifecycle_context):
    client, sessions = lifecycle_context
    finance_denied = await client.post(
        "/api/v1/customer-lifecycle/customers/11/actions",
        headers=auth_headers("finance", 2),
        json={"action": "stop", "effective_date": "2026-05-01", "reason_code": "price"},
    )
    assert finance_denied.status_code == 403

    missing_reason = await client.post(
        "/api/v1/customer-lifecycle/customers/11/actions",
        headers=auth_headers(),
        json={"action": "stop", "effective_date": "2026-05-01"},
    )
    assert missing_reason.status_code == 400

    stopped = await client.post(
        "/api/v1/customer-lifecycle/customers/11/actions",
        headers=auth_headers(),
        json={"action": "stop", "effective_date": "2026-05-01", "reason_code": "price", "note": "预算调整"},
    )
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"
    assert stopped.json()["stop_reason"] == "price"

    no_payment = await client.post(
        "/api/v1/customer-lifecycle/customers/11/actions",
        headers=auth_headers(),
        json={"action": "reactivate", "effective_date": "2026-06-01"},
    )
    assert no_payment.status_code == 400

    async with sessions() as session:
        session.add(Payments(
            id=103,
            customer_id=11,
            customer_name="The Q",
            income_type="management_fee",
            amount_due=198,
            amount_paid=198,
            currency="USD",
            payment_date=datetime(2026, 6, 3, tzinfo=timezone.utc),
            user_id="1",
        ))
        await session.commit()

    reactivated = await client.post(
        "/api/v1/customer-lifecycle/customers/11/actions",
        headers=auth_headers(),
        json={"action": "reactivate", "effective_date": "2026-06-03"},
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["cycle_number"] == 2
    assert reactivated.json()["first_payment_id"] == 103
    assert reactivated.json()["started_at"].startswith("2026-06-03")

    detail = await client.get(
        "/api/v1/customer-lifecycle/customers/11",
        headers=auth_headers("finance", 2),
    )
    assert detail.status_code == 200
    assert [cycle["status"] for cycle in detail.json()["cycles"]] == ["active", "stopped"]
    assert {event["event_type"] for event in detail.json()["events"]} >= {"started", "stop", "reactivate"}


@pytest.mark.asyncio
async def test_manual_start_correction_is_not_overwritten_by_earlier_payment(lifecycle_context):
    client, sessions = lifecycle_context
    corrected = await client.post(
        "/api/v1/customer-lifecycle/customers/11/actions",
        headers=auth_headers(),
        json={"action": "adjust_start", "effective_date": "2026-01-15", "note": "排除重复测试记账"},
    )
    assert corrected.status_code == 200
    assert corrected.json()["start_locked"] is True
    assert corrected.json()["started_at"].startswith("2026-01-15")

    async with sessions() as session:
        session.add(Payments(
            id=100,
            customer_id=11,
            customer_name="The Q",
            amount_due=1,
            amount_paid=1,
            currency="USD",
            payment_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            user_id="1",
        ))
        await session.commit()

    backfill = await client.post("/api/v1/customer-lifecycle/backfill", headers=auth_headers())
    assert backfill.status_code == 200
    detail = await client.get("/api/v1/customer-lifecycle/customers/11", headers=auth_headers())
    assert detail.json()["cycles"][0]["started_at"].startswith("2026-01-15")


def test_tenure_median_removes_earlier_censored_customers_from_risk_set():
    as_of = datetime(2026, 4, 1, tzinfo=timezone.utc)
    cycles = [
        SimpleNamespace(started_at=datetime(2026, 3, 1, tzinfo=timezone.utc), ended_at=None),
        SimpleNamespace(started_at=datetime(2026, 1, 1, tzinfo=timezone.utc), ended_at=datetime(2026, 3, 2, tzinfo=timezone.utc)),
        SimpleNamespace(started_at=datetime(2026, 1, 1, tzinfo=timezone.utc), ended_at=None),
    ]
    assert _kaplan_meier_median_months(cycles, as_of) == 2.0
