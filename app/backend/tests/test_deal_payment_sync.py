from datetime import datetime

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.database import Base
from models.customers import Customers
from models.deals import Deals
from models.finance_profit_closes import MonthlyProfitClose
from models.payments import Payments
from models.subscriptions import Subscriptions
from services.deal_payment_sync import (
    backfill_missing_payments_from_deals,
    sync_payment_from_deal,
)
from services.payment_deal_sync import sync_deal_from_payment


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


async def seed_customer(session, **overrides):
    customer = Customers(
        business_name=overrides.get("business_name", "Golden Dragon"),
        contact_name=overrides.get("contact_name", "Alice"),
        phone=overrides.get("phone", "1234567890"),
        sales_person=overrides.get("sales_person", "Amy"),
        sales_employee_id=overrides.get("sales_employee_id", 7),
        created_at=overrides.get("created_at", datetime(2026, 1, 1, 9, 0, 0)),
        updated_at=overrides.get("updated_at", datetime(2026, 1, 1, 9, 0, 0)),
    )
    session.add(customer)
    await session.flush()
    return customer


async def seed_deal(session, customer: Customers, **overrides):
    deal = Deals(
        customer_id=customer.id,
        customer_name=overrides.get("customer_name", customer.business_name),
        sales_employee_id=overrides.get("sales_employee_id", customer.sales_employee_id),
        sales_name=overrides.get("sales_name", customer.sales_person),
        product_type=overrides.get("product_type", "website"),
        package_name=overrides.get("package_name", "官方网站套餐"),
        billing_cycle=overrides.get("billing_cycle", "monthly"),
        deal_amount=overrides.get("deal_amount", 299.0),
        is_paid=overrides.get("is_paid", True),
        service_start_date=overrides.get("service_start_date", datetime(2026, 1, 1, 0, 0, 0)),
        service_end_date=overrides.get("service_end_date", datetime(2026, 6, 30, 0, 0, 0)),
        needs_group=overrides.get("needs_group", False),
        is_handed_over=overrides.get("is_handed_over", True),
        is_transferred_ops=overrides.get("is_transferred_ops", True),
        notes=overrides.get("notes", "seed deal"),
        deal_date=overrides.get("deal_date", datetime(2026, 1, 3, 10, 0, 0)),
        created_at=overrides.get("created_at", datetime(2026, 1, 3, 10, 0, 0)),
        source_payment_id=overrides.get("source_payment_id"),
    )
    session.add(deal)
    await session.flush()
    return deal


@pytest.mark.asyncio
async def test_backfill_missing_payments_from_deals_creates_linked_income(db_session):
    customer = await seed_customer(db_session, business_name="Sichuan House")
    deal = await seed_deal(
        db_session,
        customer,
        product_type="website",
        package_name="官网托管套餐",
        deal_amount=499.0,
        is_paid=True,
        deal_date=datetime(2026, 2, 1, 12, 0, 0),
    )
    db_session.add(
        Subscriptions(
            customer_id=customer.id,
            customer_name=customer.business_name,
            deal_id=deal.id,
            package_name=deal.package_name,
            package_price=deal.deal_amount,
            billing_cycle=deal.billing_cycle,
            start_date=deal.service_start_date,
            end_date=deal.service_end_date,
            last_payment_date=datetime(2026, 2, 15, 8, 0, 0),
            status="active",
            created_at=datetime(2026, 2, 1, 12, 0, 0),
        )
    )
    await db_session.commit()

    synced_count = await backfill_missing_payments_from_deals(db_session)
    assert synced_count == 1

    payments = (await db_session.execute(select(Payments))).scalars().all()
    assert len(payments) == 1
    payment = payments[0]
    assert payment.source_deal_id == deal.id
    assert payment.customer_id == customer.id
    assert payment.customer_name == "Sichuan House"
    assert payment.income_type == "website_fee"
    assert payment.payment_mode == "manual_collection"
    assert payment.amount_due == 499.0
    assert payment.amount_paid == 499.0
    assert payment.outstanding_amount == 0.0
    assert payment.payment_date == datetime(2026, 2, 1, 12, 0, 0)
    assert payment.expense_month == "2026-02"

    synced_count_again = await backfill_missing_payments_from_deals(db_session)
    assert synced_count_again == 0


@pytest.mark.asyncio
async def test_deal_payment_sync_cannot_write_locked_receipt_or_coverage_month(db_session):
    customer = await seed_customer(db_session, business_name="Locked Coverage")
    deal = await seed_deal(
        db_session,
        customer,
        deal_date=datetime(2026, 8, 5, 12, 0, 0),
        service_start_date=datetime(2026, 7, 1, 0, 0, 0),
        service_end_date=datetime(2026, 8, 1, 0, 0, 0),
    )
    db_session.add(MonthlyProfitClose(
        year_month="2026-07",
        status="locked",
        snapshot_json="{}",
        locked_by="Owner",
        locked_at=datetime(2026, 8, 1, 0, 0, 0),
    ))
    await db_session.commit()

    with pytest.raises(HTTPException) as locked_error:
        await sync_payment_from_deal(db_session, deal)
    assert locked_error.value.status_code == 409
    assert (await db_session.scalars(select(Payments))).all() == []

    # Startup backfill skips the historical locked candidate instead of making
    # the application unavailable or silently changing the closed ledger.
    assert await backfill_missing_payments_from_deals(db_session) == 0
    assert (await db_session.scalars(select(Payments))).all() == []


@pytest.mark.asyncio
async def test_sync_payment_from_deal_updates_existing_payment_without_duplicates(db_session):
    customer = await seed_customer(db_session, business_name="Beauty Space")
    deal = await seed_deal(
        db_session,
        customer,
        product_type="social_media",
        package_name="新媒体代运营",
        deal_amount=300.0,
        is_paid=False,
    )
    payment = Payments(
        source_deal_id=deal.id,
        customer_id=customer.id,
        customer_name=customer.business_name,
        income_type="other_income",
        product_name="旧套餐",
        amount_due=100.0,
        amount_paid=50.0,
        currency="USD",
        payment_date=datetime(2026, 1, 10, 10, 0, 0),
        payment_mode="manual_collection",
        payment_method="cash",
        billing_cycle="monthly",
        coverage_start=deal.service_start_date,
        coverage_end=deal.service_end_date,
        has_invoice=False,
        outstanding_amount=50.0,
        expense_month="2026-01",
        recorded_by="Old Owner",
        notes="old note",
        created_at=datetime(2026, 1, 10, 10, 0, 0),
        user_id="legacy",
    )
    db_session.add(payment)
    await db_session.commit()

    deal.deal_amount = 450.0
    deal.is_paid = True
    deal.package_name = "新媒体代运营升级版"
    deal.notes = "updated note"
    synced_payment = await sync_payment_from_deal(db_session, deal)

    payments = (await db_session.execute(select(Payments))).scalars().all()
    assert len(payments) == 1
    assert synced_payment.id == payment.id
    assert synced_payment.source_deal_id == deal.id
    assert synced_payment.product_name == "新媒体代运营升级版"
    assert synced_payment.income_type == "management_fee"
    assert synced_payment.payment_mode == "manual_collection"
    assert synced_payment.amount_due == 450.0
    assert synced_payment.amount_paid == 450.0
    assert synced_payment.outstanding_amount == 0.0
    assert synced_payment.payment_date == deal.deal_date
    assert synced_payment.notes == "updated note"


@pytest.mark.asyncio
async def test_sync_payment_from_deal_uses_latest_matching_subscription_when_duplicates_exist(db_session):
    customer = await seed_customer(db_session, business_name="Ads Lab")
    deal = await seed_deal(
        db_session,
        customer,
        product_type="ads",
        package_name="Google广告投放",
        deal_amount=2000.0,
        is_paid=True,
        service_start_date=datetime(2026, 6, 1, 0, 0, 0),
        service_end_date=datetime(2026, 6, 30, 0, 0, 0),
        deal_date=datetime(2026, 6, 24, 8, 0, 0),
    )
    db_session.add_all([
        Subscriptions(
            customer_id=customer.id,
            customer_name=customer.business_name,
            package_name=deal.package_name,
            package_price=3000.0,
            billing_cycle=deal.billing_cycle,
            start_date=deal.service_start_date,
            end_date=deal.service_end_date,
            last_payment_date=datetime(2026, 6, 5, 9, 0, 0),
            status="active",
            created_at=datetime(2026, 6, 5, 9, 0, 0),
        ),
        Subscriptions(
            customer_id=customer.id,
            customer_name=customer.business_name,
            package_name=deal.package_name,
            package_price=2000.0,
            billing_cycle=deal.billing_cycle,
            start_date=deal.service_start_date,
            end_date=deal.service_end_date,
            last_payment_date=datetime(2026, 6, 20, 9, 0, 0),
            status="active",
            created_at=datetime(2026, 6, 20, 9, 0, 0),
        ),
    ])
    await db_session.commit()

    synced_payment = await sync_payment_from_deal(db_session, deal)

    assert synced_payment.source_deal_id == deal.id
    assert synced_payment.amount_due == 2000.0
    assert synced_payment.amount_paid == 2000.0
    assert synced_payment.payment_date == datetime(2026, 6, 24, 8, 0, 0)


@pytest.mark.asyncio
async def test_sync_deal_from_payment_reuses_source_deal_id_instead_of_creating_duplicate(db_session):
    customer = await seed_customer(db_session, business_name="Nail World")
    deal = await seed_deal(
        db_session,
        customer,
        product_type="website",
        package_name="网站套餐",
        deal_amount=101.0,
        is_paid=True,
    )
    payment = Payments(
        source_deal_id=deal.id,
        customer_id=customer.id,
        customer_name=customer.business_name,
        income_type="ads_fee",
        product_name="广告投流套餐",
        amount_due=660.0,
        amount_paid=660.0,
        currency="USD",
        payment_date=datetime(2026, 6, 1, 12, 0, 0),
        payment_mode="subscription_auto",
        payment_method="stripe",
        billing_cycle="quarterly",
        coverage_start=datetime(2026, 6, 1, 0, 0, 0),
        coverage_end=datetime(2026, 9, 1, 0, 0, 0),
        has_invoice=True,
        outstanding_amount=0.0,
        expense_month="2026-06",
        recorded_by="Amy",
        notes="sync back to deal",
        created_at=datetime(2026, 6, 1, 12, 0, 0),
        user_id="7",
    )
    db_session.add(payment)
    await db_session.commit()

    synced_deal = await sync_deal_from_payment(db_session, payment)

    deals = (await db_session.execute(select(Deals))).scalars().all()
    assert len(deals) == 1
    assert synced_deal.id == deal.id
    assert synced_deal.package_name == "广告投流套餐"
    assert synced_deal.product_type == "ads"
    assert synced_deal.deal_amount == 660.0
    assert synced_deal.billing_cycle == "quarterly"
    assert synced_deal.service_start_date == datetime(2026, 6, 1, 0, 0, 0)
    assert synced_deal.service_end_date == datetime(2026, 9, 1, 0, 0, 0)
