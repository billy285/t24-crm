"""Dial snapshots must survive enrichment without attaching calls to another lead."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import Base
from models.employees import Employees
from models.ringcentral_call_records import RingCentralCallRecords
from models.ringcentral_connections import RingCentralConnections
from models.sales_call_activities import SalesCallActivities
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_lead_enrichments import SalesDialAttempt
from models.sales_leads import SalesLeads
from services.ringcentral_sync import _linked_activity, _match_lead_and_task, upsert_call_log_record


CALL_TIME = datetime(2026, 10, 14, 2, 0, tzinfo=timezone.utc)
OLD_PHONE = "+12025550123"
NEW_PHONE = "+12125550144"


@asynccontextmanager
async def database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [Employees.__table__, RingCentralConnections.__table__, SalesLeads.__table__,
              SalesDailyDialTasks.__table__, SalesDialAttempt.__table__, SalesCallActivities.__table__, RingCentralCallRecords.__table__]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            yield db
    finally:
        await engine.dispose()


async def add_lead(db, *, phone=NEW_PHONE, owner=11, name="Enriched salon"):
    lead = SalesLeads(business_name=name, phone=phone, country="US", assigned_sales_id=owner)
    db.add(lead)
    await db.flush()
    return lead


async def add_task(db, lead, *, phone=OLD_PHONE, employee=11, dial_at=CALL_TIME - timedelta(minutes=1)):
    task = SalesDailyDialTasks(sales_employee_id=employee, lead_id=lead.id,
                              task_date=dial_at.date(), dial_started_at=dial_at, dial_phone=phone)
    db.add(task)
    await db.flush()
    return task


async def add_activity(db, lead, *, phone=OLD_PHONE, employee=11, called_at=CALL_TIME + timedelta(minutes=2)):
    activity = SalesCallActivities(lead_id=lead.id, sales_employee_id=employee,
                                   outcome="callback", dial_phone=phone, called_at=called_at)
    db.add(activity)
    await db.flush()
    return activity


async def add_attempt(db, task, *, phone=OLD_PHONE, at=CALL_TIME - timedelta(minutes=1)):
    attempt = SalesDialAttempt(task_id=task.id, lead_id=task.lead_id,
                              sales_employee_id=task.sales_employee_id, dial_phone=phone, started_at=at)
    db.add(attempt)
    await db.flush()
    return attempt


@pytest.mark.asyncio
async def test_store_then_mobile_dials_keep_both_original_attempts_after_number_change():
    async with database() as db:
        lead = await add_lead(db)
        task = await add_task(db, lead, phone=NEW_PHONE)
        await add_attempt(db, task, phone=OLD_PHONE)
        await add_attempt(db, task, phone=NEW_PHONE, at=CALL_TIME + timedelta(minutes=2))
        for phone, at in [(OLD_PHONE, CALL_TIME), (NEW_PHONE, CALL_TIME + timedelta(minutes=3))]:
            match, matched_task = await _match_lead_and_task(db, 11, phone, at)
            assert (match.id, matched_task.id) == (lead.id, task.id)


@pytest.mark.asyncio
async def test_repeated_same_number_attempts_are_one_task_context():
    async with database() as db:
        lead = await add_lead(db)
        task = await add_task(db, lead)
        await add_attempt(db, task)
        await add_attempt(db, task, at=CALL_TIME - timedelta(minutes=2))
        match, matched_task = await _match_lead_and_task(db, 11, OLD_PHONE, CALL_TIME)
        assert (match.id, matched_task.id) == (lead.id, task.id)


@pytest.mark.asyncio
async def test_attempt_contexts_remain_ambiguous_across_customers():
    async with database() as db:
        for name in ["First", "Second"]:
            task = await add_task(db, await add_lead(db, name=name))
            await add_attempt(db, task)
        assert await _match_lead_and_task(db, 11, OLD_PHONE, CALL_TIME) == (None, None)


@pytest.mark.asyncio
async def test_attempt_prevents_using_overwritten_task_snapshot_as_new_dial_evidence():
    async with database() as db:
        lead = await add_lead(db)
        task = await add_task(db, lead, phone=NEW_PHONE)
        await add_attempt(db, task, phone=OLD_PHONE)
        match, matched_task = await _match_lead_and_task(db, 11, NEW_PHONE, CALL_TIME)
        assert match.id == lead.id and matched_task is None


@pytest.mark.asyncio
async def test_snapshot_activity_for_mobile_is_not_overwritten_by_earlier_store_call():
    async with database() as db:
        lead = await add_lead(db)
        task = await add_task(db, lead, phone=NEW_PHONE)
        activity = await add_activity(db, lead, phone=NEW_PHONE)
        task.completed_activity_id = activity.id
        assert await _linked_activity(db, 11, lead.id, task,
                                      remote_phone=OLD_PHONE, call_started_at=CALL_TIME) is None


@pytest.mark.asyncio
async def test_new_followup_attempt_does_not_overwrite_completed_task_original_activity():
    async with database() as db:
        lead = await add_lead(db)
        task = await add_task(db, lead, phone=NEW_PHONE)
        original_attempt = await add_attempt(db, task, at=CALL_TIME - timedelta(hours=1))
        original = await add_activity(db, lead, called_at=CALL_TIME - timedelta(minutes=55))
        original.dial_attempt_id = original_attempt.id
        task.completed_activity_id = original.id
        task.status = "completed"
        new_attempt = await add_attempt(db, task, phone=NEW_PHONE)
        # Provider callback arriving before the follow-up is saved stays
        # unlinked; it must not mutate the completed daily result.
        assert await _linked_activity(db, 11, lead.id, task,
                                      remote_phone=NEW_PHONE, call_started_at=CALL_TIME) is None
        followup = await add_activity(db, lead, phone=NEW_PHONE)
        followup.dial_attempt_id = new_attempt.id
        await db.flush()
        linked = await _linked_activity(db, 11, lead.id, task,
                                        remote_phone=NEW_PHONE, call_started_at=CALL_TIME)
        assert linked.id == followup.id
        assert original.ringcentral_call_id is None


@pytest.mark.asyncio
async def test_same_number_followup_attempt_ambiguity_never_falls_back_to_original_activity():
    async with database() as db:
        lead = await add_lead(db, phone=OLD_PHONE)
        task = await add_task(db, lead)
        original_attempt = await add_attempt(db, task, at=CALL_TIME - timedelta(hours=1))
        original = await add_activity(db, lead, called_at=CALL_TIME - timedelta(minutes=55))
        original.dial_attempt_id = original_attempt.id
        task.completed_activity_id = original.id
        task.status = "completed"
        latest_attempt = await add_attempt(db, task)
        assert await _linked_activity(db, 11, lead.id, task,
                                      remote_phone=OLD_PHONE, call_started_at=CALL_TIME) is None
        latest = await add_activity(db, lead)
        latest.dial_attempt_id = latest_attempt.id
        await db.flush()
        assert await _linked_activity(db, 11, lead.id, task,
                                      remote_phone=OLD_PHONE, call_started_at=CALL_TIME) is None


@pytest.mark.asyncio
async def test_delayed_provider_log_links_new_attempt_result_not_completed_task_result():
    async with database() as db:
        db.add(Employees(id=11, user_id="11", name="Sales", role="sales", status="active"))
        connection = RingCentralConnections(employee_id=11, access_token_encrypted="test-only", is_active=True)
        db.add(connection)
        lead = await add_lead(db)
        task = await add_task(db, lead, phone=NEW_PHONE)
        original = await add_activity(db, lead, called_at=CALL_TIME - timedelta(hours=1))
        original.call_duration_seconds = 99
        original.ringcentral_call_id = "original-call"
        task.completed_activity_id = original.id
        task.status = "completed"
        attempt = await add_attempt(db, task, phone=NEW_PHONE)
        followup = await add_activity(db, lead, phone=NEW_PHONE)
        followup.dial_attempt_id = attempt.id
        await db.flush()
        record = await upsert_call_log_record(db, connection, {
            "id": "new-followup-call", "direction": "Outbound", "to": {"phoneNumber": NEW_PHONE},
            "startTime": CALL_TIME.isoformat(), "result": "Call connected", "duration": 41,
        })
        assert record.activity_id == followup.id
        assert followup.call_duration_seconds == 41
        assert original.call_duration_seconds == 99 and original.ringcentral_call_id == "original-call"


@pytest.mark.asyncio
async def test_attempt_reference_does_not_allow_cross_employee_or_cross_lead_activity():
    async with database() as db:
        lead = await add_lead(db)
        other = await add_lead(db, owner=12, name="Other sales customer")
        task = await add_task(db, lead)
        attempt = await add_attempt(db, task)
        unrelated = await add_activity(db, other, employee=12)
        unrelated.dial_attempt_id = attempt.id
        task.completed_activity_id = unrelated.id
        await db.flush()
        assert await _linked_activity(db, 11, lead.id, task,
                                      remote_phone=OLD_PHONE, call_started_at=CALL_TIME) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("current_owner", [11, 12, None])
async def test_actual_number_snapshot_survives_enrichment_and_reassignment(current_owner):
    async with database() as db:
        lead = await add_lead(db, owner=current_owner)
        task = await add_task(db, lead)
        await add_attempt(db, task)
        # Another currently owned lead has the old number. Never move the
        # original employee's historical call onto that different lead.
        await add_lead(db, phone=OLD_PHONE, owner=11, name="Another salon")
        match, matched_task = await _match_lead_and_task(db, 11, OLD_PHONE, CALL_TIME)
        assert (match.id, matched_task.id) == (lead.id, task.id)


@pytest.mark.asyncio
async def test_contact_mobile_snapshot_works_without_replacing_store_phone():
    async with database() as db:
        lead = await add_lead(db)
        task = await add_task(db, lead)
        match, matched_task = await _match_lead_and_task(db, 11, OLD_PHONE, CALL_TIME)
        assert match.id == lead.id and matched_task.id == task.id
        assert lead.phone == NEW_PHONE


@pytest.mark.asyncio
async def test_other_employees_snapshot_cannot_attach_to_call():
    async with database() as db:
        lead = await add_lead(db, owner=12)
        await add_task(db, lead, employee=12)
        assert await _match_lead_and_task(db, 11, OLD_PHONE, CALL_TIME) == (None, None)


@pytest.mark.asyncio
async def test_multiple_snapshot_candidates_are_not_resolved_by_latest():
    async with database() as db:
        first = await add_lead(db)
        second = await add_lead(db, name="Second salon")
        await add_task(db, first)
        await add_task(db, second, dial_at=CALL_TIME - timedelta(minutes=2))
        assert await _match_lead_and_task(db, 11, OLD_PHONE, CALL_TIME) == (None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("offset,expected", [(timedelta(hours=-13), False), (timedelta(hours=-12), True),
                                           (timedelta(minutes=5), True), (timedelta(minutes=6), False)])
async def test_snapshot_matching_enforces_original_call_time_window(offset, expected):
    async with database() as db:
        lead = await add_lead(db)
        task = await add_task(db, lead, dial_at=CALL_TIME + offset)
        await add_attempt(db, task, at=CALL_TIME + offset)
        match, matched_task = await _match_lead_and_task(db, 11, OLD_PHONE, CALL_TIME)
        if expected:
            assert (match.id, matched_task.id) == (lead.id, task.id)
        else:
            assert (match, matched_task) == (None, None)


@pytest.mark.asyncio
async def test_legacy_task_matches_current_phone_but_nonempty_snapshot_is_authoritative():
    async with database() as db:
        lead = await add_lead(db, phone=OLD_PHONE)
        task = await add_task(db, lead, phone=None)
        match, matched_task = await _match_lead_and_task(db, 11, OLD_PHONE, CALL_TIME)
        assert (match.id, matched_task.id) == (lead.id, task.id)
        task.dial_phone = NEW_PHONE
        await db.flush()
        match, matched_task = await _match_lead_and_task(db, 11, OLD_PHONE, CALL_TIME)
        assert match.id == lead.id and matched_task is None


@pytest.mark.asyncio
async def test_ambiguous_legacy_tasks_remain_unlinked():
    async with database() as db:
        lead = await add_lead(db, phone=OLD_PHONE)
        # Adjacent-day tasks can both fall within the twelve-hour window.
        boundary = datetime(2026, 10, 14, 0, 30, tzinfo=timezone.utc)
        await add_task(db, lead, phone=None, dial_at=boundary - timedelta(hours=1))
        await add_task(db, lead, phone=None, dial_at=boundary - timedelta(minutes=1))
        assert await _match_lead_and_task(db, 11, OLD_PHONE, boundary) == (None, None)


@pytest.mark.asyncio
async def test_missing_provider_time_cannot_use_historical_snapshot_after_transfer():
    async with database() as db:
        lead = await add_lead(db, owner=12)
        await add_task(db, lead)
        assert await _match_lead_and_task(db, 11, OLD_PHONE, None) == (None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["task_employee", "task_lead", "activity_employee", "activity_lead"])
async def test_completed_activity_requires_exact_employee_and_lead(mismatch):
    async with database() as db:
        lead = await add_lead(db)
        other = await add_lead(db, name="Other salon")
        task = await add_task(db, lead, employee=12 if mismatch == "task_employee" else 11)
        if mismatch == "task_lead":
            task.lead_id = other.id
        activity = await add_activity(db, other if mismatch == "activity_lead" else lead,
                                      employee=12 if mismatch == "activity_employee" else 11)
        task.completed_activity_id = activity.id
        await db.flush()
        assert await _linked_activity(db, 11, lead.id, task,
                                      remote_phone=OLD_PHONE, call_started_at=CALL_TIME) is None


@pytest.mark.asyncio
async def test_followup_requires_unique_matching_number_and_time_not_latest_note():
    async with database() as db:
        lead = await add_lead(db)
        good = await add_activity(db, lead)
        await add_activity(db, lead, phone=NEW_PHONE, called_at=CALL_TIME + timedelta(minutes=3))
        await add_activity(db, lead, called_at=CALL_TIME + timedelta(days=1))
        await add_activity(db, lead, phone=None, called_at=CALL_TIME + timedelta(minutes=4))
        match = await _linked_activity(db, 11, lead.id, None, remote_phone=OLD_PHONE, call_started_at=CALL_TIME)
        assert match.id == good.id
        await add_activity(db, lead, called_at=CALL_TIME + timedelta(minutes=5))
        assert await _linked_activity(db, 11, lead.id, None,
                                      remote_phone=OLD_PHONE, call_started_at=CALL_TIME) is None


@pytest.mark.asyncio
async def test_verified_delayed_call_updates_only_original_completed_activity_after_transfer():
    async with database() as db:
        db.add(Employees(id=11, user_id="11", name="Original sales", role="sales", status="active"))
        connection = RingCentralConnections(employee_id=11, employee_name="Original sales",
                                             access_token_encrypted="test-only", is_active=True)
        db.add(connection)
        lead = await add_lead(db, owner=12)
        task = await add_task(db, lead)
        old_activity = await add_activity(db, lead)
        new_activity = await add_activity(db, lead, phone=NEW_PHONE, employee=12)
        task.status = "transferred"
        task.completed_activity_id = old_activity.id
        await db.flush()
        record = await upsert_call_log_record(db, connection, {
            "id": "delayed-original-call", "direction": "Outbound",
            "from": {"phoneNumber": "+12025550100"}, "to": {"phoneNumber": OLD_PHONE},
            "startTime": CALL_TIME.isoformat(), "result": "Call connected", "duration": 70,
        })
        assert (record.lead_id, record.task_id, record.activity_id) == (lead.id, task.id, old_activity.id)
        assert old_activity.ringcentral_call_id == "delayed-original-call"
        assert old_activity.call_duration_seconds == 70
        assert new_activity.ringcentral_call_id is None
        assert lead.assigned_sales_id == 12 and lead.phone == NEW_PHONE


@pytest.mark.asyncio
async def test_stale_call_without_task_does_not_overwrite_recent_activity():
    async with database() as db:
        db.add(Employees(id=11, user_id="11", name="Sales", role="sales", status="active"))
        connection = RingCentralConnections(employee_id=11, access_token_encrypted="test-only", is_active=True)
        db.add(connection)
        lead = await add_lead(db, phone=OLD_PHONE)
        recent = await add_activity(db, lead, called_at=CALL_TIME + timedelta(days=2))
        record = await upsert_call_log_record(db, connection, {
            "id": "stale-call", "direction": "Outbound", "to": {"phoneNumber": OLD_PHONE},
            "startTime": CALL_TIME.isoformat(), "result": "Call connected", "duration": 70,
        })
        assert record.lead_id == lead.id and record.task_id is None and record.activity_id is None
        assert recent.ringcentral_call_id is None and recent.call_duration_seconds is None
