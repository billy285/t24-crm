import asyncio
from datetime import datetime
import importlib
import pkgutil

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.database import Base
import models as models_package
from models.customers import Customers
from models.deals import Deals
from models.payments import Payments
from models.service_progresses import Service_progresses
from models.service_tasks import Service_tasks
from models.subscriptions import Subscriptions
from routers import deals as deals_router
from routers.deals import (
    DealsBatchCreateRequest,
    DealsBatchDeleteRequest,
    DealsBatchUpdateItem,
    DealsBatchUpdateRequest,
    DealsData,
    DealsUpdateData,
    DealFinalizeRequest,
)
from schemas.auth import UserResponse
from services.deal_payment_sync import sync_payment_from_deal
from services.deals import DealsService


for module_info in pkgutil.iter_modules(models_package.__path__, models_package.__name__ + "."):
    importlib.import_module(module_info.name)


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


def deal_data(customer_id: int, *, package_name: str = "基础套餐", amount: float = 198.0) -> DealsData:
    now = datetime(2026, 8, 1, 9, 0, 0)
    return DealsData(
        customer_id=customer_id,
        customer_name=f"Customer {customer_id}",
        product_type="social_media",
        package_name=package_name,
        billing_cycle="monthly",
        deal_amount=amount,
        is_paid=True,
        deal_date=now,
        created_at=now,
    )


async def seed_deal_and_payment(db_session, customer_id: int, *, amount: float = 198.0):
    deal = await DealsService(db_session).create(
        deal_data(customer_id, amount=amount).model_dump(),
        commit=False,
    )
    payment = await sync_payment_from_deal(db_session, deal, commit=False)
    await db_session.commit()
    return deal, payment


async def load_deals(db_session):
    return (await db_session.scalars(select(Deals).order_by(Deals.id))).all()


async def load_payments(db_session):
    return (await db_session.scalars(select(Payments).order_by(Payments.id))).all()


async def seed_customer(db_session, customer_id: int, *, status: str = "following") -> Customers:
    customer = Customers(
        id=customer_id,
        business_name=f"Finalize Customer {customer_id}",
        contact_name="负责人",
        phone=f"555-{customer_id:04d}",
        sales_person="成交管理员",
        status=status,
        created_at=datetime(2026, 8, 1, 8, 0, 0),
        updated_at=datetime(2026, 8, 1, 8, 0, 0),
    )
    db_session.add(customer)
    await db_session.commit()
    return customer


def admin_user() -> UserResponse:
    return UserResponse(
        id="1",
        email="owner@example.test",
        name="成交管理员",
        role="admin",
        last_login=None,
    )


def finalize_request() -> DealFinalizeRequest:
    return DealFinalizeRequest(
        ensure_subscription=True,
        auto_renew=True,
        create_service_board=True,
    )


async def seed_finalize_deal(db_session, customer_id: int) -> Deals:
    data = deal_data(customer_id, package_name="进阶套餐", amount=249.0)
    payload = data.model_dump()
    payload.update({
        "package_platforms": "facebook",
        "service_start_date": datetime(2026, 8, 1, 0, 0, 0),
        "service_end_date": datetime(2026, 9, 1, 0, 0, 0),
    })
    deal = await DealsService(db_session).create(payload, commit=False)
    await sync_payment_from_deal(db_session, deal, commit=False)
    await db_session.commit()
    return deal


@pytest.mark.asyncio
async def test_create_update_delete_commits_deal_and_payment_as_one_unit(db_session):
    created = await deals_router.create_deals(deal_data(10), _finance_user=None, db=db_session)
    payments = await load_payments(db_session)
    assert len(payments) == 1
    assert payments[0].source_deal_id == created.id
    assert payments[0].amount_due == 198.0

    updated = await deals_router.update_deals(
        created.id,
        DealsUpdateData(deal_amount=329.0, is_paid=False),
        _finance_user=None,
        db=db_session,
    )
    payment = (await load_payments(db_session))[0]
    assert updated.deal_amount == 329.0
    assert payment.amount_due == 329.0
    assert payment.amount_paid == 0.0

    await deals_router.delete_deals(created.id, _finance_user=None, db=db_session)
    assert await load_deals(db_session) == []
    remaining_payment = (await load_payments(db_session))[0]
    assert remaining_payment.source_deal_id is None


@pytest.mark.asyncio
async def test_create_rolls_back_deal_when_payment_sync_fails_after_flush(db_session, monkeypatch):
    original_sync = deals_router.sync_payment_from_deal

    async def sync_then_fail(db, deal, commit=True, **kwargs):
        await original_sync(db, deal, commit=False, **kwargs)
        raise RuntimeError("simulated sync failure")

    monkeypatch.setattr(deals_router, "sync_payment_from_deal", sync_then_fail)

    with pytest.raises(HTTPException) as error:
        await deals_router.create_deals(deal_data(1), _finance_user=None, db=db_session)

    assert error.value.status_code == 500
    assert await load_deals(db_session) == []
    assert await load_payments(db_session) == []


@pytest.mark.asyncio
async def test_update_rolls_back_both_deal_and_payment_when_sync_fails(db_session, monkeypatch):
    deal, payment = await seed_deal_and_payment(db_session, 2)
    deal_id, payment_id = deal.id, payment.id
    original_sync = deals_router.sync_payment_from_deal

    async def sync_then_fail(db, changed_deal, commit=True, **kwargs):
        await original_sync(db, changed_deal, commit=False, **kwargs)
        raise RuntimeError("simulated sync failure")

    monkeypatch.setattr(deals_router, "sync_payment_from_deal", sync_then_fail)

    with pytest.raises(HTTPException) as error:
        await deals_router.update_deals(
            deal_id,
            DealsUpdateData(deal_amount=329.0, package_name="专业套餐"),
            _finance_user=None,
            db=db_session,
        )

    assert error.value.status_code == 500
    restored_deal = await db_session.get(Deals, deal_id)
    restored_payment = await db_session.get(Payments, payment_id)
    assert restored_deal.deal_amount == 198.0
    assert restored_deal.package_name == "基础套餐"
    assert restored_payment.amount_due == 198.0
    assert restored_payment.product_name == "基础套餐"


@pytest.mark.asyncio
async def test_delete_rolls_back_deal_and_payment_link_when_unlink_fails(db_session, monkeypatch):
    deal, payment = await seed_deal_and_payment(db_session, 3)
    deal_id, payment_id = deal.id, payment.id
    original_unlink = deals_router.unlink_synced_payment_for_deal

    async def unlink_then_fail(db, deal_id, commit=True):
        await original_unlink(db, deal_id, commit=False)
        raise RuntimeError("simulated unlink failure")

    monkeypatch.setattr(deals_router, "unlink_synced_payment_for_deal", unlink_then_fail)

    with pytest.raises(HTTPException) as error:
        await deals_router.delete_deals(deal_id, _finance_user=None, db=db_session)

    assert error.value.status_code == 500
    assert await db_session.get(Deals, deal_id) is not None
    restored_payment = await db_session.get(Payments, payment_id)
    assert restored_payment.source_deal_id == deal_id


@pytest.mark.asyncio
async def test_batch_create_is_all_or_nothing_when_second_sync_fails(db_session, monkeypatch):
    original_sync = deals_router.sync_payment_from_deal
    calls = 0

    async def fail_second_sync(db, deal, commit=True, **kwargs):
        nonlocal calls
        calls += 1
        await original_sync(db, deal, commit=False, **kwargs)
        if calls == 2:
            raise RuntimeError("simulated second sync failure")

    monkeypatch.setattr(deals_router, "sync_payment_from_deal", fail_second_sync)
    request = DealsBatchCreateRequest(items=[deal_data(4), deal_data(5, amount=249.0)])

    with pytest.raises(HTTPException) as error:
        await deals_router.create_dealss_batch(request, _finance_user=None, db=db_session)

    assert error.value.status_code == 500
    assert await load_deals(db_session) == []
    assert await load_payments(db_session) == []


@pytest.mark.asyncio
async def test_batch_update_is_all_or_nothing_when_second_sync_fails(db_session, monkeypatch):
    first, first_payment = await seed_deal_and_payment(db_session, 6)
    second, second_payment = await seed_deal_and_payment(db_session, 7, amount=249.0)
    first_id, first_payment_id = first.id, first_payment.id
    second_id, second_payment_id = second.id, second_payment.id
    original_sync = deals_router.sync_payment_from_deal
    calls = 0

    async def fail_second_sync(db, deal, commit=True, **kwargs):
        nonlocal calls
        calls += 1
        await original_sync(db, deal, commit=False, **kwargs)
        if calls == 2:
            raise RuntimeError("simulated second sync failure")

    monkeypatch.setattr(deals_router, "sync_payment_from_deal", fail_second_sync)
    request = DealsBatchUpdateRequest(items=[
        DealsBatchUpdateItem(id=first_id, updates=DealsUpdateData(deal_amount=329.0)),
        DealsBatchUpdateItem(id=second_id, updates=DealsUpdateData(deal_amount=499.0)),
    ])

    with pytest.raises(HTTPException) as error:
        await deals_router.update_dealss_batch(request, _finance_user=None, db=db_session)

    assert error.value.status_code == 500
    assert (await db_session.get(Deals, first_id)).deal_amount == 198.0
    assert (await db_session.get(Deals, second_id)).deal_amount == 249.0
    assert (await db_session.get(Payments, first_payment_id)).amount_due == 198.0
    assert (await db_session.get(Payments, second_payment_id)).amount_due == 249.0


@pytest.mark.asyncio
async def test_batch_delete_is_all_or_nothing_when_second_unlink_fails(db_session, monkeypatch):
    first, first_payment = await seed_deal_and_payment(db_session, 8)
    second, second_payment = await seed_deal_and_payment(db_session, 9, amount=249.0)
    first_id, first_payment_id = first.id, first_payment.id
    second_id, second_payment_id = second.id, second_payment.id
    original_unlink = deals_router.unlink_synced_payment_for_deal
    calls = 0

    async def fail_second_unlink(db, deal_id, commit=True):
        nonlocal calls
        calls += 1
        await original_unlink(db, deal_id, commit=False)
        if calls == 2:
            raise RuntimeError("simulated second unlink failure")

    monkeypatch.setattr(deals_router, "unlink_synced_payment_for_deal", fail_second_unlink)

    with pytest.raises(HTTPException) as error:
        await deals_router.delete_dealss_batch(
            DealsBatchDeleteRequest(ids=[first_id, second_id]),
            _finance_user=None,
            db=db_session,
        )

    assert error.value.status_code == 500
    assert await db_session.get(Deals, first_id) is not None
    assert await db_session.get(Deals, second_id) is not None
    assert (await db_session.get(Payments, first_payment_id)).source_deal_id == first_id
    assert (await db_session.get(Payments, second_payment_id)).source_deal_id == second_id


@pytest.mark.asyncio
async def test_finalize_is_idempotent_for_subscription_customer_and_service_board(db_session):
    customer = await seed_customer(db_session, 20)
    deal = await seed_finalize_deal(db_session, customer.id)
    deal_id = deal.id

    first = await deals_router.finalize_deal_handoff(
        deal_id,
        finalize_request(),
        current_user=admin_user(),
        db=db_session,
    )
    second = await deals_router.finalize_deal_handoff(
        deal_id,
        finalize_request(),
        current_user=admin_user(),
        db=db_session,
    )

    assert first.complete is True
    assert first.steps["service_board"].created_count == 6
    assert second.complete is True
    assert second.steps["service_board"].created_count == 0
    assert len((await db_session.scalars(select(Subscriptions).where(Subscriptions.deal_id == deal_id))).all()) == 1
    assert len((await db_session.scalars(select(Service_progresses).where(Service_progresses.customer_id == customer.id))).all()) == 1
    assert len((await db_session.scalars(select(Service_tasks).where(Service_tasks.customer_id == customer.id))).all()) == 6
    assert (await db_session.get(Customers, customer.id)).status == "closed"


@pytest.mark.asyncio
async def test_finalize_rolls_back_failed_board_then_retry_converges_without_duplicates(db_session, monkeypatch):
    customer = await seed_customer(db_session, 21)
    deal = await seed_finalize_deal(db_session, customer.id)
    deal_id, customer_id = deal.id, customer.id
    original_ensure_board = deals_router.ensure_service_board

    async def board_then_fail(db, deal, **kwargs):
        await original_ensure_board(db, deal, **kwargs)
        raise RuntimeError("simulated board failure")

    monkeypatch.setattr(deals_router, "ensure_service_board", board_then_fail)
    first = await deals_router.finalize_deal_handoff(
        deal_id,
        finalize_request(),
        current_user=admin_user(),
        db=db_session,
    )

    assert first.complete is False
    assert first.steps["subscription"].status == "completed"
    assert first.steps["customer"].status == "completed"
    assert first.steps["service_board"].status == "failed"
    assert len((await db_session.scalars(select(Subscriptions).where(Subscriptions.deal_id == deal_id))).all()) == 1
    assert (await db_session.get(Customers, customer_id)).status == "closed"
    assert (await db_session.scalars(select(Service_progresses).where(Service_progresses.customer_id == customer_id))).all() == []
    assert (await db_session.scalars(select(Service_tasks).where(Service_tasks.customer_id == customer_id))).all() == []

    monkeypatch.setattr(deals_router, "ensure_service_board", original_ensure_board)
    retried = await deals_router.finalize_deal_handoff(
        deal_id,
        finalize_request(),
        current_user=admin_user(),
        db=db_session,
    )
    assert retried.complete is True
    assert len((await db_session.scalars(select(Subscriptions).where(Subscriptions.deal_id == deal_id))).all()) == 1
    assert len((await db_session.scalars(select(Service_progresses).where(Service_progresses.customer_id == customer_id))).all()) == 1
    assert len((await db_session.scalars(select(Service_tasks).where(Service_tasks.customer_id == customer_id))).all()) == 6


@pytest.mark.asyncio
async def test_finalize_rolls_back_core_failure_then_retry_converges_without_duplicates(db_session, monkeypatch):
    customer = await seed_customer(db_session, 22)
    deal = await seed_finalize_deal(db_session, customer.id)
    deal_id, customer_id = deal.id, customer.id
    original_finalize_core = deals_router.finalize_subscription_and_customer

    async def core_then_fail(db, deal, **kwargs):
        await original_finalize_core(db, deal, **kwargs)
        raise RuntimeError("simulated core failure")

    monkeypatch.setattr(deals_router, "finalize_subscription_and_customer", core_then_fail)
    first = await deals_router.finalize_deal_handoff(
        deal_id,
        finalize_request(),
        current_user=admin_user(),
        db=db_session,
    )

    assert first.complete is False
    assert first.steps["subscription"].status == "failed"
    assert first.steps["customer"].status == "failed"
    assert (await db_session.scalars(select(Subscriptions).where(Subscriptions.deal_id == deal_id))).all() == []
    assert (await db_session.get(Customers, customer_id)).status == "following"

    monkeypatch.setattr(deals_router, "finalize_subscription_and_customer", original_finalize_core)
    retried = await deals_router.finalize_deal_handoff(
        deal_id,
        finalize_request(),
        current_user=admin_user(),
        db=db_session,
    )
    assert retried.complete is True
    assert len((await db_session.scalars(select(Subscriptions).where(Subscriptions.deal_id == deal_id))).all()) == 1
    assert len((await db_session.scalars(select(Service_progresses).where(Service_progresses.customer_id == customer_id))).all()) == 1


@pytest.mark.asyncio
async def test_concurrent_finalize_calls_converge_to_single_subscription_and_board(tmp_path):
    database_path = tmp_path / "concurrent-finalize.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as seed_session:
        customer = await seed_customer(seed_session, 23)
        deal = await seed_finalize_deal(seed_session, customer.id)
        deal_id, customer_id = deal.id, customer.id

    async def run_finalize():
        async with session_maker() as session:
            return await deals_router.finalize_deal_handoff(
                deal_id,
                finalize_request(),
                current_user=admin_user(),
                db=session,
            )

    first, second = await asyncio.gather(run_finalize(), run_finalize())
    assert first.complete is True
    assert second.complete is True

    async with session_maker() as verify_session:
        subscriptions = (await verify_session.scalars(
            select(Subscriptions).where(Subscriptions.deal_id == deal_id)
        )).all()
        progresses = (await verify_session.scalars(
            select(Service_progresses).where(Service_progresses.customer_id == customer_id)
        )).all()
        tasks = (await verify_session.scalars(
            select(Service_tasks).where(Service_tasks.customer_id == customer_id)
        )).all()
        assert len(subscriptions) == 1
        assert len(progresses) == 1
        assert len(tasks) == 6

    await engine.dispose()
