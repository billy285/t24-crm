"""Synthetic automatic drafts: no live AI, credentials or publication calls."""
import asyncio
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import create_engine, func, inspect, select, text
from core.database import get_db
from dependencies.auth import get_current_user
from models.customer_menu_items import Customer_menu_items as Menu
from models.customers import Customers
from models.employees import Employees
from models.google_business import GoogleBusinessBinding as Binding, GoogleBusinessAction as Action, GoogleBusinessSchedule as Schedule
from models.media_monthly import MediaMonthlyRun as Run
from models.media_monthly_automation import MediaMonthlyAutomationPolicy as Policy, MediaMonthlyAutomationOccurrence as Occurrence, MediaMonthlyAutomationRequest as Receipt
from models.media_operations import MediaOperationTask as Task
from routers.media_monthly_automation import router
from services import media_monthly_automation as service
from test_google_business import gbp_env, OWNER, OPS, ADMIN, SECOND_OWNER, actors
from test_media_monthly import monthly, configured, profile
from test_media_monthly_meta import meta_pipeline
from test_meta_operations import ops_env
from test_meta_business import meta_env

PREFIX = "/api/v1/media-monthly"
AT = datetime(2026, 11, 24, 16, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def automation(monthly, monkeypatch):
    env = monthly; env.user = OWNER
    await configured(env)
    async with env.sessions() as db:
        binding = await db.get(Binding, 2); binding.connection_id = 1; binding.lifecycle = "active"
        await db.commit()
    monkeypatch.setattr(service, "now", lambda: AT)
    monkeypatch.setenv("T24_MEDIA_MONTHLY_AUTOPREP_ENABLED", "true")
    app = FastAPI(); app.include_router(router)
    async def database():
        async with env.sessions() as db: yield db
    async def actor(): return env.user
    app.dependency_overrides[get_db] = database; app.dependency_overrides[get_current_user] = actor
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://synthetic.test") as client:
        env.auto_client = client
        yield env


async def read(env, platform="google_business"):
    response = await env.auto_client.get(PREFIX + "/customers/20/automation", params={"platform": platform})
    assert response.status_code == 200, response.text
    return response.json()


async def enable(env, platform="google_business", **updates):
    state = await read(env, platform)
    body = {"request_id": str(uuid4()), "expected_revision": state["policy"]["revision"] if state["policy"] else 0,
        "enabled": True, "lead_days": 7, "local_time": "09:00", "source_signature": state["source_signature"],
        "runtime_fingerprint": state["runtime"]["fingerprint"], "confirmed": True, "notice_version": service.NOTICE_VERSION, **updates}
    response = await env.auto_client.put(PREFIX + "/customers/20/automation", params={"platform": platform}, json=body)
    return response, body


@pytest.mark.asyncio
async def test_defaults_are_off_and_read_is_private(automation, monkeypatch):
    env = automation; monkeypatch.delenv("T24_MEDIA_MONTHLY_AUTOPREP_ENABLED")
    data = await read(env)
    assert data["policy"] is None and not data["worker"]["enabled"] and not data["automatic_publish"]
    assert data["eligibility"]["can_enable"] and data["next_target_month"] == "2026-12"
    assert data["timezone"] == "America/Chicago"
    assert data["next_run_at"] == "2026-11-24T15:00:00+00:00"
    assert "SECRET" not in json.dumps(data)
    assert await service.run_tick(sessions=env.sessions) == {"stage": "disabled", "processed": 0}
    assert not env.monthly_state.calls


@pytest.mark.asyncio
async def test_policy_consent_pin_and_immutable_recovery(automation):
    env = automation
    response, body = await enable(env)
    assert response.status_code == 200, response.text
    data = response.json(); assert data["policy"]["revision"] == 1 and data["policy"]["enabled"]
    assert data["receipt_request_id"] == body["request_id"]
    repeat = await env.auto_client.put(PREFIX + "/customers/20/automation", json=body)
    assert repeat.json() == data
    changed = await env.auto_client.put(PREFIX + "/customers/20/automation", json={**body, "lead_days": 8})
    assert changed.status_code == 409
    result = await env.auto_client.get(PREFIX + "/automation/requests/" + body["request_id"])
    assert result.json()["result"]["policy"]["revision"] == 1
    assert not env.monthly_state.calls


@pytest.mark.parametrize("change", [{"confirmed": False}, {"source_signature": "0"*64}, {"runtime_fingerprint": "0"*64}])
@pytest.mark.asyncio
async def test_cannot_enable_without_exact_confirmation(automation, change):
    response, _ = await enable(automation, **change)
    assert response.status_code == 409
    assert not automation.monthly_state.calls


@pytest.mark.parametrize("change", [{"lead_days": 2}, {"lead_days": 15}, {"local_time": "08:00"}, {"enabled": 1}, {"extra": "ignored"}])
@pytest.mark.asyncio
async def test_strict_policy_input(automation, change):
    response, _ = await enable(automation, **change)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_nonowners_cannot_read_write_overview_or_recover(automation):
    env = automation; response, body = await enable(env); assert response.status_code == 200
    for actor in actors():
        if actor.role == "super_admin": continue
        env.user = actor
        for path in ["/customers/20/automation", "/automation/overview", "/automation/requests/"+body["request_id"]]:
            assert (await env.auto_client.get(PREFIX+path)).status_code == 403
        assert (await env.auto_client.put(PREFIX+"/customers/20/automation", json=body)).status_code == 403
    env.user = SECOND_OWNER
    assert (await env.auto_client.get(PREFIX+"/automation/requests/"+body["request_id"])).status_code == 404
    data = (await env.auto_client.get(PREFIX+"/automation/overview")).json()
    assert data["counts"]["policies"] == 0 and not data["recent_jobs"]


@pytest.mark.asyncio
async def test_worker_reserves_before_single_ai_call_and_never_publishes(automation, monkeypatch):
    env = automation; response, _ = await enable(env); assert response.status_code == 200
    from services import media_monthly as monthly_service
    original = monthly_service.call_ai
    async def checked(runtime, snapshot):
        async with env.sessions() as db:
            job = await db.scalar(select(Occurrence).where(Occurrence.status == "running"))
            assert job is not None and job.ai_attempted_at is not None
            run = await db.scalar(select(Run).where(Run.request_id == job.request_id))
            assert run is not None and run.status == "generating"
        return await original(runtime, snapshot)
    monkeypatch.setattr(monthly_service, "call_ai", checked)
    async with env.sessions() as db:
        canary = (await db.execute(text("SELECT * FROM financial_canary"))).all()
        settings = (await db.execute(text("SELECT * FROM app_settings"))).all()
        tasks = await db.scalar(select(func.count(Task.id)))
    assert (await service.run_tick(sessions=env.sessions))["processed"] == 1
    assert len(env.monthly_state.calls) == 1
    assert (await service.run_tick(sessions=env.sessions))["processed"] == 0
    data = await read(env)
    assert data["latest_job"]["status"] == "generated" and data["latest_job"]["run_id"]
    assert data["latest_job"]["month"] == "2026-12"
    async with env.sessions() as db:
        assert (await db.execute(text("SELECT * FROM financial_canary"))).all() == canary
        assert (await db.execute(text("SELECT * FROM app_settings"))).all() == settings
        assert await db.scalar(select(func.count(Task.id))) == tasks
        assert await db.scalar(select(func.count(Action.id))) == 0
        assert await db.scalar(select(func.count(Schedule.id))) == 0


@pytest.mark.asyncio
async def test_concurrent_ticks_have_one_occurrence_and_one_ai_call(automation):
    env = automation; assert (await enable(env))[0].status_code == 200
    await asyncio.gather(service.run_tick(sessions=env.sessions), service.run_tick(sessions=env.sessions))
    assert len(env.monthly_state.calls) == 1
    async with env.sessions() as db:
        assert await db.scalar(select(func.count(Occurrence.id))) == 1
        assert await db.scalar(select(func.count(Run.id))) == 1


@pytest.mark.parametrize("failure", ["timeout", "exception", "missing"])
@pytest.mark.asyncio
async def test_failed_unknown_and_invalid_ai_are_not_retried(automation, failure):
    env = automation; assert (await enable(env))[0].status_code == 200
    env.monthly_state.failure = failure
    await service.run_tick(sessions=env.sessions)
    await service.run_tick(sessions=env.sessions)
    assert len(env.monthly_state.calls) == 1
    data = await read(env)
    assert data["latest_job"]["status"] in {"unknown", "failed"}
    assert not data["automatic_publish"]


@pytest.mark.parametrize("change", ["menu", "runtime", "connection", "cooperation", "employee"])
@pytest.mark.asyncio
async def test_freshness_permissions_and_cooperation_block_automatic_ai(automation, change):
    env = automation; assert (await enable(env))[0].status_code == 200
    async with env.sessions() as db:
        if change == "menu": (await db.get(Menu, 201)).name = "Changed menu"
        elif change == "connection": (await db.get(Binding, 2)).revision += 1
        elif change == "cooperation": (await db.get(Customers, 20)).status = "paused"
        elif change == "employee": (await db.get(Employees, 1)).status = "inactive"
        await db.commit()
    if change == "runtime": env.monthly_state.runtime.model = "different-destination-model"
    await service.run_tick(sessions=env.sessions)
    assert not env.monthly_state.calls
    async with env.sessions() as db:
        assert (await db.scalar(select(Occurrence))).status == "blocked"


@pytest.mark.asyncio
async def test_pause_is_available_even_after_source_and_cooperation_change(automation):
    env = automation; result, body = await enable(env); assert result.status_code == 200
    async with env.sessions() as db:
        (await db.get(Customers, 20)).status = "paused"
        (await db.get(Menu, 201)).name = "Changed menu"
        await db.commit()
    pause = {**body, "request_id": str(uuid4()), "expected_revision": 1, "enabled": False, "confirmed": False}
    response = await env.auto_client.put(PREFIX+"/customers/20/automation", json=pause)
    assert response.status_code == 200 and not response.json()["policy"]["enabled"]
    await service.run_tick(sessions=env.sessions)
    assert not env.monthly_state.calls


@pytest.mark.asyncio
async def test_pause_after_reservation_prevents_new_ai(automation):
    env = automation; assert (await enable(env))[0].status_code == 200
    async with env.sessions() as db: claim = await service._claim(db, AT)
    async with env.sessions() as db:
        policy = await db.scalar(select(Policy)); policy.enabled = False; policy.revision += 1
        await db.commit()
    async with env.sessions() as db: await service._execute(db, claim)
    assert not env.monthly_state.calls
    async with env.sessions() as db: assert (await db.scalar(select(Occurrence))).status == "blocked"


@pytest.mark.asyncio
async def test_crossing_local_month_after_claim_does_not_prepare_current_month(automation, monkeypatch):
    env = automation; assert (await enable(env))[0].status_code == 200
    async with env.sessions() as db: claim = await service._claim(db, AT)
    monkeypatch.setattr(service, "now", lambda: datetime(2026, 12, 1, 16, tzinfo=timezone.utc))
    async with env.sessions() as db: await service._execute(db, claim)
    assert not env.monthly_state.calls
    async with env.sessions() as db: assert (await db.scalar(select(Occurrence))).status == "blocked"


@pytest.mark.asyncio
async def test_crash_after_reservation_is_quarantined_not_replayed(automation):
    env = automation; assert (await enable(env))[0].status_code == 200
    async with env.sessions() as db: claim = await service._claim(db, AT)
    async with env.sessions() as db:
        job = await db.get(Occurrence, claim["id"]); job.updated_at = AT - timedelta(minutes=6)
        await db.commit()
    await service.run_tick(sessions=env.sessions)
    assert not env.monthly_state.calls
    data = await read(env); assert data["latest_job"]["status"] == "unknown"


@pytest.mark.asyncio
async def test_future_window_only_and_no_historical_catchup(automation):
    env = automation; assert (await enable(env))[0].status_code == 200
    assert (await service.run_tick(sessions=env.sessions, clock=lambda: AT-timedelta(days=10)))["processed"] == 0
    assert (await service.run_tick(sessions=env.sessions, clock=lambda: datetime(2026, 12, 1, 16, tzinfo=timezone.utc)))["processed"] == 0
    assert not env.monthly_state.calls


@pytest.mark.asyncio
async def test_existing_manual_month_is_preserved(automation):
    env = automation; assert (await enable(env))[0].status_code == 200
    from services import media_monthly as monthly_service
    async with env.sessions() as db:
        state = await monthly_service.setup(db, OWNER, 20, month="2026-12")
        original = await monthly_service.generate(db, OWNER, 20, request_id=str(uuid4()), expected_profile_revision=1,
            month="2026-12", input_hash=state["input_hash"], consent={"confirmed": True, "notice_version": monthly_service.NOTICE_VERSION,
                "input_hash": state["input_hash"], "runtime_fingerprint": state["runtime"]["fingerprint"]})
    calls = len(env.monthly_state.calls)
    await service.run_tick(sessions=env.sessions)
    assert len(env.monthly_state.calls) == calls
    job = (await read(env))["latest_job"]
    assert job["status"] == "existing" and job["run_id"] == original["id"]


@pytest.mark.asyncio
async def test_owner_daily_budget_is_durable(automation, monkeypatch):
    env = automation; assert (await enable(env))[0].status_code == 200
    monkeypatch.setattr(service, "OWNER_DAILY_LIMIT", 0)
    assert (await service.run_tick(sessions=env.sessions))["processed"] == 0
    assert not env.monthly_state.calls
    async with env.sessions() as db: assert await db.scalar(select(func.count(Occurrence.id))) == 0


@pytest.mark.asyncio
async def test_global_daily_budget_is_durable(automation, monkeypatch):
    env = automation; assert (await enable(env))[0].status_code == 200
    monkeypatch.setattr(service, "GLOBAL_DAILY_LIMIT", 0)
    assert (await service.run_tick(sessions=env.sessions))["processed"] == 0
    assert not env.monthly_state.calls


@pytest.mark.asyncio
async def test_calendar_rollover_does_not_change_confirmed_source_pin(automation):
    env = automation
    async with env.sessions() as db:
        first = await service.get_policy(db, OWNER, 20, at=AT)
        second = await service.get_policy(db, OWNER, 20, at=datetime(2026, 12, 24, 16, tzinfo=timezone.utc))
    assert first["next_target_month"] == "2026-12" and second["next_target_month"] == "2027-01"
    assert first["source_signature"] == second["source_signature"]
    assert first["runtime"]["fingerprint"] == second["runtime"]["fingerprint"]
    assert not env.monthly_state.calls


@pytest.mark.asyncio
async def test_three_platforms_are_bounded_and_never_create_native_posts(meta_pipeline, automation):
    env = automation
    for platform in ["facebook", "instagram"]:
        response = await env.monthly_client.put(PREFIX+"/customers/20/profile", params={"platform": platform}, json=profile(env))
        assert response.status_code == 200, response.text
    for platform in ["google_business", "facebook", "instagram"]:
        assert (await enable(env, platform))[0].status_code == 200
    assert (await service.run_tick(sessions=env.sessions))["processed"] == 2
    assert len(env.monthly_state.calls) == 2
    assert (await service.run_tick(sessions=env.sessions))["processed"] == 1
    assert len(env.monthly_state.calls) == 3
    from models.meta_operations import MetaOperationsAction, MetaOperationsDraft, MetaOperationsSchedule
    async with env.sessions() as db:
        runs = list((await db.scalars(select(Run))).all())
        assert {run.snapshot.get("platform", "google_business") for run in runs} == {"google_business", "facebook", "instagram"}
        assert await db.scalar(select(func.count(MetaOperationsDraft.id))) == 0
        assert await db.scalar(select(func.count(MetaOperationsSchedule.id))) == 0
        assert await db.scalar(select(func.count(MetaOperationsAction.id))) == 0
    assert not env.ops.reads and not env.ops.writes


@pytest.mark.asyncio
async def test_original_run_recovery_counts_do_not_depend_on_display_limit(automation):
    env = automation; assert (await enable(env))[0].status_code == 200
    await service.run_tick(sessions=env.sessions)
    async with env.sessions() as db:
        job = await db.scalar(select(Occurrence)); job.status = "unknown"; job.run_id = None
        policy = await db.scalar(select(Policy))
        for index in range(25):
            db.add(Occurrence(policy_id=policy.id, policy_revision=1, owner_id=1, customer_id=100+index, customer_name="Synthetic merchant", platform="google_business", month="2026-12",
                request_id=str(uuid4()), source_signature=policy.source_signature, runtime_fingerprint=policy.runtime_fingerprint, generation_input=None, run_id=None,
                status="failed" if index%2 else "missed", message="Synthetic exception", ai_attempted_at=None, created_at=AT, updated_at=AT))
        await db.commit()
    response = await env.auto_client.get(PREFIX+"/automation/overview")
    assert response.status_code == 200, response.text
    value = response.json()
    assert len(value["recent_jobs"]) == 20
    assert value["counts"]["generated"] == 1 and value["counts"]["unknown"] == 0 and value["counts"]["blocked"] == 25
    assert value["attention_total"] == 25 and len(value["attention_jobs"]) == 20
    assert all(job["status"] in {"failed", "missed"} for job in value["attention_jobs"])
    assert (await read(env))["latest_job"]["status"] == "generated"


@pytest.mark.asyncio
async def test_older_exception_is_visible_beyond_twenty_newer_successes(automation):
    env = automation; assert (await enable(env))[0].status_code == 200
    await service.run_tick(sessions=env.sessions)
    async with env.sessions() as db:
        original = await db.scalar(select(Occurrence)); original.status = "unknown"; original.run_id = None
        policy = await db.scalar(select(Policy))
        for index in range(27):
            status = "generated" if index >= 2 else ("blocked" if index == 0 else "running")
            at = AT - timedelta(hours=1) if index < 2 else AT
            db.add(Occurrence(policy_id=policy.id, policy_revision=1, owner_id=1, customer_id=100+index, customer_name="Synthetic merchant", platform="google_business", month="2026-12",
                request_id=str(uuid4()), source_signature=policy.source_signature, runtime_fingerprint=policy.runtime_fingerprint, generation_input=None, run_id=None,
                status=status, message="Synthetic result", ai_attempted_at=None, created_at=at, updated_at=at))
        await db.commit()
    value = (await env.auto_client.get(PREFIX+"/automation/overview")).json()
    assert len(value["recent_jobs"]) == 20 and all(job["status"] == "generated" for job in value["recent_jobs"])
    assert value["attention_total"] == 2 and value["counts"]["blocked"] == 1 and value["counts"]["unknown"] == 1
    assert {job["customer_id"] for job in value["attention_jobs"]} == {100, 101}
    assert {job["status"] for job in value["attention_jobs"]} == {"blocked", "unknown"}
    assert original.id not in {job["id"] for job in value["attention_jobs"]}


@pytest.mark.parametrize("zone,at,expected,trigger", [
    ("America/Denver", datetime(2026, 11, 2, 1, tzinfo=timezone.utc), "2026-12", "2026-11-24T16:00:00+00:00"),
    ("America/Denver", datetime(2026, 12, 1, 1, tzinfo=timezone.utc), "2026-12", "2026-11-24T16:00:00+00:00"),
    ("America/Chicago", datetime(2026, 12, 20, tzinfo=timezone.utc), "2027-01", "2026-12-25T15:00:00+00:00"),
])
def test_local_calendar_and_dst(zone, at, expected, trigger):
    month, due, first = service.target_window(at, zone)
    assert month == expected and due.isoformat() == trigger and due < first


def test_additive_empty_migration_and_downgrade():
    path = Path(__file__).parents[1]/"alembic/versions/h43fe567f803_media_monthly_automation.py"
    spec = importlib.util.spec_from_file_location("monthly_auto_migration", path); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE financial_canary(id INTEGER PRIMARY KEY, value TEXT)"))
        connection.execute(text("INSERT INTO financial_canary VALUES(1,'preserved')"))
        connection.execute(text("CREATE TABLE media_monthly_runs(id INTEGER PRIMARY KEY)"))
        context = MigrationContext.configure(connection)
        with Operations.context(context): module.upgrade()
        assert service.TABLES.issubset(set(inspect(connection).get_table_names()))
        for table in service.TABLES: assert connection.execute(text('SELECT count(*) FROM '+table)).scalar() == 0
        with Operations.context(context): module.downgrade()
        assert connection.execute(text("SELECT value FROM financial_canary")).scalar() == "preserved"


@pytest.mark.asyncio
async def test_actual_router_discovery_has_no_generic_crud_for_automation_tables(automation):
    # This is the actual production router discovery function, not only the
    # small isolated automation router. ORM import does not register entity
    # CRUD. Neither owner nor staff can bypass consent/versioned endpoints.
    from main import include_routers_from_package
    app = FastAPI(); include_routers_from_package(app)
    paths = app.openapi()["paths"]
    assert PREFIX+"/customers/{customer_id}/automation" in paths
    assert PREFIX+"/automation/requests/{request_id}" in paths
    assert PREFIX+"/automation/overview" in paths
    async def database():
        async with automation.sessions() as db: yield db
    async def actor(): return automation.user
    app.dependency_overrides[get_db] = database; app.dependency_overrides[get_current_user] = actor
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://synthetic.test") as client:
        for actor_value in (OWNER, OPS):
            automation.user = actor_value
            for table in service.TABLES:
                url = "/api/v1/entities/"+table
                assert url not in paths and url+"/{id}" not in paths
                assert (await client.get(url)).status_code == 404
                assert (await client.get(url+"/1")).status_code == 404
                assert (await client.post(url, json={"enabled": True})).status_code == 404
                assert (await client.put(url+"/1", json={"enabled": True})).status_code == 404
                assert (await client.delete(url+"/1")).status_code == 404
