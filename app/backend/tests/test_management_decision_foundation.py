from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.services.emp_auth import create_access_token
from core.database import Base, get_db
from models.customers import Customers
from models.management_decisions import BusinessLine, CustomerEngagement, ProductCatalog


def auth_headers(role: str, employee_id: int) -> dict[str, str]:
    token = create_access_token({
        "emp_id": employee_id,
        "email": f"{employee_id}@test.local",
        "role": role,
        "name": role,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def management_context():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as session:
        managed = BusinessLine(id=1, code="managed_service", name="代运营", is_recurring=True, is_active=True)
        restaurant = BusinessLine(id=2, code="restaurant_os", name="餐饮 OS", is_recurring=True, is_active=True)
        managed_product = ProductCatalog(
            id=1,
            business_line_id=1,
            code="managed_service_legacy",
            name="代运营历史套餐",
            billing_kind="recurring",
            default_currency="USD",
            is_active=True,
        )
        customer = Customers(
            id=11,
            customer_code="C-0011",
            business_name="The Q",
            contact_name="Owner",
            phone="555-0011",
            industry="restaurant",
            status="closed",
        )
        session.add_all([managed, restaurant, managed_product, customer])
        await session.flush()
        session.add(CustomerEngagement(
            id=1,
            customer_id=11,
            business_line_id=1,
            product_id=1,
            engagement_code="ENG-000001",
            status="active_paid",
            billing_cycle="monthly",
            collection_method="stripe_auto",
            currency="USD",
            paid_started_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
        ))
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
async def test_management_metadata_is_finance_protected_and_read_only(management_context):
    client = management_context
    unauthenticated = await client.get("/api/v1/management-decisions/metadata")
    denied = await client.get(
        "/api/v1/management-decisions/metadata",
        headers=auth_headers("sales", 2),
    )
    allowed = await client.get(
        "/api/v1/management-decisions/metadata",
        headers=auth_headers("finance", 3),
    )

    assert unauthenticated.status_code == 401
    assert denied.status_code == 403
    assert allowed.status_code == 200
    payload = allowed.json()
    assert payload["write_enabled"] is False
    assert payload["phase"] == "review_and_project_management"
    assert {item["code"] for item in payload["business_lines"]} == {
        "managed_service",
        "restaurant_os",
        "beauty_os",
        "one_time_project",
    }


@pytest.mark.asyncio
async def test_business_lines_and_engagements_are_filterable(management_context):
    client = management_context
    headers = auth_headers("admin", 1)

    lines = await client.get("/api/v1/management-decisions/business-lines", headers=headers)
    engagements = await client.get(
        "/api/v1/management-decisions/engagements?business_line=managed_service&status=active_paid",
        headers=headers,
    )
    empty = await client.get(
        "/api/v1/management-decisions/engagements?business_line=restaurant_os",
        headers=headers,
    )

    assert lines.status_code == 200
    assert lines.json()["total"] == 2
    assert engagements.status_code == 200
    assert engagements.json()["total"] == 1
    assert engagements.json()["items"][0]["customer_name"] == "The Q"
    assert engagements.json()["items"][0]["business_line"]["code"] == "managed_service"
    assert engagements.json()["write_enabled"] is True
    assert empty.status_code == 200
    assert empty.json()["items"] == []


@pytest.mark.asyncio
async def test_foundation_exposes_no_write_endpoint(management_context):
    client = management_context
    response = await client.post(
        "/api/v1/management-decisions/engagements",
        headers=auth_headers("admin", 1),
        json={"customer_id": 11},
    )
    assert response.status_code == 405
