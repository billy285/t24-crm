import asyncio
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.database import Base
from models.employees import Employees
from models.sales_call_activities import SalesCallActivities
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_leads import SalesLeads
from models.sales_lead_assignment_logs import SalesLeadAssignmentLogs
from models.ringcentral_call_records import RingCentralCallRecords
from routers.sales_leads import RecoveryReassignRequest, SalesCallResultCreate, reassign_sales_lead, record_daily_call_result
from schemas.auth import UserResponse
from services.sales_lead_cycle import run_sales_lead_cycle
from services.sales_workflow_locks import SALES_WORKFLOW_ADVISORY_KEY, lock_sales_workflow

ADMIN = UserResponse(id="1", email="admin@example.com", name="Admin", role="admin")
SALES = UserResponse(id="11", email="sales@example.com", name="Sales A", role="sales")


@pytest_asyncio.fixture
async def file_sales_db(tmp_path):
    # WAL permits concurrent reads, so these separate physical connections
    # prove that the write guard serializes business reads as well as writes.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sales-fixture.db'}", poolclass=NullPool, connect_args={"timeout": 0.08})
    async with engine.connect() as connection:
        await connection.execute(text("PRAGMA journal_mode=WAL"))
        await connection.commit()
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[
            Employees.__table__, SalesLeads.__table__, SalesCallActivities.__table__,
            SalesDailyDialTasks.__table__, SalesLeadAssignmentLogs.__table__, RingCentralCallRecords.__table__,
        ]))
        await connection.execute(text("CREATE TABLE IF NOT EXISTS app_settings (config_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TIMESTAMP)"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    async with maker() as db:
        db.add_all([
            Employees(id=1, user_id="1", name="Admin", role="admin", status="active"),
            Employees(id=11, user_id="11", name="Sales A", role="sales", status="active"),
            Employees(id=12, user_id="12", name="Sales B", role="sales", status="active"),
            SalesLeads(id=1, business_name="Pending fixture", phone="+12025550123", country="US", status="new", assigned_sales_id=11, assigned_sales_name="Sales A"),
            SalesLeads(id=2, business_name="Completed history", phone="+12025550124", country="US", status="contacted", assigned_sales_id=11, assigned_sales_name="Sales A", notes="Historical notes"),
            SalesCallActivities(id=101, lead_id=2, sales_employee_id=11, sales_employee_name="Sales A", outcome="callback", notes="Historical evidence", called_at=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)),
            SalesDailyDialTasks(id=1, lead_id=1, sales_employee_id=11, task_date=today, status="pending"),
            SalesDailyDialTasks(id=2, lead_id=2, sales_employee_id=11, task_date=today, status="completed", completed_activity_id=101, completed_at=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)),
        ])
        await db.commit()
    yield maker
    await engine.dispose()


async def historical_snapshot(db):
    task = (await db.execute(text("SELECT * FROM sales_daily_dial_tasks WHERE id=2"))).mappings().one()
    activity = (await db.execute(text("SELECT * FROM sales_call_activities WHERE id=101"))).mappings().one()
    return dict(task), dict(activity)


@pytest.mark.asyncio
async def test_sqlite_lock_itself_does_not_update_raw_fields_or_timestamps(file_sales_db):
    async with file_sales_db() as db:
        before = [dict(row) for row in (await db.execute(text("SELECT * FROM sales_leads ORDER BY id"))).mappings()]
        history = await historical_snapshot(db)
        await db.rollback()
        await lock_sales_workflow(db)
        await db.commit()
        after = [dict(row) for row in (await db.execute(text("SELECT * FROM sales_leads ORDER BY id"))).mappings()]
        assert after == before
        assert await historical_snapshot(db) == history


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["assignment", "result"])
async def test_two_connection_transfer_and_result_are_serialized_without_history_rewrite(file_sales_db, first):
    held, release = asyncio.Event(), asyncio.Event()
    async with file_sales_db() as db:
        original_history = await historical_snapshot(db)

    async def mutate(operation, pause=False):
        async with file_sales_db() as db:
            try:
                # This is the endpoint integration contract: one transaction
                # starts with the lock, then rechecks current business state.
                await lock_sales_workflow(db, lead_ids=[1], employee_ids=[12, 11])
            except HTTPException:
                assert not db.in_transaction()
                raise
            if pause:
                held.set()
                await asyncio.wait_for(release.wait(), timeout=5)
            if operation == "assignment":
                return await reassign_sales_lead(1, RecoveryReassignRequest(assigned_sales_id=12, reason="Fixture transfer", confirm_protected_transfer=True), ADMIN, db)
            return await record_daily_call_result(1, SalesCallResultCreate(outcome="callback", notes="Fixture result", next_follow_up_at=datetime.now(timezone.utc) + timedelta(days=1)), SALES, db)

    second = "result" if first == "assignment" else "assignment"
    writer = asyncio.create_task(mutate(first, pause=True))
    await asyncio.wait_for(held.wait(), timeout=5)
    try:
        with pytest.raises(HTTPException) as conflict:
            await mutate(second)
        assert conflict.value.status_code == 409
        assert "尚未写入" in conflict.value.detail
    finally:
        release.set()
        await asyncio.wait_for(writer, timeout=5)

    if first == "assignment":
        # The losing result request must reload the cancelled task after retry,
        # rather than attribute a new call to the original salesperson.
        with pytest.raises(HTTPException) as cancelled:
            await mutate("result")
        assert cancelled.value.status_code == 400
        assert "转交" in cancelled.value.detail
    else:
        await mutate("assignment")

    async with file_sales_db() as db:
        assert await historical_snapshot(db) == original_history
        task = await db.get(SalesDailyDialTasks, 1)
        lead = await db.get(SalesLeads, 1)
        activities = (await db.scalars(select(SalesCallActivities).where(SalesCallActivities.lead_id == 1))).all()
        assert lead.assigned_sales_id == 12
        assert task.sales_employee_id == 11
        if first == "assignment":
            assert task.status == "cancelled"
            assert activities == []
            target = (await db.scalars(select(SalesDailyDialTasks).where(SalesDailyDialTasks.lead_id == 1, SalesDailyDialTasks.sales_employee_id == 12))).one()
            assert target.status == "pending"
        else:
            assert task.status == "completed"
            assert len(activities) == 1
            assert activities[0].sales_employee_id == 11
            assert task.completed_activity_id == activities[0].id


@pytest.mark.asyncio
async def test_direct_background_cycle_locks_before_reads_and_transfer_retries_without_partial_write(file_sales_db, monkeypatch):
    now = datetime.now(timezone.utc)
    snapshot_tables = ["sales_leads", "sales_daily_dial_tasks", "sales_call_activities", "sales_lead_assignment_logs"]

    async def workflow_snapshot(db):
        return {
            table: [dict(row) for row in (await db.execute(text(f"SELECT * FROM {table} ORDER BY id"))).mappings()]
            for table in snapshot_tables
        }

    async with file_sales_db() as db:
        lead = await db.get(SalesLeads, 1)
        lead.assigned_at = now - timedelta(hours=49)
        await db.commit()
        original_history = await historical_snapshot(db)
        original_workflow = await workflow_snapshot(db)

    held, release = asyncio.Event(), asyncio.Event()
    async with file_sales_db() as background_db, file_sales_db() as transfer_db:
        statements = []
        execute = background_db.execute

        async def execute_and_pause(statement, *args, **kwargs):
            sql = str(statement)
            statements.append(sql)
            result = await execute(statement, *args, **kwargs)
            if sql == "UPDATE sales_leads SET id = id WHERE 0":
                held.set()
                await asyncio.wait_for(release.wait(), timeout=5)
            return result

        monkeypatch.setattr(background_db, "execute", execute_and_pause)
        # Invoke the background service directly: no router and no test-side
        # lock call. Its own first statement must acquire the real write lock.
        background = asyncio.create_task(run_sales_lead_cycle(background_db, now=now))
        try:
            await asyncio.wait_for(held.wait(), timeout=5)
            assert statements == ["UPDATE sales_leads SET id = id WHERE 0"]
            with pytest.raises(HTTPException) as conflict:
                await reassign_sales_lead(1, RecoveryReassignRequest(assigned_sales_id=12, reason="Retry after background cycle", confirm_protected_transfer=True), ADMIN, transfer_db)
            assert conflict.value.status_code == 409
            assert not transfer_db.in_transaction()
            # WAL permits this separate connection to inspect the committed
            # state while the background transaction still owns the guard.
            assert await workflow_snapshot(transfer_db) == original_workflow
            await transfer_db.rollback()
        finally:
            release.set()
            cycle_result = await asyncio.wait_for(background, timeout=5)

        assert cycle_result["released_unstarted"] == 1
        await reassign_sales_lead(1, RecoveryReassignRequest(assigned_sales_id=12, reason="Retry after background cycle", confirm_protected_transfer=True), ADMIN, transfer_db)

    async with file_sales_db() as db:
        assert await historical_snapshot(db) == original_history
        lead = await db.get(SalesLeads, 1)
        assert lead.assigned_sales_id == 12
        assert lead.last_assigned_sales_id == 11
        assert lead.rotation_count == 1
        old_task = await db.get(SalesDailyDialTasks, 1)
        assert old_task.status == "cancelled"
        assert old_task.sales_employee_id == 11
        target = (await db.scalars(select(SalesDailyDialTasks).where(SalesDailyDialTasks.lead_id == 1, SalesDailyDialTasks.sales_employee_id == 12))).one()
        assert target.status == "pending"
        assert (await db.scalars(select(SalesCallActivities).where(SalesCallActivities.lead_id == 1))).all() == []
        logs = (await db.scalars(select(SalesLeadAssignmentLogs).where(SalesLeadAssignmentLogs.lead_id == 1).order_by(SalesLeadAssignmentLogs.id))).all()
        assert [log.action for log in logs] == ["auto_reclaimed_unstarted", "reassigned"]
        assert logs[0].from_sales_employee_id == 11
        assert logs[1].from_sales_employee_id is None
        assert logs[1].to_sales_employee_id == 12


@pytest.mark.asyncio
async def test_postgres_lock_order_is_stable_for_reversed_input_ids():
    db = SimpleNamespace(no_autoflush=nullcontext(), get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")), execute=AsyncMock())
    await lock_sales_workflow(db, lead_ids=[2, 1, 2], employee_ids=[12, 11, 12])
    statements = [call.args[0].compile(dialect=postgresql.dialect()) for call in db.execute.await_args_list]
    assert len(statements) == 3
    assert "SELECT pg_advisory_xact_lock(" in str(statements[0])
    assert db.execute.await_args_list[0].args[1] == {"namespace_key": SALES_WORKFLOW_ADVISORY_KEY}
    assert "FROM employees" in str(statements[1])
    assert "ORDER BY employees.id FOR UPDATE" in str(statements[1])
    assert statements[1].params["id_1"] == [11, 12]
    assert "FROM sales_leads" in str(statements[2])
    assert "ORDER BY sales_leads.id FOR UPDATE" in str(statements[2])
    assert statements[2].params["id_1"] == [1, 2]


@pytest.mark.asyncio
async def test_postgres_empty_ids_and_different_sales_share_same_transaction_lock():
    calls = []
    for ids in [(), (11,), (12,)]:
        db = SimpleNamespace(no_autoflush=nullcontext(), get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")), execute=AsyncMock())
        await lock_sales_workflow(db, employee_ids=ids)
        first = db.execute.await_args_list[0]
        calls.append((str(first.args[0].compile(dialect=postgresql.dialect())), first.args[1]))
        assert db.execute.await_count == (2 if ids else 1)
    assert calls[0] == calls[1] == calls[2]
    assert calls[0][1] == {"namespace_key": SALES_WORKFLOW_ADVISORY_KEY}
    assert 0 < SALES_WORKFLOW_ADVISORY_KEY < 2**63


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_step", ["advisory", "employee", "lead"])
async def test_postgres_deadlock_is_rollback_and_actionable_conflict(failed_step):
    class Deadlock(Exception):
        sqlstate = "40P01"
    step = {"advisory": 0, "employee": 1, "lead": 2}[failed_step]
    db = SimpleNamespace(no_autoflush=nullcontext(), get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")), execute=AsyncMock(side_effect=[None] * step + [OperationalError("locked query", {}, Deadlock("deadlock"))]), rollback=AsyncMock())
    with pytest.raises(HTTPException) as conflict:
        await lock_sales_workflow(db, lead_ids=[1], employee_ids=[11])
    assert conflict.value.status_code == 409
    db.rollback.assert_awaited_once()
