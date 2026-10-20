"""File-SQLite daily recheck concurrency, recovery and ledger isolation."""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.tests.test_sales_catalog_handoffs import headers, sale_api
from backend.tests.test_stripe_history_reconciliation import (API, FakeReader, bind, confirmation, history_api,
    manual_payment, remote_invoice, snapshot, sync)
from models.stripe_history_daily_scan import StripeHistoryScanState
from models.stripe_history_reconciliation import StripeHistoryBinding, StripeHistoryInvoiceReview, StripeHistoryPosting
from models.payments import Payments
from services import stripe_history_daily_scan as daily


AT = datetime(2026, 10, 19, 1, 0, tzinfo=timezone.utc)  # Beijing 09:00.


class Clock:
    def __init__(self, value=AT):
        self.value = value

    def __call__(self):
        value = self.value
        self.value += timedelta(microseconds=1)
        return value


class Pages(FakeReader):
    def __init__(self, count=23):
        super().__init__()
        self.records = []
        for index in range(count):
            raw = remote_invoice(100)
            raw["id"] = f"in_scan{index:04}"
            charge = raw["payment_intent"]["latest_charge"]
            raw["payment_intent"]["id"] = charge["payment_intent"] = f"pi_scan{index:04}"
            charge["id"] = charge["balance_transaction"]["source"] = f"ch_scan{index:04}"
            charge["invoice"] = raw["id"]
            self.records.append(raw)

    async def invoices(self, subscription_id, start, end, cursor=None):
        self.calls.append((subscription_id, start, end, cursor))
        matching = [raw for raw in self.records if raw["subscription"] == subscription_id and start <= raw["created"] < end]
        position = next((index + 1 for index, raw in enumerate(matching) if raw["id"] == cursor), 0) if cursor else 0
        return copy.deepcopy(matching[position:position+10]), position + 10 < len(matching)


async def state(sessions, binding_id):
    async with sessions() as db:
        return await db.get(StripeHistoryScanState, binding_id)


def test_beijing_nine_schedule_and_initial_startup_catchup():
    assert daily.scheduled_target(AT) == AT
    assert daily.scheduled_target(AT - timedelta(microseconds=1)) == AT - timedelta(days=1)
    assert daily.next_scheduled(AT) == AT + timedelta(days=1)
    assert daily.scheduled_target(datetime(2027, 1, 1, 0, tzinfo=timezone.utc)) == datetime(2026, 12, 31, 1, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_complete_pagination_restart_and_daily_recheck_never_write_old_rows(history_api):
    client, sessions, _ = history_api
    binding = await bind(client)
    original = await snapshot(sessions)
    pages = Pages()
    clock = Clock()
    assert (await daily.run_batch(sessions=sessions, reader=pages, clock=clock, max_pages=1))["processed_pages"] == 1
    checkpoint = await state(sessions, binding["id"])
    assert checkpoint.cursor == "in_scan0009" and checkpoint.covered_through is None and checkpoint.completed_for is None
    # New process/reader starts only from durable DB state, not process memory.
    restarted = Pages()
    await daily.run_batch(sessions=sessions, reader=restarted, clock=clock, max_pages=1)
    assert restarted.calls[0][-1] == "in_scan0009"
    checkpoint = await state(sessions, binding["id"])
    assert checkpoint.cursor == "in_scan0019" and checkpoint.covered_through is None
    await daily.run_batch(sessions=sessions, reader=restarted, clock=clock, max_pages=1)
    checkpoint = await state(sessions, binding["id"])
    assert checkpoint.completed_for == "2026-10-19" and daily.utc(checkpoint.covered_through) == AT
    assert (checkpoint.page_count, checkpoint.invoice_count, checkpoint.discovered_count) == (3, 23, 23)
    calls = len(restarted.calls)
    assert (await daily.run_batch(sessions=sessions, reader=restarted, clock=clock))["processed_pages"] == 0
    assert len(restarted.calls) == calls
    await daily.run_batch(sessions=sessions, reader=restarted, clock=Clock(AT + timedelta(days=1)))
    checkpoint = await state(sessions, binding["id"])
    assert checkpoint.completed_for == "2026-10-20" and checkpoint.discovered_count == 0
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(StripeHistoryInvoiceReview)) == 23
        assert await db.scalar(select(func.count()).select_from(StripeHistoryPosting)) == 0
    assert await snapshot(sessions) == original


@pytest.mark.asyncio
async def test_long_downtime_windows_complete_only_after_all_ranges(history_api):
    client, sessions, fake = history_api
    binding = await bind(client)
    clock = Clock(datetime(2027, 9, 1, 1, tzinfo=timezone.utc))
    await daily.run_batch(sessions=sessions, reader=fake, clock=clock, max_pages=1)
    checkpoint = await state(sessions, binding["id"])
    assert checkpoint.completed_for is None and checkpoint.covered_through is None
    assert checkpoint.page_count == 1
    while (await state(sessions, binding["id"])).completed_for is None:
        await daily.run_batch(sessions=sessions, reader=fake, clock=clock)
    calls = [call for call in fake.calls if call[0] == "invoices"]
    assert all(end - start <= 93 * 86400 for _, _, start, end, _ in calls)
    assert calls[0][2] == int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp())
    assert all(left[3] == right[2] for left, right in zip(calls, calls[1:]))
    assert daily.utc((await state(sessions, binding["id"])).covered_through) == datetime(2027, 9, 1, 1, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_independent_engines_claim_one_lease_and_old_lease_cannot_save(history_api):
    client, sessions, _ = history_api
    binding = await bind(client)
    engine2 = create_async_engine(str(sessions.kw["bind"].url))
    other_sessions = async_sessionmaker(engine2, expire_on_commit=False)
    try:
        first, second = await asyncio.gather(daily.claim_page(sessions, AT), daily.claim_page(other_sessions, AT))
        jobs = [job for job in (first, second) if job]
        assert len(jobs) == 1
        old = jobs[0]
        assert await daily.claim_page(other_sessions, AT + timedelta(seconds=20)) is None
        new = await daily.claim_page(other_sessions, AT + timedelta(seconds=daily.LEASE_SECONDS + 1))
        assert new and new["token"] != old["token"]
        assert not await daily.finish_page(sessions, old, [remote_invoice()], False, AT + timedelta(seconds=92))
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(StripeHistoryInvoiceReview)) == 0
        assert await daily.finish_page(other_sessions, new, [remote_invoice()], False, AT + timedelta(seconds=92))
        assert (await state(sessions, binding["id"])).completed_for == "2026-10-19"
    finally:
        await engine2.dispose()


@pytest.mark.asyncio
async def test_provider_failure_backoff_is_visible_and_does_not_block_other_binding(history_api, monkeypatch):
    client, sessions, fake = history_api
    one, two = await bind(client), await bind(client, 101)
    original = fake.invoices
    async def intermittent(identity, *args):
        if identity == "sub_history100":
            raise HTTPException(503, "Synthetic secret-looking response must not be persisted")
        return await original(identity, *args)
    fake.invoices = intermittent
    await daily.run_batch(sessions=sessions, reader=fake, clock=Clock())
    failed, success = await state(sessions, one["id"]), await state(sessions, two["id"])
    assert failed.last_error_code == "provider_unavailable" and failed.failure_count == 1
    assert daily.utc(failed.retry_at) >= AT + timedelta(seconds=60) and failed.cursor is None and failed.covered_through is None
    assert success.completed_for == "2026-10-19"
    fake.invoices = original
    assert (await daily.run_batch(sessions=sessions, reader=fake, clock=Clock(AT + timedelta(seconds=30))))["processed_pages"] == 0
    await daily.run_batch(sessions=sessions, reader=fake, clock=Clock(AT + timedelta(seconds=61)))
    assert (await state(sessions, one["id"])).completed_for == "2026-10-19"


@pytest.mark.asyncio
async def test_large_binding_yields_turn_to_other_bindings(history_api):
    client, sessions, _ = history_api
    one, two = await bind(client), await bind(client, 101)
    reader = Pages()
    # Binding101 has no records, but still receives its own full coverage turn.
    await daily.run_batch(sessions=sessions, reader=reader, clock=Clock(), max_pages=2)
    assert [call[0] for call in reader.calls] == ["sub_history100", "sub_history101"]
    assert (await state(sessions, one["id"])).covered_through is None
    assert (await state(sessions, two["id"])).completed_for == "2026-10-19"


@pytest.mark.asyncio
async def test_page_evidence_and_cursor_rollback_together_then_replay(history_api, monkeypatch):
    client, sessions, _ = history_api
    binding = await bind(client)
    original = await snapshot(sessions)
    reader = Pages(2)
    real_save = daily.save_invoice
    async def failing_save(db, current, raw):
        result = await real_save(db, current, raw)
        if raw["id"] == "in_scan0001":
            raise RuntimeError("Synthetic page save interruption")
        return result
    monkeypatch.setattr(daily, "save_invoice", failing_save)
    await daily.run_batch(sessions=sessions, reader=reader, clock=Clock(), max_pages=1)
    failed = await state(sessions, binding["id"])
    assert failed.last_error_code == "scan_failed" and failed.cursor is None and failed.page_count == 0
    assert failed.covered_through is None
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(StripeHistoryInvoiceReview)) == 0
    monkeypatch.setattr(daily, "save_invoice", real_save)
    await daily.run_batch(sessions=sessions, reader=reader, clock=Clock(AT + timedelta(seconds=61)))
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(StripeHistoryInvoiceReview)) == 2
    assert await snapshot(sessions) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["subscription", "conflicting_subscription", "customer", "livemode", "outside_window", "duplicate", "bad_cursor"])
async def test_foreign_or_broken_page_is_never_saved_or_marked_covered(history_api, case):
    client, sessions, _ = history_api
    binding = await bind(client)
    job = await daily.claim_page(sessions, AT)
    raw = remote_invoice()
    more = False
    if case == "subscription": raw["subscription"] = "sub_uninvited"
    if case == "conflicting_subscription": raw["parent"] = {"subscription_details": {"subscription": "sub_uninvited"}}
    if case == "customer": raw["customer"] = "cus_uninvited"
    if case == "livemode": raw["livemode"] = False
    if case == "outside_window": raw["created"] = int(AT.timestamp())
    rows = [raw, raw] if case == "duplicate" else [raw]
    if case == "bad_cursor": rows, more = [], True
    with pytest.raises(ValueError):
        await daily.finish_page(sessions, job, rows, more, AT + timedelta(seconds=1))
    checkpoint = await state(sessions, binding["id"])
    assert checkpoint.cursor is None and checkpoint.covered_through is None
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(StripeHistoryInvoiceReview)) == 0


@pytest.mark.asyncio
async def test_paused_binding_before_and_after_claim_never_fetches_or_saves(history_api):
    client, sessions, fake = history_api
    binding = await bind(client)
    job = await daily.claim_page(sessions, AT)
    async with sessions() as db:
        (await db.get(StripeHistoryBinding, binding["id"])).status = "paused"
        await db.commit()
    assert not await daily.finish_page(sessions, job, [remote_invoice()], False, AT + timedelta(seconds=1))
    calls = len(fake.calls)
    assert (await daily.run_batch(sessions=sessions, reader=fake, clock=Clock()))["processed_pages"] == 0
    assert len(fake.calls) == calls
    assert (await state(sessions, binding["id"])).covered_through is None


@pytest.mark.asyncio
async def test_old_unpaid_invoice_later_paid_without_webhook_is_rechecked(history_api):
    client, sessions, fake = history_api
    binding = await bind(client)
    original = await snapshot(sessions)
    fake.invoice_rows["in_history100"]["status"] = "open"
    fake.invoice_rows["in_history100"]["paid"] = False
    await daily.run_batch(sessions=sessions, reader=fake, clock=Clock())
    async with sessions() as db:
        review = await db.scalar(select(StripeHistoryInvoiceReview))
        first_id = review.id
        assert review.status == "exception"
    fake.invoice_rows["in_history100"] = remote_invoice()
    # Six months later still revisit the old created date, not just a lookback.
    future = Clock(datetime(2027, 4, 20, 1, tzinfo=timezone.utc))
    for _ in range(4):
        await daily.run_batch(sessions=sessions, reader=fake, clock=future)
    async with sessions() as db:
        review = await db.scalar(select(StripeHistoryInvoiceReview))
        assert review.id == first_id and review.status == "pending_review"
        assert await db.scalar(select(func.count()).select_from(StripeHistoryPosting)) == 0
    assert await snapshot(sessions) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["create_payment", "link_existing"])
async def test_already_posted_evidence_change_reminds_without_regression_or_new_payment(history_api, monkeypatch, action):
    client, sessions, fake = history_api
    binding = await bind(client)
    payment_id = await manual_payment(sessions) if action == "link_existing" else None
    result = await sync(client, binding)
    review_id = result["items"][0]["id"]
    detail = (await client.get(f"{API}/invoice-reviews/{review_id}", headers=headers(1))).json()["review"]
    posted = await client.post(f"{API}/invoice-reviews/{review_id}/confirm", headers=headers(1), json=confirmation(
        detail["revision"], action=action, existing_payment_id=payment_id))
    assert posted.status_code == 200, posted.text
    original = await snapshot(sessions)
    async with sessions() as db:
        post_fingerprint = (await db.get(StripeHistoryPosting, review_id)).fingerprint
    await daily.run_batch(sessions=sessions, reader=fake, clock=Clock())
    monkeypatch.setattr(daily, "now", lambda: AT)
    assert (await client.get(API + "/reminders", headers=headers(1))).json()["counts"]["total"] == 0
    fake.invoice_rows["in_history100"]["payment_intent"]["latest_charge"]["disputed"] = True
    await daily.run_batch(sessions=sessions, reader=fake, clock=Clock(AT + timedelta(days=1)))
    response = await client.get(API + "/reminders", headers=headers(1))
    assert response.status_code == 200 and response.json()["counts"] == {"pending_review": 0, "needs_refresh": 0, "exception": 1, "total": 1}
    assert response.json()["items"][0]["title"].startswith("已核账凭据")
    async with sessions() as db:
        assert (await db.get(StripeHistoryInvoiceReview, review_id)).status == ("confirmed" if action == "create_payment" else "linked_existing")
        assert (await db.get(StripeHistoryPosting, review_id)).fingerprint == post_fingerprint
        assert await db.scalar(select(func.count()).select_from(Payments)) == 1
        assert await db.scalar(select(func.count()).select_from(StripeHistoryPosting)) == 1
    assert await snapshot(sessions) == original


@pytest.mark.asyncio
async def test_owner_reminders_are_readonly_and_explicit_never_disabled_and_retry_status(history_api, monkeypatch):
    client, sessions, fake = history_api
    monkeypatch.setattr(daily, "now", lambda: AT)
    for actor in (11, 12, 13, 14, 15, 16, 17):
        assert (await client.get(API + "/reminders", headers=headers(actor))).status_code == 403
    before = await snapshot(sessions)
    initial = await client.get(API + "/reminders", headers=headers(1))
    assert initial.status_code == 200 and initial.json()["daily_scan"]["last_run_status"] == "no_bindings"
    assert "no-store" in initial.headers["cache-control"]
    binding = await bind(client)
    waiting = (await client.get(API + "/reminders", headers=headers(1))).json()
    assert waiting["daily_scan"]["last_run_status"] == "never" and waiting["daily_scan"]["last_discovered_reviews"] is None
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(StripeHistoryScanState)) == 0
    monkeypatch.setenv("STRIPE_HISTORY_DAILY_SCAN_ENABLED", "false")
    assert daily.start_daily_scan() is None
    assert (await client.get(API + "/reminders", headers=headers(1))).json()["daily_scan"]["last_run_status"] == "disabled"
    monkeypatch.setenv("STRIPE_HISTORY_DAILY_SCAN_ENABLED", "true")
    await daily.run_batch(sessions=sessions, reader=fake, clock=Clock())
    complete = (await client.get(API + "/reminders", headers=headers(1))).json()
    assert complete["daily_scan"]["last_run_status"] == "completed" and complete["daily_scan"]["covered_bindings"] == 1
    assert complete["daily_scan"]["last_discovered_reviews"] == 1
    assert complete["counts"]["total"] == complete["counts"]["pending_review"] == 1
    assert complete["items"][0]["href"].endswith("&stripe_review=1")
    assert await snapshot(sessions) == before


@pytest.mark.asyncio
async def test_exception_reminders_are_not_hidden_by_twenty_newer_pending_records(history_api, monkeypatch):
    client, sessions, _ = history_api
    binding = await bind(client)
    monkeypatch.setattr(daily, "now", lambda: AT)
    async with sessions() as db:
        for index in range(25):
            is_exception = index == 0
            db.add(StripeHistoryInvoiceReview(account_id=daily.STRIPE_ACCOUNT_ID, livemode=True,
                binding_id=binding["id"], stripe_invoice_id=f"in_reminder{index}",
                status="exception" if is_exception else "pending_review", snapshot={"issues": ["refund_or_dispute"] if is_exception else []},
                fingerprint=f"synthetic{index}", revision=1, needs_refresh=False, observed_at=AT + timedelta(seconds=index)))
        await db.commit()
    before = await snapshot(sessions)
    value = (await client.get(API + "/reminders", headers=headers(1))).json()
    assert value["counts"] == {"pending_review": 24, "needs_refresh": 0, "exception": 1, "total": 25}
    assert len(value["items"]) == 20 and all(item["kind"] == "pending_review" for item in value["items"])
    assert len(value["exception_items"]) == 1 and value["exception_items"][0]["id"] == 1
    assert value["exception_items"][0]["href"].endswith("&stripe_review=1")
    assert not value["exception_has_more"] and await snapshot(sessions) == before


@pytest.mark.asyncio
async def test_batch_deadline_cancels_slow_provider_and_restart_can_resume(history_api, monkeypatch):
    client, sessions, fake = history_api
    binding = await bind(client)
    monkeypatch.setattr(daily, "BATCH_SECONDS", .03)
    original = fake.invoices
    async def slow(*args):
        await asyncio.sleep(10)
    fake.invoices = slow
    result = await daily.run_batch(sessions=sessions, reader=fake, clock=Clock())
    assert result["deferred"] and result["processed_pages"] == 0
    checkpoint = await state(sessions, binding["id"])
    assert checkpoint.covered_through is None and checkpoint.lease_token
    fake.invoices = original
    monkeypatch.setattr(daily, "BATCH_SECONDS", 60)
    await daily.run_batch(sessions=sessions, reader=fake, clock=Clock(AT + timedelta(seconds=91)))
    assert (await state(sessions, binding["id"])).completed_for == "2026-10-19"


@pytest.mark.asyncio
async def test_webhook_manual_sync_and_daily_page_converge_to_one_draft(history_api, monkeypatch):
    from backend.tests.test_sales_deal_payments import SECRET, deliver
    from backend.tests.test_service_follow_through import lifecycle
    client, sessions, _ = history_api
    binding = await bind(client)
    original = await snapshot(sessions)
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET", SECRET)
    job = await daily.claim_page(sessions, AT)
    result, manual, webhook = await asyncio.gather(daily.finish_page(sessions, job, [remote_invoice()], False, AT + timedelta(seconds=1)),
        sync(client, binding), deliver(client, lifecycle("invoice.paid", sub="sub_history100", identity="in_history100", created=int(AT.timestamp()))))
    assert result and manual["items"][0]["id"] and webhook.status_code == 200
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(StripeHistoryInvoiceReview)) == 1
        assert await db.scalar(select(func.count()).select_from(StripeHistoryPosting)) == 0
    assert await snapshot(sessions) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("python310", [False, True])
async def test_started_worker_catches_up_without_owner_page_and_stops_cleanly(history_api, monkeypatch, python310):
    client, sessions, fake = history_api
    binding = await bind(client)
    original = await snapshot(sessions)
    monkeypatch.setattr(daily, "sessions_factory", lambda: sessions)
    monkeypatch.setattr(daily, "now", lambda: AT)
    monkeypatch.setattr(daily, "STARTUP_DELAY_SECONDS", 0)
    monkeypatch.setenv("STRIPE_HISTORY_DAILY_SCAN_ENABLED", "true")
    if python310:
        monkeypatch.delattr(asyncio, "timeout", raising=False)
    done = asyncio.Event()
    real_finish = daily.finish_page
    async def finished(*args):
        result = await real_finish(*args)
        done.set()
        return result
    monkeypatch.setattr(daily, "finish_page", finished)
    task = daily.start_daily_scan()
    assert task and task.get_name() == "stripe-history-daily-scan"
    await asyncio.wait_for(done.wait(), timeout=2)
    await daily.stop_daily_scan(task)
    assert task.cancelled() and (await state(sessions, binding["id"])).completed_for == "2026-10-19"
    assert await snapshot(sessions) == original


def test_migration_is_one_empty_additive_table_and_preserves_existing_rows(tmp_path):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE stripe_history_bindings(id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE payments(id INTEGER PRIMARY KEY, amount INTEGER)"))
        connection.execute(text("INSERT INTO payments VALUES(1,198)"))
        old = connection.execute(text("SELECT type,name,sql FROM sqlite_master ORDER BY name")).all()
        migration = Path(__file__).resolve().parents[1] / "alembic/versions/e2b6c0f8a345_stripe_history_daily_scan.py"
        scope = {"__name__": "_isolated_migration"}
        exec(compile(migration.read_text(), str(migration), "exec"), scope)
        assert scope["down_revision"] == "d1a5b9e7f234"
        scope["op"] = Operations(MigrationContext.configure(connection))
        scope["upgrade"]()
        assert connection.execute(text("SELECT count(*) FROM stripe_history_scan_states")).scalar() == 0
        assert connection.execute(text("SELECT * FROM payments")).all() == [(1, 198)]
        assert connection.execute(text("SELECT type,name,sql FROM sqlite_master WHERE name<>'stripe_history_scan_states' ORDER BY name")).all() == old
        assert inspect(connection).get_table_names() == ["payments", "stripe_history_bindings", "stripe_history_scan_states"]
        assert [row["name"] for row in inspect(connection).get_columns("stripe_history_scan_states")] == list(StripeHistoryScanState.__table__.columns.keys())
    engine.dispose()
