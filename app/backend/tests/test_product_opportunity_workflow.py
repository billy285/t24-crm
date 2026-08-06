from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.services.emp_auth import create_access_token
from core.database import Base, get_db
from models.customers import Customers
from models.deals import Deals
from models.management_decisions import BusinessLine, CustomerEngagement, ProductCatalog, ProductPlan
from models.opportunities import Opportunities
from models.payments import Payments
from models.tasks import Tasks


def auth_headers(role: str = "admin", employee_id: int = 1) -> dict[str, str]:
    token = create_access_token({
        "emp_id": employee_id,
        "email": f"{employee_id}@test.local",
        "role": role,
        "name": "Test Admin",
    })
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def opportunity_context():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add_all([
            BusinessLine(id=1, code="managed_service", name="代运营", is_recurring=True, is_active=True),
            ProductCatalog(
                id=1, business_line_id=1, code="managed_service", name="代运营服务",
                billing_kind="recurring", default_currency="USD", is_active=True,
            ),
            Customers(
                id=11, customer_code="C-0011", business_name="The Q", contact_name="Owner",
                phone="555-0011", industry="restaurant", status="closed",
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
async def test_plan_validation_and_opportunity_task_conversion_are_closed_loop(opportunity_context):
    client, sessions = opportunity_context
    headers = auth_headers()
    rejected_plan = await client.post("/api/v1/product-plans/plans", headers=headers, json={
        "product_id": 1,
        "code": "managed_basic_invalid",
        "name": "基础套餐",
        "pricing_status": "published",
        "standard_price": None,
        "default_currency": "USD",
        "default_billing_cycle": "monthly",
        "platform_limit": 2,
        "scope_type": "platforms",
        "entitlements": [],
        "is_active": True,
    })
    assert rejected_plan.status_code == 422

    plan_response = await client.post("/api/v1/product-plans/plans", headers=headers, json={
        "product_id": 1,
        "code": "managed_basic_v1",
        "name": "基础套餐",
        "version_label": "2026 版",
        "pricing_status": "published",
        "standard_price": 198,
        "default_currency": "USD",
        "default_billing_cycle": "monthly",
        "platform_limit": 2,
        "scope_type": "platforms",
        "entitlements": ["月度内容运营"],
        "is_active": True,
    })
    assert plan_response.status_code == 201, plan_response.text
    plan_id = plan_response.json()["id"]
    due_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    opportunity_response = await client.post("/api/v1/opportunities", headers=headers, json={
        "customer_id": 11,
        "business_line_id": 1,
        "product_id": 1,
        "product_plan_id": plan_id,
        "title": "新增 Google 与 Facebook 代运营",
        "stage": "quoted",
        "status": "open",
        "estimated_amount": 198,
        "currency": "USD",
        "selected_platforms": ["google"],
        "next_follow_up_at": due_at,
    })
    assert opportunity_response.status_code == 201, opportunity_response.text
    opportunity_id = opportunity_response.json()["id"]
    task_id = opportunity_response.json()["task_id"]
    assert task_id

    incomplete_conversion = await client.post(
        f"/api/v1/opportunities/{opportunity_id}/convert", headers=headers, json={}
    )
    assert incomplete_conversion.status_code == 400
    assert "2 个实际运营平台" in incomplete_conversion.json()["detail"]

    updated = await client.put(f"/api/v1/opportunities/{opportunity_id}", headers=headers, json={
        "selected_platforms": ["google", "facebook"],
        "next_follow_up_at": due_at,
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["task_id"] == task_id

    follow = await client.post(f"/api/v1/opportunities/{opportunity_id}/follow-ups", headers=headers, json={
        "content": "客户确认两个平台，等待首笔付款",
        "contact_method": "phone",
        "stage": "payment_pending",
        "next_follow_up_at": due_at,
    })
    assert follow.status_code == 201, follow.text
    assert follow.json()["opportunity"]["probability"] == 90

    converted = await client.post(f"/api/v1/opportunities/{opportunity_id}/convert", headers=headers, json={})
    assert converted.status_code == 200, converted.text
    converted_payload = converted.json()
    assert converted_payload["lifecycle_started"] is False
    assert converted_payload["subscription_id"] is None

    repeated = await client.post(f"/api/v1/opportunities/{opportunity_id}/convert", headers=headers, json={})
    assert repeated.status_code == 200
    assert repeated.json()["idempotent"] is True

    async with sessions() as session:
        assert (await session.execute(select(func.count(Payments.id)))).scalar_one() == 0
        assert (await session.execute(select(func.count(Deals.id)))).scalar_one() == 1
        engagement = (await session.execute(select(CustomerEngagement))).scalar_one()
        assert engagement.status == "pending_setup"
        assert engagement.paid_started_at is None
        opportunity = await session.get(Opportunities, opportunity_id)
        task = await session.get(Tasks, task_id)
        assert opportunity.status == "won"
        assert task.status == "completed"
        assert "商机已成交" in task.completion_result


@pytest.mark.asyncio
async def test_non_admin_can_read_catalog_but_cannot_edit(opportunity_context):
    client, _sessions = opportunity_context
    finance_headers = auth_headers("finance", 3)
    listing = await client.get("/api/v1/product-plans", headers=finance_headers)
    denied = await client.post("/api/v1/product-plans/plans", headers=finance_headers, json={
        "product_id": 1,
        "code": "denied_plan",
        "name": "Denied",
        "pricing_status": "draft",
        "scope_type": "generic",
        "entitlements": [],
        "is_active": True,
    })
    assert listing.status_code == 200
    assert denied.status_code == 403
