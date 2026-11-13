"""Project identity at conversion; synthetic SQLite, no providers or real money."""
import importlib
import pkgutil
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import models as models_package
from core.database import Base, get_db
from dependencies.auth import get_current_user
from models.customer_lifecycles import CustomerLifecycleCycle
from models.customers import Customers
from models.deals import Deals
from models.employees import Employees
from models.management_decisions import BusinessLine, CustomerEngagement, ProductCatalog, ProductPlan
from models.opportunities import Opportunities
from models.payments import Payments
from models.subscriptions import Subscriptions
from models.tasks import Tasks
from routers import opportunities as opportunities_router
from schemas.auth import UserResponse
from services.commissions import _resolve_payment_scope
from services.deal_payment_sync import sync_payment_from_deal


for module_info in pkgutil.iter_modules(models_package.__path__, models_package.__name__ + "."):
    importlib.import_module(module_info.name)


@pytest_asyncio.fixture
async def project_context():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add_all([
            Employees(id=1, user_id="1", name="Synthetic Owner", role="super_admin", status="active"),
            Employees(id=2, user_id="2", name="Synthetic Operations", role="operations", status="active"),
            Employees(id=3, user_id="3", name="Synthetic Sales", role="sales", status="active"),
            Employees(id=6, user_id="6", name="Synthetic Finance", role="finance", status="active"),
            Customers(id=11, customer_code="SYN-EXISTING", business_name="Synthetic Existing",
                      contact_name="Synthetic Contact", phone="+12125550111", status="closed"),
            Customers(id=12, customer_code="SYN-NEW", business_name="Synthetic New",
                      contact_name="Synthetic Contact", phone="+12125550112", status="following"),
            BusinessLine(id=1, code="managed_service", name="Synthetic Managed", is_recurring=True, is_active=True),
            BusinessLine(id=2, code="beauty_os", name="Synthetic Software", is_recurring=True, is_active=True),
            BusinessLine(id=3, code="one_time_project", name="Synthetic Website", is_recurring=False, is_active=True),
            ProductCatalog(id=1, business_line_id=1, code="synthetic-managed", name="Synthetic Managed",
                           billing_kind="recurring", default_currency="USD", is_active=True),
            ProductCatalog(id=2, business_line_id=2, code="synthetic-software", name="Synthetic Software",
                           billing_kind="recurring", default_currency="USD", is_active=True),
            ProductCatalog(id=3, business_line_id=3, code="synthetic-website", name="Synthetic Website",
                           billing_kind="one_time", default_currency="USD", is_active=True),
            ProductPlan(id=1, product_id=1, code="synthetic-managed-v1", name="Synthetic Managed Plan",
                        default_billing_cycle="monthly", scope_type="generic", pricing_status="published", is_active=True),
            ProductPlan(id=2, product_id=2, code="synthetic-software-v1", name="Existing Software Plan",
                        default_billing_cycle="monthly", scope_type="generic", pricing_status="published", is_active=True),
            ProductPlan(id=3, product_id=3, code="synthetic-website-v1", name="Synthetic Website Plan",
                        default_billing_cycle="one_time", scope_type="generic", pricing_status="published", is_active=True),
            CustomerEngagement(id=30, customer_id=11, business_line_id=2, product_id=2, product_plan_id=2,
                               engagement_code="SYN-OLD", package_name="Existing Software Plan", status="active_paid",
                               owner_employee_id=2, sales_employee_id=3, billing_cycle="monthly", currency="USD"),
            Deals(id=41, customer_id=11, engagement_id=30, business_line_id=2, product_id=2, product_plan_id=2,
                  product_type="beauty_os", package_name="Existing Software Plan", deal_amount=99,
                  is_paid=True, is_handed_over=True, is_transferred_ops=True),
            Subscriptions(id=61, customer_id=11, deal_id=41, engagement_id=30, business_line_id=2, product_id=2,
                          product_plan_id=2, package_name="Existing Software Plan", package_price=99,
                          billing_cycle="monthly", status="active", auto_renew=False),
            Payments(id=71, customer_id=11, source_deal_id=41, engagement_id=30, business_line_id=2, product_id=2,
                     product_name="Existing Software Plan", amount_due=99, amount_paid=99, user_id="1"),
        ])
        await db.commit()

    app = FastAPI()
    app.include_router(opportunities_router.router)
    identity = {"user": UserResponse(id="1", role="super_admin", name="Synthetic Owner", email="owner@example.invalid")}

    async def override_db():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://synthetic.test") as client:
        yield client, sessions, identity
    await engine.dispose()


async def seed_opportunity(sessions, *, customer_id=11, one_time=False):
    product_id = 3 if one_time else 1
    async with sessions() as db:
        row = Opportunities(customer_id=customer_id, customer_name="Synthetic Customer",
                            business_line_id=product_id, product_id=product_id, product_plan_id=product_id,
                            opportunity_code=f"SYN-OPP-{customer_id}-{product_id}", title="Synthetic Additional Service",
                            stage="payment_pending", status="open", estimated_amount=321,
                            currency="USD", owner_employee_id=3, owner_name="Synthetic Sales",
                            selected_platforms="[]", service_scope_json='{"synthetic":"agreed scope"}',
                            next_follow_up_at=datetime(2030, 1, 1, tzinfo=timezone.utc))
        db.add(row)
        await db.commit()
        return row.id


@pytest.mark.asyncio
@pytest.mark.parametrize("customer_id", [11, 12])
@pytest.mark.parametrize("one_time", [False, True])
async def test_conversion_persists_direct_project_identity_without_financial_activation(project_context, customer_id, one_time):
    client, sessions, _identity = project_context
    opportunity_id = await seed_opportunity(sessions, customer_id=customer_id, one_time=one_time)
    response = await client.post(f"/api/v1/opportunities/{opportunity_id}/convert", json={})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["subscription_id"] is None
    assert result["lifecycle_started"] is False
    async with sessions() as db:
        opportunity = await db.get(Opportunities, opportunity_id)
        deal = await db.get(Deals, result["deal_id"])
        project = await db.get(CustomerEngagement, result["engagement_id"])
        assert deal.engagement_id == project.id
        assert deal.business_line_id == project.business_line_id == (3 if one_time else 1)
        assert deal.product_id == project.product_id == (3 if one_time else 1)
        assert deal.product_plan_id == project.product_plan_id == (3 if one_time else 1)
        assert deal.opportunity_id == opportunity.id
        assert deal.customer_id == project.customer_id == customer_id
        assert opportunity.converted_deal_id == deal.id
        assert opportunity.converted_engagement_id == project.id
        assert deal.deal_amount == 321
        assert deal.is_paid is False
        assert deal.is_handed_over is False
        assert deal.is_transferred_ops is False
        assert project.status == "pending_setup"
        assert project.paid_started_at is None
        assert deal.service_start_date is None and deal.service_end_date is None
        assert (await db.scalar(select(func.count(Payments.id)))) == 1
        assert (await db.scalar(select(func.count(Subscriptions.id)))) == 1
        assert (await db.scalar(select(func.count(CustomerLifecycleCycle.id)))) == 0
        assert (await db.get(Customers, customer_id)).status == ("closed" if customer_id == 11 else "following")
        old_project = await db.get(CustomerEngagement, 30)
        old_deal = await db.get(Deals, 41)
        assert (old_project.status, old_project.product_id) == ("active_paid", 2)
        assert (old_deal.engagement_id, old_deal.deal_amount, old_deal.is_paid) == (30, 99, True)
        assert (await db.get(Subscriptions, 61)).engagement_id == 30
        assert (await db.get(Payments, 71)).engagement_id == 30


@pytest.mark.asyncio
async def test_repeated_conversion_preserves_one_deal_one_project_and_closed_followup(project_context):
    client, sessions, _identity = project_context
    opportunity_id = await seed_opportunity(sessions)
    first = await client.post(f"/api/v1/opportunities/{opportunity_id}/convert", json={})
    repeated = await client.post(f"/api/v1/opportunities/{opportunity_id}/convert", json={})
    assert first.status_code == repeated.status_code == 200
    assert repeated.json()["idempotent"] is True
    async with sessions() as db:
        assert await db.scalar(select(func.count(Deals.id))) == 2
        assert await db.scalar(select(func.count(CustomerEngagement.id))) == 2
        opportunity = await db.get(Opportunities, opportunity_id)
        assert opportunity.converted_engagement_id == first.json()["engagement_id"]
        task = await db.scalar(select(Tasks).where(Tasks.opportunity_id == opportunity_id))
        assert task.status == "completed"
        assert opportunity.status == "won"


@pytest.mark.asyncio
@pytest.mark.parametrize("employee_id,role", [(3, "sales"), (2, "operations"), (6, "finance")])
async def test_conversion_keeps_existing_owner_only_financial_boundary(project_context, employee_id, role):
    client, sessions, identity = project_context
    opportunity_id = await seed_opportunity(sessions)
    identity["user"] = UserResponse(id=str(employee_id), role=role, name="Synthetic Member", email="member@example.invalid")
    denied = await client.post(f"/api/v1/opportunities/{opportunity_id}/convert", json={})
    assert denied.status_code == 403
    async with sessions() as db:
        assert await db.scalar(select(func.count(Deals.id))) == 1
        assert await db.scalar(select(func.count(CustomerEngagement.id))) == 1
        assert (await db.get(Opportunities, opportunity_id)).status == "open"


@pytest.mark.asyncio
async def test_incomplete_catalog_rejected_without_partial_project_or_deal(project_context):
    client, sessions, _identity = project_context
    opportunity_id = await seed_opportunity(sessions)
    async with sessions() as db:
        opportunity = await db.get(Opportunities, opportunity_id)
        opportunity.product_plan_id = None
        await db.commit()
    rejected = await client.post(f"/api/v1/opportunities/{opportunity_id}/convert", json={})
    assert rejected.status_code == 400
    async with sessions() as db:
        assert await db.scalar(select(func.count(Deals.id))) == 1
        assert await db.scalar(select(func.count(CustomerEngagement.id))) == 1
        assert (await db.get(Opportunities, opportunity_id)).status == "open"


def unscoped_receivable(**changes):
    return Payments(customer_id=11, source_deal_id=41, product_name="Existing Software Plan",
                    amount_due=123, amount_paid=0, currency="USD", user_id="synthetic", **changes)


@pytest.mark.asyncio
@pytest.mark.parametrize("one_time", [False, True])
async def test_unpaid_receivable_from_converted_deal_resolves_exact_project(project_context, one_time):
    client, sessions, _identity = project_context
    opportunity_id = await seed_opportunity(sessions, one_time=one_time)
    response = await client.post(f"/api/v1/opportunities/{opportunity_id}/convert", json={})
    assert response.status_code == 200
    async with sessions() as db:
        deal = await db.get(Deals, response.json()["deal_id"])
        payment = await sync_payment_from_deal(db, deal, commit=False)
        await _resolve_payment_scope(db, payment)
        await db.flush()
        await db.refresh(payment)
        assert payment.engagement_id == deal.engagement_id == response.json()["engagement_id"]
        assert payment.business_line_id == deal.business_line_id == (3 if one_time else 1)
        assert payment.product_id == deal.product_id == (3 if one_time else 1)
        assert payment.amount_paid == 0 and payment.amount_due == payment.outstanding_amount == 321
        assert deal.is_paid is False and deal.is_transferred_ops is False
        assert (await db.get(CustomerEngagement, payment.engagement_id)).status == "pending_setup"


@pytest.mark.asyncio
async def test_explicit_same_customer_source_deal_precedes_old_subscription(project_context):
    _client, sessions, _identity = project_context
    async with sessions() as db:
        # A direct project identity must win over a differently linked legacy
        # subscription. No name, amount or subscription guess replaces it.
        db.add(CustomerEngagement(id=32, customer_id=11, business_line_id=3, product_id=3,
                                  product_plan_id=3, engagement_code="SYN-DIRECT", status="pending_setup"))
        deal = await db.get(Deals, 41)
        deal.engagement_id, deal.business_line_id, deal.product_id, deal.product_plan_id = 32, 3, 3, 3
        await db.flush()
        payment = unscoped_receivable()
        await _resolve_payment_scope(db, payment)
        assert (payment.engagement_id, payment.business_line_id, payment.product_id) == (32, 3, 3)
        assert (payment.amount_due, payment.amount_paid, payment.currency) == (123, 0, "USD")
        assert (await db.get(Subscriptions, 61)).engagement_id == 30


@pytest.mark.asyncio
async def test_foreign_source_deal_cannot_supply_project_or_classification(project_context):
    _client, sessions, _identity = project_context
    async with sessions() as db:
        payment = unscoped_receivable()
        payment.customer_id = 12
        await _resolve_payment_scope(db, payment)
        assert (payment.engagement_id, payment.business_line_id, payment.product_id) == (None, None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign", [False, True])
async def test_missing_or_foreign_explicit_source_project_is_not_guessed_from_subscription(project_context, foreign):
    _client, sessions, _identity = project_context
    async with sessions() as db:
        if foreign:
            db.add(CustomerEngagement(id=32, customer_id=12, business_line_id=2, product_id=2,
                                      product_plan_id=2, engagement_code="SYN-FOREIGN", status="pending_setup"))
        deal = await db.get(Deals, 41)
        deal.engagement_id = 32 if foreign else 9999
        await db.flush()
        payment = unscoped_receivable()
        await _resolve_payment_scope(db, payment)
        assert (payment.engagement_id, payment.business_line_id, payment.product_id) == (None, None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("target,field", [("payment", "business_line_id"), ("payment", "product_id"),
                                         ("deal", "business_line_id"), ("deal", "product_id"), ("deal", "product_plan_id")])
async def test_classification_conflicts_preserve_values_without_project_inheritance(project_context, target, field):
    _client, sessions, _identity = project_context
    async with sessions() as db:
        deal = await db.get(Deals, 41)
        payment = unscoped_receivable()
        setattr(payment if target == "payment" else deal, field, 3)
        await db.flush()
        before = (payment.engagement_id, payment.business_line_id, payment.product_id)
        await _resolve_payment_scope(db, payment)
        assert (payment.engagement_id, payment.business_line_id, payment.product_id) == before
        assert getattr(payment if target == "payment" else deal, field) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("project_id", [30, 9999])
async def test_existing_explicit_payment_project_and_classification_are_never_replaced(project_context, project_id):
    _client, sessions, _identity = project_context
    async with sessions() as db:
        payment = unscoped_receivable(engagement_id=project_id, business_line_id=3, product_id=3)
        await _resolve_payment_scope(db, payment)
        assert (payment.engagement_id, payment.business_line_id, payment.product_id) == (project_id, 3, 3)


@pytest.mark.asyncio
async def test_explicit_foreign_payment_project_cannot_fill_missing_classification(project_context):
    _client, sessions, _identity = project_context
    async with sessions() as db:
        db.add(CustomerEngagement(id=32, customer_id=12, business_line_id=2, product_id=2,
                                  product_plan_id=2, engagement_code="SYN-FOREIGN-PAYMENT", status="pending_setup"))
        await db.flush()
        payment = unscoped_receivable(engagement_id=32)
        await _resolve_payment_scope(db, payment)
        assert (payment.engagement_id, payment.business_line_id, payment.product_id) == (32, None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("source_id", [None, 9999, 41])
async def test_no_explicit_source_project_retains_existing_same_customer_legacy_fallback(project_context, source_id):
    _client, sessions, _identity = project_context
    async with sessions() as db:
        deal = await db.get(Deals, 41)
        deal.engagement_id = None
        await db.flush()
        payment = unscoped_receivable()
        payment.source_deal_id = source_id
        await _resolve_payment_scope(db, payment)
        assert (payment.engagement_id, payment.business_line_id, payment.product_id) == (30, 2, 2)
        assert deal.engagement_id is None
