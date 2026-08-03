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
from models.management_decisions import (
    BusinessLine,
    ClassificationReviewDecision,
    CustomerEngagement,
    EngagementLifecycleEvent,
    EngagementSourceLink,
    ProductCatalog,
)
from models.payments import Payments


def auth_headers(role: str, employee_id: int) -> dict[str, str]:
    token = create_access_token({
        "emp_id": employee_id,
        "email": f"{employee_id}@test.local",
        "role": role,
        "name": role,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def workflow_context():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    now = datetime(2026, 8, 3, tzinfo=timezone.utc)
    async with sessions() as session:
        managed = BusinessLine(id=1, code="managed_service", name="代运营", is_recurring=True, is_active=True)
        product = ProductCatalog(
            id=1,
            business_line_id=1,
            code="managed_service_legacy",
            name="代运营历史套餐",
            billing_kind="recurring",
            default_currency="USD",
            is_active=True,
        )
        session.add_all([
            managed,
            product,
            Customers(
                id=11,
                customer_code="C-0011",
                business_name="Ocean Buffet",
                contact_name="Owner",
                phone="555-0011",
                industry="restaurant",
                status="closed",
            ),
            Customers(
                id=12,
                customer_code="C-0012",
                business_name="Other Customer",
                contact_name="Owner",
                phone="555-0012",
                industry="restaurant",
                status="closed",
            ),
            Payments(
                id=101,
                customer_id=11,
                customer_name="Ocean Buffet",
                income_type="ads_fee",
                product_name="投流充值",
                amount_due=2000,
                amount_paid=2000,
                currency="USD",
                payment_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
                user_id="1",
            ),
            Payments(
                id=102,
                customer_id=11,
                customer_name="Ocean Buffet",
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
                id=201,
                customer_id=12,
                customer_name="Other Customer",
                income_type="management_fee",
                product_name="基础套餐",
                amount_due=198,
                amount_paid=198,
                currency="USD",
                payment_date=datetime(2026, 2, 11, tzinfo=timezone.utc),
                user_id="1",
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
async def test_review_queue_is_readable_by_finance_and_writable_only_by_admin(workflow_context):
    client, _ = workflow_context
    finance = await client.get(
        "/api/v1/management-decisions/classification-review",
        headers=auth_headers("finance", 2),
    )
    admin = await client.get(
        "/api/v1/management-decisions/classification-review",
        headers=auth_headers("admin", 1),
    )
    denied = await client.get(
        "/api/v1/management-decisions/classification-review",
        headers=auth_headers("sales", 3),
    )

    assert finance.status_code == 200
    assert finance.json()["write_enabled"] is False
    assert admin.status_code == 200
    assert admin.json()["write_enabled"] is True
    assert denied.status_code == 403
    ocean = next(row for row in admin.json()["items"] if row["customer_id"] == 11)
    assert ocean["review_status"] == "pending"
    assert ocean["customer_lifecycle"]["status"] == "active"
    assert {row["business_line"] for row in ocean["suggestions"]} == {"managed_service"}


@pytest.mark.asyncio
async def test_confirming_project_is_idempotent_and_does_not_change_customer_lifecycle(workflow_context):
    client, sessions = workflow_context
    payload = {
        "decision": "confirmed",
        "note": "确认仍在合作，只建立代运营项目",
        "projects": [{
            "business_line_code": "managed_service",
            "product_code": "managed_service_legacy",
            "product_name": "代运营历史套餐",
            "status": "active_paid",
            "billing_cycle": "monthly",
            "collection_method": "bank_transfer",
            "currency": "USD",
            "paid_started_at": "2026-02-10T00:00:00Z",
            "source_payment_ids": [102],
            "source_subscription_ids": [],
        }],
    }
    first = await client.post(
        "/api/v1/management-decisions/classification-review/customers/11",
        headers=auth_headers("admin", 1),
        json=payload,
    )
    second = await client.post(
        "/api/v1/management-decisions/classification-review/customers/11",
        headers=auth_headers("admin", 1),
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    async with sessions() as session:
        counts = {
            model.__tablename__: (await session.execute(select(func.count()).select_from(model))).scalar_one()
            for model in (CustomerEngagement, EngagementSourceLink, EngagementLifecycleEvent, ClassificationReviewDecision)
        }
        customer = (await session.execute(select(Customers).where(Customers.id == 11))).scalar_one()
        lifecycle = (await session.execute(
            select(CustomerLifecycleCycle).where(CustomerLifecycleCycle.id == 301)
        )).scalar_one()
        engagement = (await session.execute(select(CustomerEngagement))).scalar_one()

    assert counts == {
        "customer_engagements": 1,
        "engagement_source_links": 1,
        "engagement_lifecycle_events": 1,
        "classification_review_decisions": 1,
    }
    assert customer.status == "closed"
    assert lifecycle.status == "active"
    assert lifecycle.first_payment_id == 101
    assert engagement.status == "active_paid"
    assert engagement.paid_started_at.date().isoformat() == "2026-02-10"


@pytest.mark.asyncio
async def test_confirmation_rejects_another_customers_payment(workflow_context):
    client, sessions = workflow_context
    response = await client.post(
        "/api/v1/management-decisions/classification-review/customers/11",
        headers=auth_headers("admin", 1),
        json={
            "decision": "confirmed",
            "projects": [{
                "business_line_code": "managed_service",
                "status": "active_paid",
                "billing_cycle": "monthly",
                "collection_method": "other",
                "currency": "USD",
                "paid_started_at": "2026-02-10T00:00:00Z",
                "source_payment_ids": [201],
            }],
        },
    )
    assert response.status_code == 400
    assert "不属于该客户" in response.json()["detail"]
    async with sessions() as session:
        assert (await session.execute(select(func.count()).select_from(CustomerEngagement))).scalar_one() == 0


@pytest.mark.asyncio
async def test_project_stop_does_not_stop_customer(workflow_context):
    client, sessions = workflow_context
    create = await client.post(
        "/api/v1/management-decisions/classification-review/customers/11",
        headers=auth_headers("admin", 1),
        json={
            "decision": "confirmed",
            "projects": [{
                "business_line_code": "managed_service",
                "status": "active_paid",
                "billing_cycle": "monthly",
                "collection_method": "other",
                "currency": "USD",
                "paid_started_at": "2026-02-10T00:00:00Z",
                "source_payment_ids": [102],
            }],
        },
    )
    project_id = create.json()["projects"][0]["id"]
    stopped = await client.patch(
        f"/api/v1/management-decisions/engagements/{project_id}/status",
        headers=auth_headers("admin", 1),
        json={"status": "stopped", "effective_date": "2026-08-03", "note": "仅停止该项目"},
    )

    assert stopped.status_code == 200
    async with sessions() as session:
        customer = (await session.execute(select(Customers).where(Customers.id == 11))).scalar_one()
        lifecycle = (await session.execute(select(CustomerLifecycleCycle).where(CustomerLifecycleCycle.id == 301))).scalar_one()
        engagement = (await session.execute(select(CustomerEngagement).where(CustomerEngagement.id == project_id))).scalar_one()
    assert customer.status == "closed"
    assert lifecycle.status == "active"
    assert engagement.status == "stopped"
