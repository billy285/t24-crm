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
async def test_automatic_risk_reminder_never_changes_project_status(workflow_context):
    client, sessions = workflow_context
    async with sessions() as session:
        session.add(CustomerEngagement(
            id=401,
            customer_id=11,
            business_line_id=1,
            product_id=1,
            engagement_code="ENG-RISK-401",
            package_name="待上线套餐",
            status="pending_setup",
            currency="USD",
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        ))
        await session.commit()

    response = await client.get(
        "/api/v1/management-decisions/classification-review",
        headers=auth_headers("admin", 1),
    )
    assert response.status_code == 200
    payload = response.json()
    reminder = next(row for row in payload["anomalies"] if row["code"] == "automatic_project_risk_reminder")
    assert reminder["category"] == "risk"
    assert "待开通" in reminder["message"]
    assert payload["summary"]["risk_reminder_count"] == 1

    async with sessions() as session:
        engagement = (await session.execute(
            select(CustomerEngagement).where(CustomerEngagement.id == 401)
        )).scalar_one()
    assert engagement.status == "pending_setup"


@pytest.mark.asyncio
async def test_customer_create_with_projects_is_atomic_and_admin_can_read_projects(workflow_context):
    client, sessions = workflow_context
    payload = {
        "customer": {
            "customer_code": "C-NEW",
            "business_name": "New Multi Service Customer",
            "contact_name": "Owner",
            "phone": "555-9000",
            "industry": "restaurant",
            "status": "closed",
        },
        "projects": [{
            "business_line_code": "managed_service",
            "product_code": "managed_service_legacy",
            "product_name": "代运营服务",
            "package_name": "代运营基础套餐",
            "status": "active_paid",
            "billing_cycle": "monthly",
            "collection_method": "bank_transfer",
            "currency": "USD",
            "paid_started_at": "2026-08-01T00:00:00Z",
        }],
    }
    created = await client.post(
        "/api/v1/entities/customers/with-projects",
        headers=auth_headers("admin", 33),
        json=payload,
    )
    assert created.status_code == 201, created.text
    customer_id = created.json()["id"]

    projects = await client.get(
        f"/api/v1/entities/customers/{customer_id}/projects",
        headers=auth_headers("admin", 33),
    )
    assert projects.status_code == 200
    assert projects.json()["items"][0]["package_name"] == "代运营基础套餐"

    async with sessions() as session:
        engagement = (await session.execute(
            select(CustomerEngagement).where(CustomerEngagement.customer_id == customer_id)
        )).scalar_one()
        decision = (await session.execute(
            select(ClassificationReviewDecision).where(ClassificationReviewDecision.customer_id == customer_id)
        )).scalar_one()
    assert engagement.package_name == "代运营基础套餐"
    assert decision.decision == "confirmed"

    updated = await client.put(
        f"/api/v1/entities/customers/{customer_id}/with-projects",
        headers=auth_headers("admin", 33),
        json={
            "customer": {"business_name": "Atomic Customer"},
            "projects": [{
                **payload["projects"][0],
                "engagement_id": engagement.id,
                "status": "stopped",
                "stopped_at": "2026-08-03T00:00:00Z",
                "stop_reason_code": "customer_choice",
            }],
        },
    )
    assert updated.status_code == 200, updated.text
    async with sessions() as session:
        status_events = (await session.execute(
            select(EngagementLifecycleEvent)
            .where(EngagementLifecycleEvent.engagement_id == engagement.id)
            .order_by(EngagementLifecycleEvent.id.asc())
        )).scalars().all()
    assert [event.event_type for event in status_events] == ["classification_confirmed", "status_changed"]
    assert "active_paid -> stopped" in status_events[-1].note

    invalid_payload = {
        **payload,
        "customer": {**payload["customer"], "customer_code": "C-BAD", "business_name": "Should Roll Back"},
        "projects": [{**payload["projects"][0], "paid_started_at": None}],
    }
    invalid = await client.post(
        "/api/v1/entities/customers/with-projects",
        headers=auth_headers("admin", 33),
        json=invalid_payload,
    )
    assert invalid.status_code == 400
    async with sessions() as session:
        rolled_back = (await session.execute(
            select(Customers).where(Customers.customer_code == "C-BAD")
        )).scalar_one_or_none()
    assert rolled_back is None


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
