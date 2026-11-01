"""Central monthly view stays distinct from native publication schedules."""
from datetime import datetime, timezone

import pytest

from services import media_monthly as monthly_service, media_monthly_workflow as workflow_service
from services import schema_readiness
from models.media_monthly import MediaMonthlyProfile as Profile
from models.customers import Customers
from test_media_monthly import monthly, generated
from test_google_business import gbp_env, OWNER, OPS

START = datetime(2026, 11, 1, tzinfo=timezone.utc)
END = datetime(2026, 12, 1, tzinfo=timezone.utc)


def state(**extra):
    return {"status": "prepared", "source_stale": False, "requires_attention": False, "exception_count": 0,
            "pending_owner_confirmation": True, "task_ids": [], "schedule_ids": [], "alerts": [],
            "revision": 3, "snapshot_hash": "b" * 64, "message": "整月已准备，尚未确认公开发布", **extra}


@pytest.mark.asyncio
async def test_prepared_packet_overrides_old_material_gap_without_claiming_publication(monthly, monkeypatch):
    env = monthly; run, _ = await generated(env)
    async with env.sessions() as db:
        profile = await db.get(Profile, run["profile_snapshot"].get("id", 1))
        profile.images = [{**profile.images[0], "image_version_id": "f" * 32}]
        await db.commit()
    async def workflow(db, user, identity):
        assert user.id == OWNER.id and identity == run["id"]
        return state()
    monkeypatch.setattr(workflow_service, "workspace_status", workflow)
    async with env.sessions() as db:
        rows = await monthly_service.workspace_rows(db, OWNER, [20], START, END, "review")
        assert len(rows) == 1 and rows[0]["kind"] == "monthly_run"
        assert rows[0]["status"] == "prepared" and rows[0]["version"] == "b" * 64 and rows[0]["revision"] == 3
        assert rows[0]["review_eligible"] is False and rows[0]["navigation"]["run_id"] == run["id"]
        calendar = await monthly_service.workspace_rows(db, OWNER, [20], START, END, "calendar")
        assert len(calendar) == 12 and all(row["time_basis"] == "proposed_publish" for row in calendar)
    assert env.fake.writes == [] and env.fake.reads == []


@pytest.mark.asyncio
async def test_real_schedule_records_replace_proposed_calendar_but_keep_batch_entry(monthly, monkeypatch):
    env = monthly; run, _ = await generated(env)
    async def workflow(*args): return state(status="scheduled", pending_owner_confirmation=False, schedule_ids=list(range(101, 113)))
    monkeypatch.setattr(workflow_service, "workspace_status", workflow)
    async with env.sessions() as db:
        assert await monthly_service.workspace_rows(db, OWNER, [20], START, END, "calendar") == []
        rows = await monthly_service.workspace_rows(db, OWNER, [20], START, END, "review")
        assert len(rows) == 1 and rows[0]["status"] == "scheduled"
        assert rows[0]["navigation"]["run_id"] == run["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("patch", [{"source_stale": True}, {"exception_count": 1}])
async def test_stale_or_failed_month_requires_attention_without_new_schedule(monthly, monkeypatch, patch):
    env = monthly; await generated(env)
    async def workflow(*args): return state(**patch)
    monkeypatch.setattr(workflow_service, "workspace_status", workflow)
    async with env.sessions() as db:
        rows = await monthly_service.workspace_rows(db, OWNER, [20], START, END, "overview")
        assert rows[0]["status"] == "blocked"
    assert env.fake.writes == []


@pytest.mark.asyncio
async def test_staff_never_reads_monthly_workflow_even_for_invited_customer(monthly, monkeypatch):
    async def forbidden(*args): raise AssertionError("Staff must not reach monthly workflow data")
    monkeypatch.setattr(workflow_service, "workspace_status", forbidden)
    async with monthly.sessions() as db:
        assert await monthly_service.workspace_rows(db, OPS, [20], START, END, "review") == []


@pytest.mark.asyncio
async def test_missing_new_tables_keeps_existing_monthly_preview_available(monthly, monkeypatch):
    env = monthly; await generated(env)
    original = schema_readiness.tables_available
    async def available(db, tables):
        return False if set(tables) == workflow_service.TABLES else await original(db, tables)
    async def forbidden(*args): raise AssertionError("Workflow is not migrated")
    monkeypatch.setattr(schema_readiness, "tables_available", available)
    monkeypatch.setattr(workflow_service, "workspace_status", forbidden)
    async with env.sessions() as db:
        rows = await monthly_service.workspace_rows(db, OWNER, [20], START, END, "calendar")
        assert len(rows) == 12 and all(row["status"] == "generated" for row in rows)


@pytest.mark.asyncio
async def test_owner_can_find_stopped_customer_monthly_exceptions_without_reopening_cooperation(monthly, monkeypatch):
    env = monthly; await generated(env)
    async with env.sessions() as db:
        customer = await db.get(Customers, 20); customer.status = "lost"; await db.commit()
    async def workflow(*args): return state(source_stale=True, exception_count=1)
    monkeypatch.setattr(workflow_service, "workspace_status", workflow)
    async with env.sessions() as db:
        rows = await monthly_service.workspace_rows(db, OWNER, [20], START, END, "review")
        assert len(rows) == 1 and rows[0]["status"] == "blocked"
        assert (await db.get(Customers, 20)).status == "lost"
    assert env.fake.writes == []
