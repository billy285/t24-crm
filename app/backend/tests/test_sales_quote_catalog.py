"""Verified-user catalog contract; isolated SQLite fixtures, no lifespan or production IO."""
import json
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI, Header
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Register the existing model set without starting the production application.
import backend.main  # noqa: F401
from core.database import Base, get_db
from dependencies.auth import get_current_user
from models.employees import Employees
from models.management_decisions import BusinessLine, ProductCatalog, ProductPlan
from models.sales_deal_controls import SalesHandoffChecklists, SalesQuoteRequests
from models.sales_leads import SalesLeads
from routers import sales_deal_controls
from schemas.auth import UserResponse


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = datetime(2026, 10, 10, 16, 1, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


def headers(emp_id=11, role="sales"):
    return {"X-Fixture-Employee": str(emp_id), "X-Fixture-Role": role}


@pytest_asyncio.fixture
async def catalog_app(monkeypatch):
    monkeypatch.setattr(sales_deal_controls, "datetime", FrozenDateTime)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add_all([
            Employees(id=10, user_id="manager-fixture", name="Manager A", role="sales_manager", status="active"),
            Employees(id=11, user_id="sales-a-fixture", name="Sales A", role="sales", status="active", supervisor="Manager A"),
            Employees(id=12, user_id="sales-b-fixture", name="Sales B", role="sales", status="active", supervisor="Manager B"),
            BusinessLine(id=1, code="public-service", name="在售业务", is_active=True),
            BusinessLine(id=2, code="inactive-line", name="停用业务", is_active=False),
            BusinessLine(id=3, code="private-line", name="尚未在售业务", is_active=True),
        ])
        products = [
            ProductCatalog(id=1, business_line_id=1, code="public-product", name="在售产品", billing_kind="recurring", default_currency="USD", is_active=True),
            ProductCatalog(id=2, business_line_id=3, code="private-product", name="仅草稿产品", billing_kind="recurring", is_active=True),
            ProductCatalog(id=3, business_line_id=2, code="inactive-line-product", name="停用业务产品", billing_kind="recurring", is_active=True),
            ProductCatalog(id=4, business_line_id=1, code="inactive-product", name="停用产品", billing_kind="recurring", is_active=False),
            ProductCatalog(id=5, business_line_id=1, code="future-product", name="未来产品", billing_kind="recurring", is_active=True, effective_from=date(2026, 10, 12)),
            ProductCatalog(id=6, business_line_id=1, code="expired-product", name="过期产品", billing_kind="recurring", is_active=True, effective_to=date(2026, 10, 10)),
        ]
        db.add_all(products)
        await db.flush()
        def plan(i, **overrides):
            fields = dict(id=i, product_id=1, code=f"plan-{i}", name=f"版本-{i}", pricing_status="published", standard_price=398, default_currency="USD", default_billing_cycle="quarterly", platform_limit=3, scope_type="platforms", is_active=True, entitlements_json='["内部字段不应透出"]')
            fields.update(overrides)
            return ProductPlan(**fields)
        db.add_all([
            plan(1, name="公开套餐", effective_from=date(2026, 10, 11), effective_to=date(2026, 10, 11)),
            plan(2, pricing_status="draft", product_id=2), plan(3, pricing_status="retired"),
            plan(4, is_active=False), plan(5, effective_from=date(2026, 10, 12)),
            plan(6, effective_to=date(2026, 10, 10)), plan(7, standard_price=None),
            plan(8, standard_price=-1), plan(9, standard_price=float("inf")),
            plan(10, product_id=3), plan(11, product_id=4), plan(12, product_id=5), plan(13, product_id=6),
            SalesLeads(id=101, business_name="Sales A merchant", phone="+12125550111", assigned_sales_id=11, status="interested"),
            SalesLeads(id=102, business_name="Sales B merchant", phone="+12125550112", assigned_sales_id=12, status="interested"),
        ])
        await db.flush()
        db.add_all([
            SalesQuoteRequests(id=1, lead_id=101, submitted_by_id=11, package_name="旧已批报价", list_amount=99, discount_amount=11, final_amount=88, billing_mode="manual", billing_cycle="one_time", currency="USD", status="approved"),
            SalesHandoffChecklists(id=1, lead_id=101, quote_id=1, payment_status="paid", amount_received=88, finance_payment_confirmed=True, payment_reference="local-fixture-proof"),
        ])
        await db.commit()
    api = FastAPI()
    api.include_router(sales_deal_controls.router)
    async def verified_user(x_fixture_employee: str = Header("11"), x_fixture_role: str = Header("sales")):
        return UserResponse(id=x_fixture_employee, email=f"{x_fixture_employee}@example.test", role=x_fixture_role, name={"10":"Manager A","11":"Sales A","12":"Sales B"}.get(x_fixture_employee,"Fixture"))
    async def fixture_db():
        async with sessions() as db:
            yield db
    api.dependency_overrides[get_current_user] = verified_user
    api.dependency_overrides[get_db] = fixture_db
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://fixture") as client:
        yield client, sessions
    await engine.dispose()


@pytest.mark.asyncio
async def test_only_published_active_finite_current_prices_with_inclusive_beijing_dates(catalog_app):
    client, _ = catalog_app
    response = await client.get("/api/v1/sales-deal-controls/catalog", headers=headers())
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"business_lines", "products", "plans"}
    assert data["business_lines"] == [{"id":1,"code":"public-service","name":"在售业务"}]
    assert data["products"] == [{"id":1,"business_line_id":1,"name":"在售产品","default_currency":"USD"}]
    assert data["plans"] == [{"id":1,"product_id":1,"name":"公开套餐","standard_price":398.0,"default_currency":"USD","default_billing_cycle":"quarterly","platform_limit":3,"scope_type":"platforms"}]
    assert "内部字段" not in response.text
    for private in ("entitlements", "created_at", "updated_at", "pricing_status", "effective_from", "payment", "commission"):
        assert private not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["operations", "finance", "sales_partner", "viewer"])
async def test_catalog_does_not_grant_other_roles_sales_access(catalog_app, role):
    client, _ = catalog_app
    assert (await client.get("/api/v1/sales-deal-controls/catalog", headers=headers(role=role))).status_code == 403


@pytest.mark.asyncio
async def test_multiple_sales_share_public_catalog_but_never_read_or_write_others_leads(catalog_app):
    client, _ = catalog_app
    a = await client.get("/api/v1/sales-deal-controls/catalog", headers=headers(11))
    b = await client.get("/api/v1/sales-deal-controls/catalog", headers=headers(12))
    assert a.json() == b.json()
    assert (await client.get("/api/v1/sales-deal-controls/101/readiness", headers=headers(11))).status_code == 200
    assert (await client.get("/api/v1/sales-deal-controls/101/readiness", headers=headers(12))).status_code == 404
    payload = dict(business_line_id=1, product_id=1, product_plan_id=1, package_name="公开套餐", list_amount=398, discount_amount=10, selected_platforms=["Google", "Instagram"], billing_mode="subscription", billing_cycle="quarterly", currency="USD")
    assert (await client.post("/api/v1/sales-deal-controls/101/quotes", headers=headers(12), json=payload)).status_code == 404
    response = await client.post("/api/v1/sales-deal-controls/101/quotes", headers=headers(11), json=payload)
    assert response.status_code == 201
    assert response.json()["final_amount"] == 388
    assert response.json()["product_plan_id"] == 1
    assert response.json()["billing_cycle"] == "quarterly"
    assert (await client.post("/api/v1/sales-deal-controls/101/handoff/finance-confirmation", headers=headers(11), json={"payment_status":"paid","amount_received":398})).status_code == 403


@pytest.mark.asyncio
async def test_catalog_reads_leave_all_tables_and_existing_finance_confirmation_unchanged(catalog_app):
    client, sessions = catalog_app
    async def snapshot():
        async with sessions() as db:
            names = (await db.execute(text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))).scalars().all()
            return {name: [list(row) for row in (await db.execute(text('SELECT * FROM "'+name.replace('"','""')+'" ORDER BY rowid')))] for name in names}
    before = json.dumps(await snapshot(), sort_keys=True, default=str)
    for emp_id, role in [(11,"sales"),(12,"sales"),(10,"sales_manager"),(1,"admin")]:
        assert (await client.get("/api/v1/sales-deal-controls/catalog", headers=headers(emp_id,role))).status_code == 200
    assert json.dumps(await snapshot(), sort_keys=True, default=str) == before
