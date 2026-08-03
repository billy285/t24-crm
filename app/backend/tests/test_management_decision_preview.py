from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.services.emp_auth import create_access_token
from core.database import Base, get_db
from models.customer_lifecycles import CustomerLifecycleCycle
from models.customers import Customers
from models.management_decisions import CustomerEngagement, EngagementLifecycleEvent, EngagementSourceLink
from models.payments import Payments
from models.subscriptions import Subscriptions
from services.management_decision_preview import classify_payment


def auth_headers(role: str, employee_id: int) -> dict[str, str]:
    token = create_access_token({
        "emp_id": employee_id,
        "email": f"{employee_id}@test.local",
        "role": role,
        "name": role,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def preview_context():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    now = datetime(2026, 8, 3, tzinfo=timezone.utc)
    async with sessions() as session:
        session.add_all([
            Customers(
                id=11,
                customer_code="C-0011",
                business_name="The Q",
                contact_name="Owner",
                phone="555-0011",
                industry="restaurant",
                status="closed",
            ),
            Customers(
                id=12,
                customer_code="C-0012",
                business_name="Sophia Spa",
                contact_name="Owner",
                phone="555-0012",
                industry="beauty",
                status="closed",
            ),
            Payments(
                id=101,
                customer_id=11,
                customer_name="The Q",
                income_type="ads_fee",
                product_name="投流充值",
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
                product_name="基础套餐",
                amount_due=198,
                amount_paid=198,
                currency="USD",
                billing_cycle="月付",
                payment_date=datetime(2026, 2, 10, tzinfo=timezone.utc),
                user_id="1",
            ),
            Payments(
                id=103,
                customer_id=11,
                customer_name="The Q",
                income_type="management_ads_mixed",
                product_name="基础套餐、投放套餐",
                amount_due=3198,
                amount_paid=3198,
                management_amount=198,
                ads_recharge_amount=3000,
                currency="USD",
                payment_date=datetime(2026, 3, 10, tzinfo=timezone.utc),
                user_id="1",
            ),
            Payments(
                id=104,
                customer_id=11,
                customer_name="The Q",
                income_type="ordering_fee",
                product_name="T24Menu Restaurant OS",
                amount_due=99,
                amount_paid=99,
                currency="USD",
                payment_date=datetime(2026, 4, 10, tzinfo=timezone.utc),
                user_id="1",
            ),
            Payments(
                id=105,
                customer_id=11,
                customer_name="The Q",
                income_type="website_fee",
                product_name="官网制作",
                amount_due=1200,
                amount_paid=1200,
                currency="USD",
                payment_date=datetime(2026, 5, 10, tzinfo=timezone.utc),
                user_id="1",
            ),
            Payments(
                id=106,
                customer_id=12,
                customer_name="Sophia Spa",
                income_type="management_fee",
                product_name="基础套餐",
                amount_due=198,
                amount_paid=198,
                currency="USD",
                payment_date=datetime(2026, 6, 10, tzinfo=timezone.utc),
                user_id="1",
            ),
            Subscriptions(
                id=201,
                customer_id=11,
                customer_name="The Q",
                package_name="T24Menu Restaurant OS",
                package_price=99,
                billing_cycle="monthly",
                start_date=datetime(2026, 4, 10, tzinfo=timezone.utc),
                status="active",
            ),
            CustomerLifecycleCycle(
                id=301,
                customer_id=11,
                cycle_number=1,
                first_payment_id=101,
                started_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
                status="active",
                start_source="payment",
                start_locked=False,
                created_at=now,
                updated_at=now,
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
async def test_preview_flags_pass_through_lifecycle_and_suggests_service_payment(preview_context):
    client, _ = preview_context
    response = await client.get(
        "/api/v1/management-decisions/classification-preview?customer_id=11",
        headers=auth_headers("finance", 2),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "dry_run"
    assert payload["write_enabled"] is False
    assert payload["start_date"] == "2026-01-01"
    row = payload["items"][0]
    assert row["current_legacy_lifecycle"]["first_payment_id"] == 101
    assert row["lifecycle_candidates"]["managed_service"]["payment_id"] == 102
    assert row["lifecycle_candidates"]["restaurant_os"]["payment_id"] == 104
    assert row["lifecycle_candidates"]["one_time_project"]["payment_id"] == 105
    warning = next(item for item in row["warnings"] if item["code"] == "lifecycle_started_by_pass_through")
    assert warning["context"] == {"current_payment_id": 101, "suggested_payment_id": 102}


@pytest.mark.asyncio
async def test_preview_splits_mixed_payment_and_does_not_infer_beauty_os_from_industry(preview_context):
    client, _ = preview_context
    response = await client.get(
        "/api/v1/management-decisions/classification-preview",
        headers=auth_headers("admin", 1),
    )

    assert response.status_code == 200
    rows = {row["customer_id"]: row for row in response.json()["items"]}
    mixed = next(payment for payment in rows[11]["payments"] if payment["payment_id"] == 103)
    assert [(item["classification"], item["amount"]) for item in mixed["components"]] == [
        ("service_revenue", 198.0),
        ("pass_through_principal", 3000.0),
    ]
    assert mixed["warnings"] == []

    spa = rows[12]
    assert "beauty_os" not in spa["lifecycle_candidates"]
    assert spa["lifecycle_candidates"]["managed_service"]["payment_id"] == 106


@pytest.mark.asyncio
async def test_preview_is_permission_protected_and_has_no_database_writes(preview_context):
    client, sessions = preview_context
    async with sessions() as session:
        before_counts = {
            model.__tablename__: (await session.execute(select(func.count()).select_from(model))).scalar_one()
            for model in (CustomerEngagement, EngagementSourceLink, EngagementLifecycleEvent)
        }
        before_payment = (await session.execute(select(Payments).where(Payments.id == 101))).scalar_one()
        before_payment_snapshot = (
            before_payment.income_type,
            before_payment.amount_paid,
            before_payment.management_amount,
            before_payment.ads_recharge_amount,
        )
        before_cycle = (await session.execute(
            select(CustomerLifecycleCycle).where(CustomerLifecycleCycle.id == 301)
        )).scalar_one()
        before_cycle_snapshot = (before_cycle.first_payment_id, before_cycle.started_at, before_cycle.start_locked)

    unauthenticated = await client.get("/api/v1/management-decisions/classification-preview")
    denied = await client.get(
        "/api/v1/management-decisions/classification-preview",
        headers=auth_headers("sales", 3),
    )
    allowed = await client.get(
        "/api/v1/management-decisions/classification-preview",
        headers=auth_headers("finance", 2),
    )

    assert unauthenticated.status_code == 401
    assert denied.status_code == 403
    assert allowed.status_code == 200

    async with sessions() as session:
        after_counts = {
            model.__tablename__: (await session.execute(select(func.count()).select_from(model))).scalar_one()
            for model in (CustomerEngagement, EngagementSourceLink, EngagementLifecycleEvent)
        }
        after_payment = (await session.execute(select(Payments).where(Payments.id == 101))).scalar_one()
        after_cycle = (await session.execute(
            select(CustomerLifecycleCycle).where(CustomerLifecycleCycle.id == 301)
        )).scalar_one()

    assert after_counts == before_counts == {
        "customer_engagements": 0,
        "engagement_source_links": 0,
        "engagement_lifecycle_events": 0,
    }
    assert (
        after_payment.income_type,
        after_payment.amount_paid,
        after_payment.management_amount,
        after_payment.ads_recharge_amount,
    ) == before_payment_snapshot
    assert (after_cycle.first_payment_id, after_cycle.started_at, after_cycle.start_locked) == before_cycle_snapshot


def test_incomplete_mixed_and_unknown_payments_fail_closed():
    incomplete = classify_payment(Payments(
        id=901,
        customer_id=11,
        income_type="management_ads_mixed",
        product_name="基础套餐、投放套餐",
        amount_due=3198,
        amount_paid=3198,
        management_amount=198,
        ads_recharge_amount=0,
        currency="USD",
        user_id="1",
    ))
    unknown = classify_payment(Payments(
        id=902,
        customer_id=11,
        income_type="other_income",
        product_name="待确认项目",
        amount_due=500,
        amount_paid=500,
        currency=None,
        user_id="1",
    ))

    assert incomplete["components"] == [{
        "classification": "needs_review",
        "business_line": None,
        "product_code": None,
        "amount": 3198.0,
        "basis": "mixed_split_incomplete",
        "lifecycle_eligible": False,
    }]
    assert {item["code"] for item in incomplete["warnings"]} == {"mixed_split_incomplete"}
    assert unknown["lifecycle_eligible"] is False
    assert unknown["components"][0]["classification"] == "needs_review"
    assert {item["code"] for item in unknown["warnings"]} == {"unrecognized_income", "missing_currency"}
