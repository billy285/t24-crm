"""External refund identities are serialized before a ledger row is created."""
import asyncio
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models.finance_profit_closes import MonthlyProfitClose
from models.finance_refunds import FinanceRefund
from models.payments import Payments
from models.sales_leads import SalesLeads
from routers import finance_adjustments as adjustments
from schemas.auth import UserResponse
from services.sales_workflow_locks import lock_sales_workflow


ACTOR = UserResponse(id="1", email="owner@example.test", name="Synthetic owner", role="super_admin")
DATE = datetime(2026, 11, 1, tzinfo=timezone.utc)


def request(**updates):
    return adjustments.RefundCreate(**{"payment_id": 1, "refund_amount": 30, "refund_date": DATE,
        "provider": "stripe", "provider_refund_id": "re_synthetic_001", **updates})


@pytest_asyncio.fixture
async def refund_store(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'refund.db'}", connect_args={"timeout": 3})
    async with engine.begin() as connection:
        for table in (Payments.__table__, FinanceRefund.__table__, MonthlyProfitClose.__table__, SalesLeads.__table__):
            await connection.run_sync(table.create)
        await connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    calls = []

    async def available(_db):
        return True

    async def sync(_db, row):
        calls.append(row.id)

    monkeypatch.setattr(adjustments, "commission_ledger_available", available)
    monkeypatch.setattr(adjustments, "sync_refund_commission", sync)
    async with sessions() as db:
        db.add_all([Payments(id=i, customer_id=i, customer_name=f"Synthetic {i}",
            income_type="management_fee", amount_due=198, amount_paid=198, currency="USD", payment_date=DATE, user_id="1") for i in (1, 2)])
        await db.commit()
    try:
        yield sessions, calls, engine
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_same_provider_refund_replay_returns_original_without_second_reversal(refund_store):
    sessions, calls, _ = refund_store
    async with sessions() as db:
        first = await adjustments.create_refund(request(), ACTOR, db)
        original_id = first.id
        repeated = await adjustments.create_refund(request(), ACTOR, db)
        assert repeated.id == original_id
        assert await db.scalar(select(func.count()).select_from(FinanceRefund)) == 1
        assert calls == [original_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"payment_id": 2}, {"refund_amount": 31},
    {"stripe_fee_refunded_amount": 1}, {"status": "pending"},
    {"refund_date": datetime(2026, 11, 2, tzinfo=timezone.utc)}])
async def test_reused_provider_identity_with_changed_financial_content_is_rejected(refund_store, changes):
    sessions, calls, _ = refund_store
    async with sessions() as db:
        first = await adjustments.create_refund(request(), ACTOR, db)
        original_id = first.id
        payload = request().model_dump()
        payload.update(changes)
        with pytest.raises(HTTPException) as rejected:
            await adjustments.create_refund(adjustments.RefundCreate(**payload), ACTOR, db)
        assert rejected.value.status_code == 409
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(FinanceRefund)) == 1
        assert calls == [original_id]


@pytest.mark.asyncio
async def test_exact_replay_remains_read_only_after_month_was_closed(refund_store):
    sessions, calls, _ = refund_store
    async with sessions() as db:
        first = await adjustments.create_refund(request(), ACTOR, db)
        original_id = first.id
        db.add(MonthlyProfitClose(year_month="2026-11", status="locked", snapshot_json="{}"))
        await db.commit()
        repeated = await adjustments.create_refund(request(), ACTOR, db)
        assert repeated.id == original_id and calls == [original_id]
        payload = request().model_dump()
        payload["provider_refund_id"] = "re_synthetic_new"
        with pytest.raises(HTTPException) as rejected:
            await adjustments.create_refund(adjustments.RefundCreate(**payload), ACTOR, db)
        assert rejected.value.status_code == 409 and "月结" in rejected.value.detail


@pytest.mark.asyncio
async def test_historical_duplicate_reference_is_not_silently_selected(refund_store):
    sessions, _, _ = refund_store
    async with sessions() as db:
        for _ in range(2):
            db.add(FinanceRefund(payment_id=1, customer_id=1, refund_amount=30, currency="USD",
                refund_date=DATE, provider="stripe", provider_refund_id="re_synthetic_001",
                stripe_fee_refunded_amount=0, status="completed", created_at=DATE, user_id="1"))
        await db.commit()
        with pytest.raises(HTTPException) as rejected:
            await adjustments.create_refund(request(), ACTOR, db)
        assert rejected.value.status_code == 409
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(FinanceRefund)) == 2


@pytest.mark.asyncio
async def test_simultaneous_replays_on_distinct_connections_create_one_refund(refund_store, monkeypatch):
    sessions, calls, engine = refund_store
    async with engine.connect() as left, engine.connect() as right:
        assert (await left.get_raw_connection()).driver_connection is not (await right.get_raw_connection()).driver_connection
    locked, release = asyncio.Event(), asyncio.Event()
    original = adjustments.ensure_profit_months_open
    visits = 0

    async def hold_first(db, months, **kwargs):
        nonlocal visits
        visits += 1
        if visits == 1:
            locked.set()
            await asyncio.wait_for(release.wait(), timeout=3)
        return await original(db, months, **kwargs)

    monkeypatch.setattr(adjustments, "ensure_profit_months_open", hold_first)

    async def submit():
        async with sessions() as db:
            return (await adjustments.create_refund(request(), ACTOR, db)).id

    first = asyncio.create_task(submit())
    await asyncio.wait_for(locked.wait(), timeout=2)
    second = asyncio.create_task(submit())
    await asyncio.sleep(0.05)
    assert not second.done()
    release.set()
    result = await asyncio.gather(first, second)
    assert result[0] == result[1] and calls == [result[0]]
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(FinanceRefund)) == 1


@pytest.mark.parametrize("field,value", [("refund_amount", float("inf")),
    ("refund_amount", float("nan")), ("stripe_fee_refunded_amount", float("inf")),
    ("refund_amount", 0.001)])
def test_nonfinite_money_cannot_enter_refund_ledger(field, value):
    payload = request().model_dump()
    payload[field] = value
    with pytest.raises(ValidationError):
        adjustments.RefundCreate(**payload)


@pytest.mark.asyncio
async def test_distinct_refunds_without_external_ids_are_not_guessed_duplicates(refund_store):
    sessions, calls, _ = refund_store
    async with sessions() as db:
        first = await adjustments.create_refund(request(provider_refund_id=None), ACTOR, db)
        first_id = first.id
        second = await adjustments.create_refund(request(provider_refund_id=None), ACTOR, db)
        assert second.id != first_id and calls == [first_id, second.id]


@pytest.mark.asyncio
async def test_provider_normalization_preserves_case_sensitive_external_identity(refund_store):
    sessions, _, _ = refund_store
    async with sessions() as db:
        original = (await adjustments.create_refund(request(provider=" Stripe ", provider_refund_id=" re_Case "), ACTOR, db)).id
        repeated = await adjustments.create_refund(request(provider_refund_id="re_Case"), ACTOR, db)
        assert repeated.id == original
        different = await adjustments.create_refund(request(provider_refund_id="re_case"), ACTOR, db)
        assert different.id != original


@pytest.mark.asyncio
async def test_simultaneous_distinct_refunds_cannot_overreserve_payment(refund_store):
    sessions, calls, _ = refund_store

    async def submit(reference):
        async with sessions() as db:
            try:
                return (await adjustments.create_refund(request(refund_amount=120, provider_refund_id=reference), ACTOR, db)).id
            except HTTPException as error:
                return error

    results = await asyncio.gather(submit("re_left"), submit("re_right"))
    assert sum(isinstance(result, int) for result in results) == 1
    rejected = next(result for result in results if isinstance(result, HTTPException))
    assert rejected.status_code == 400 and "不能超过" in rejected.detail
    assert len(calls) == 1
    async with sessions() as db:
        assert await db.scalar(select(func.sum(FinanceRefund.refund_amount))) == 120


@pytest.mark.asyncio
async def test_close_lock_wins_before_new_refund_checks_month(refund_store):
    sessions, calls, _ = refund_store
    async with sessions() as closing_db:
        await lock_sales_workflow(closing_db)
        closing_db.add(MonthlyProfitClose(year_month="2026-11", status="locked", snapshot_json="{}"))
        await closing_db.flush()

        async def submit():
            async with sessions() as db:
                with pytest.raises(HTTPException) as rejected:
                    await adjustments.create_refund(request(), ACTOR, db)
                return rejected.value

        waiting = asyncio.create_task(submit())
        await asyncio.sleep(0.05)
        assert not waiting.done()
        await closing_db.commit()
        rejected = await waiting
        assert rejected.status_code == 409 and "月结" in rejected.detail
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("timestamp,booked_month,utc_month", [
    ("2026-11-01T00:00:00-05:00", "2026-11", "2026-11"),
    ("2026-11-01T00:30:00+08:00", "2026-11", "2026-10"),
    ("2026-10-31T23:30:00-05:00", "2026-10", "2026-11"),
])
async def test_offset_replay_preserves_sqlite_booked_wallclock_and_original_month(refund_store, timestamp, booked_month, utc_month):
    sessions, calls, engine = refund_store
    assert engine.url.database.endswith("refund.db")
    booked_at = datetime.fromisoformat(timestamp)
    payload = request(refund_date=booked_at)
    async with sessions() as db:
        # Existing period guards use the booked date, not a shifted UTC month.
        if utc_month != booked_month:
            db.add(MonthlyProfitClose(year_month=utc_month, status="locked", snapshot_json="{}"))
            await db.commit()
        created_id = (await adjustments.create_refund(payload, ACTOR, db)).id
    # Reload on another file-backed connection so SQLite's timezone-free stored
    # representation is compared against the original offset-bearing request.
    async with sessions() as db:
        stored = await db.get(FinanceRefund, created_id)
        assert stored.refund_date == booked_at.replace(tzinfo=None)
        repeated = await adjustments.create_refund(payload, ACTOR, db)
        assert repeated.id == created_id
        db.add(MonthlyProfitClose(year_month=booked_month, status="locked", snapshot_json="{}"))
        await db.commit()
    async with sessions() as db:
        repeated_after_close = await adjustments.create_refund(payload, ACTOR, db)
        assert repeated_after_close.id == created_id and calls == [created_id]
        assert await db.scalar(select(func.count()).select_from(FinanceRefund)) == 1
        with pytest.raises(HTTPException) as rejected:
            await adjustments.create_refund(request(refund_date=booked_at, provider_refund_id="re_new_after_close"), ACTOR, db)
        assert rejected.value.status_code == 409 and "月结" in rejected.value.detail
