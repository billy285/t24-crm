"""Close snapshots and automatic receipts serialize on real file-backed SQLite.

The original dashboard and ledger functions are exercised unchanged. Two physical
connections are asserted explicitly; an in-memory StaticPool cannot prove this race.
"""
import asyncio
import json
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select

from backend.tests.test_stripe_auto_posting import prepared, future_invoice, save
from backend.tests.test_stripe_history_reconciliation import history_api, sale_api, headers
from models.finance_exchange_rates import MonthlyExchangeRate
from models.finance_profit_closes import MonthlyProfitClose
from models.payments import Payments
from models.stripe_auto_posting import StripeAutoPostingJob
from routers import management_decisions as closing
from services import stripe_auto_posting as automatic


class AfterOctober(date):
    @classmethod
    def today(cls):
        return cls(2026, 12, 1)


@pytest_asyncio.fixture
async def file_history(history_api):
    _, sessions, _ = history_api
    engine = sessions.kw["bind"]
    assert engine.dialect.name == "sqlite"
    assert engine.url.database and engine.url.database != ":memory:"
    async with engine.connect() as left, engine.connect() as right:
        left_raw = await left.get_raw_connection()
        right_raw = await right.get_raw_connection()
        assert left_raw.driver_connection is not right_raw.driver_connection
        assert (await left.exec_driver_sql("PRAGMA journal_mode=WAL")).scalar() == "wal"
        for connection in (left, right):
            await connection.exec_driver_sql("PRAGMA busy_timeout=2000")
            await connection.commit()

    def configure(connection, _record):
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=2000")
        finally:
            cursor.close()

    event.listen(engine.sync_engine, "connect", configure)
    try:
        yield history_api
    finally:
        event.remove(engine.sync_engine, "connect", configure)


async def ready(file_history, monkeypatch):
    client, sessions, fake, clock, bindings = await prepared(file_history, monkeypatch)
    monkeypatch.setattr(closing, "date", AfterOctober)
    async with sessions() as db:
        db.add(MonthlyExchangeRate(year_month="2026-10", base_currency="USD", quote_currency="CNY",
            average_rate=7.2, source="Synthetic locked rate", status="locked"))
        await db.commit()
    raw = future_invoice(clock)
    fake.invoice_rows[raw["id"]] = raw
    review_id = await save(sessions, bindings[0]["id"], raw)
    return client, sessions, review_id


@pytest.mark.asyncio
async def test_close_first_holds_snapshot_lock_then_auto_receipt_is_rejected(file_history, monkeypatch):
    client, sessions, review_id = await ready(file_history, monkeypatch)
    claim = await automatic.claim_job(sessions)
    assert claim["review_id"] == review_id
    snapshot_ready, release_close = asyncio.Event(), asyncio.Event()
    worker_attempting_lock, worker_acquired_lock = asyncio.Event(), asyncio.Event()
    original_dashboard = closing.build_growth_dashboard
    original_lock = automatic.lock_sales_workflow
    snapshot = {}

    async def held_dashboard(db, **parameters):
        result = await original_dashboard(db, **parameters)
        snapshot.update(result["formal_monthly_profit"]["rows"][0])
        snapshot_ready.set()
        await asyncio.wait_for(release_close.wait(), timeout=3)
        return result

    async def worker_lock(db, *args, **parameters):
        worker_attempting_lock.set()
        await original_lock(db, *args, **parameters)
        worker_acquired_lock.set()

    monkeypatch.setattr(closing, "build_growth_dashboard", held_dashboard)
    monkeypatch.setattr(automatic, "lock_sales_workflow", worker_lock)
    close_task = asyncio.create_task(client.put("/api/v1/management-decisions/profit-closes/2026-10",
        headers=headers(1), json={"action": "close"}))
    worker_task = None
    try:
        await asyncio.wait_for(snapshot_ready.wait(), timeout=3)
        assert snapshot["cash_service_revenue_usd"] == 0
        worker_task = asyncio.create_task(automatic.process_job(sessions, claim))
        await asyncio.wait_for(worker_attempting_lock.wait(), timeout=2)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(worker_acquired_lock.wait(), timeout=0.1)
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Payments)) == 0
    finally:
        release_close.set()
        response = await asyncio.wait_for(close_task, timeout=3)
        if worker_task is not None:
            await asyncio.wait_for(worker_task, timeout=3)
    assert response.status_code == 200, response.text
    async with sessions() as db:
        close = await db.scalar(select(MonthlyProfitClose).where(MonthlyProfitClose.year_month == "2026-10"))
        job = await db.get(StripeAutoPostingJob, review_id)
        assert close.status == "locked"
        assert json.loads(close.snapshot_json)["cash_service_revenue_usd"] == 0
        assert job.status == "manual_required" and "月结" in job.reason
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0
    print("CLOSE_FIRST_PROOF", json.dumps({"distinct_file_connections": True, "worker_waited": True,
        "locked_cash_revenue": 0, "payments_after_close": 0, "job": "manual_required"}))


@pytest.mark.asyncio
async def test_auto_receipt_commits_first_then_close_snapshot_contains_it(file_history, monkeypatch):
    client, sessions, review_id = await ready(file_history, monkeypatch)
    assert (await automatic.run_batch(sessions))["processed"] == 1
    async with sessions() as db:
        assert (await db.get(StripeAutoPostingJob, review_id)).status == "auto_posted"
        payment = await db.scalar(select(Payments))
        assert payment.amount_paid == 198
    response = await client.put("/api/v1/management-decisions/profit-closes/2026-10",
        headers=headers(1), json={"action": "close"})
    assert response.status_code == 200, response.text
    async with sessions() as db:
        close = await db.scalar(select(MonthlyProfitClose).where(MonthlyProfitClose.year_month == "2026-10"))
        snapshot = json.loads(close.snapshot_json)
        assert close.status == "locked"
        assert snapshot["cash_service_revenue_usd"] == 198
        assert snapshot["recognized_service_revenue_usd"] > 0
        assert snapshot["stripe_fee_usd"] == payment.stripe_fee_amount
        assert await db.scalar(select(func.count()).select_from(Payments)) == 1
    print("AUTO_FIRST_PROOF", json.dumps({"distinct_file_connections": True, "payments": 1,
        "locked_cash_revenue": snapshot["cash_service_revenue_usd"],
        "locked_recognized_revenue": snapshot["recognized_service_revenue_usd"],
        "locked_fee": snapshot["stripe_fee_usd"]}))
