"""Synthetic monthly drafts: no production data, AI or public provider calls."""
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import struct
from types import SimpleNamespace
from uuid import uuid4
import zlib

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI, HTTPException
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import create_engine, func, inspect, select, text

from core.database import get_db
from dependencies.auth import get_current_user
from models.customer_materials import Customer_materials as Material
from models.customer_menu_items import Customer_menu_items as Menu
from models.customers import Customers
from models.customer_access_grants import CustomerAccessGrant
from models.employees import Employees
from models.media_monthly import MediaMonthlyProfile as Profile, MediaMonthlyRun as Run, MediaMonthlyItem as Item
from models.media_operations import MediaOperationTask as Task, MediaOperationEvent as Event
from models.media_publication_images import MediaPublicationImageSelection as Selection, MediaPublicationImageDelivery as Delivery
from models.google_business import GoogleBusinessAction as GoogleAction, GoogleBusinessSchedule as GoogleSchedule
from routers.media_monthly import router
from services import media_monthly as service, media_publication_images as images
from test_google_business import gbp_env, OWNER, OPS

PREFIX = "/api/v1/media-monthly"
RULES = {"timezone": "America/Chicago", "weekdays": [2, 4, 6], "local_time": "11:00", "posts_per_week": 3,
         "language": "en", "include_prices": False, "generic_mode": False, "forbidden_claims": ["best in town"]}


def png(width=320, height=320):
    rng = random.Random(17)
    raw = b"".join(b"\0" + rng.randbytes(width * 3) for _ in range(height))
    return images.PNG + images._chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + images._chunk(b"IDAT", zlib.compress(raw)) + images._chunk(b"IEND", b"")


@pytest_asyncio.fixture
async def monthly(gbp_env, tmp_path, monkeypatch):
    env = gbp_env
    root = tmp_path / "materials"; (root / "20").mkdir(parents=True)
    original = png(); (root / "20" / "front.png").write_bytes(original)
    monkeypatch.setattr(images, "MATERIALS_ROOT", root)
    runtime = SimpleNamespace(enabled=True, provider="deepseek", model="synthetic-model", api_key="SYNTHETIC-API-SECRET", base_url="https://api.example.com/v1")
    async def runtime_config(db): return runtime
    monkeypatch.setattr(service, "resolve_ai_runtime_config", runtime_config)
    async with env.sessions() as db:
        customer = await db.get(Customers, 20); customer.business_name = "Internal CRM alias"; customer.notes = "SECRET-PRIVATE-CRM-NOTES"
        db.add(Menu(id=201, customer_id=20, user_id="1", name="Beef noodles", category="Noodles", price="$12.00", selling_points="Confirmed menu item", status="active", notes="SECRET-MENU-NOTES"))
        db.add(Material(id=203, user_id="1", customer_id=20, title="Confirmed real storefront", material_type="image", visibility="team", content_type="image/png", source_type="upload",
            file_path="20/front.png", approval_status="approved", copyright_status="client_provided", linked_item_id=201, notes="SECRET-MATERIAL-NOTES"))
        await db.commit()
        version = await images.prepare(db, OWNER, customer_id=20, material_id=203, source_sha256=hashlib.sha256(original).hexdigest(), rights_basis="client_provided", rights_confirmed=True, request_id=str(uuid4()), body=original)
    state = SimpleNamespace(calls=[], failure=None, started=None, release=None, runtime=runtime)
    async def fake_ai(runtime, snapshot):
        async with env.sessions() as db:
            reserved = await db.scalar(select(Run).where(Run.status == "generating"))
            assert reserved is not None, "AI called before durable reservation"
        state.calls.append(service._ai_payload(snapshot))
        if state.started: state.started.set(); await state.release.wait()
        if state.failure == "timeout": raise service.MonthlyAIError(unknown=True)
        if state.failure == "exception": raise RuntimeError("SECRET-RAW-PROVIDER-ERROR")
        values = [{"slot_id": row["slot_id"], "title": "Menu spotlight", "content": "Beef noodles at Northern Pasta in Houston.", "owner_summary": "围绕已确认的牛肉面名称及门店位置准备文案，仍需老板核对。"} for row in snapshot["slots"]]
        if state.failure == "missing": values.pop()
        if state.failure == "duplicate": values[-1]["slot_id"] = values[0]["slot_id"]
        if state.failure == "unsupported": values[0]["url"] = "https://unrequested.example.com"
        if state.failure == "price": values[0]["content"] = "Beef noodles for $12.00."
        if state.failure == "hours": values[0]["content"] = "Open today at 11 AM."
        if state.failure == "summary": values[0].pop("owner_summary")
        return json.dumps({"items": values})
    monkeypatch.setattr(service, "call_ai", fake_ai)
    app = FastAPI(); app.include_router(router)
    async def database():
        async with env.sessions() as db: yield db
    async def actor(): return env.user
    app.dependency_overrides[get_db] = database; app.dependency_overrides[get_current_user] = actor
    env.monthly_state = state; env.version = version; env.root = root
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://synthetic.test") as client:
        env.monthly_client = client; yield env


def profile(env, **updates):
    return {"expected_revision": 0, "public_facts": {"public_name": "Northern Pasta", "location": "Houston, TX", "highlights": ["Confirmed Northern Chinese dishes"]}, "rules": dict(RULES),
        "menu_item_ids": [201], "images": [{"material_id": 203, "image_version_id": env.version["id"], "menu_item_id": 201, "quality_confirmed": False}], "confirmed_facts": True, **updates}


async def configured(env, **updates):
    response = await env.monthly_client.put(PREFIX + "/customers/20/profile", json=profile(env, **updates))
    assert response.status_code == 200, response.text
    return response.json()


def generate_body(setup, **updates):
    return {"request_id": str(uuid4()), "expected_profile_revision": setup["profile"]["revision"], "month": "2026-11", "input_hash": setup["input_hash"],
        "consent": {"confirmed": True, "notice_version": "monthly-text-v1", "input_hash": setup["input_hash"], "runtime_fingerprint": setup["runtime"]["fingerprint"]}, **updates}


async def generated(env, **updates):
    setup = await configured(env, **updates)
    body = generate_body(setup)
    response = await env.monthly_client.post(PREFIX + "/customers/20/runs", json=body)
    assert response.status_code == 201, response.text
    return response.json(), body


@pytest.mark.asyncio
async def test_fixed_12_chicago_slots_and_first_durable_text_only_generation(monthly):
    env = monthly; run, body = await generated(env)
    assert run["status"] == "generated" and run["ai_used"] is True and len(run["items"]) == 12
    assert run["adoptable"] is True
    proposed = [datetime.fromisoformat(r["proposed_publish_at"]) for r in run["items"]]
    assert len(set(proposed)) == 12 and all(at.hour == 17 for at in proposed)
    assert [at.day for at in proposed] == [3, 5, 7, 10, 12, 14, 17, 19, 21, 24, 26, 28]
    assert all(r["task_id"] is None and r["owner_summary"] for r in run["items"])
    sent = json.dumps(env.monthly_state.calls[0])
    assert "SECRET" not in sent and "$12.00" not in sent and "Internal CRM alias" not in sent and "front.png" not in sent
    assert "image_sha" not in sent and "file_path" not in sent
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Task)) == 0
        assert await db.scalar(select(func.count()).select_from(GoogleAction)) == 0
        assert await db.scalar(select(func.count()).select_from(GoogleSchedule)) == 0
        assert await db.scalar(select(func.count()).select_from(Delivery)) == 0
    assert not env.fake.reads and not env.fake.writes


@pytest.mark.asyncio
async def test_request_and_semantic_idempotency_never_repeat_ai_or_month(monthly):
    env = monthly; run, body = await generated(env)
    same = await env.monthly_client.post(PREFIX + "/customers/20/runs", json=body)
    other_key = await env.monthly_client.post(PREFIX + "/customers/20/runs", json={**body, "request_id": str(uuid4())})
    assert same.json()["id"] == other_key.json()["id"] == run["id"]
    assert other_key.json()["canonical_request_id"] == body["request_id"] and len(env.monthly_state.calls) == 1
    recovered = await env.monthly_client.get(PREFIX + "/requests/" + body["request_id"])
    assert recovered.json()["id"] == run["id"]
    changed = await env.monthly_client.post(PREFIX + "/customers/20/runs", json={**body, "input_hash": "0" * 64})
    assert changed.status_code == 409


@pytest.mark.asyncio
async def test_parallel_different_uuid_same_input_returns_durable_run_without_second_ai(monthly):
    env = monthly; state = env.monthly_state; state.started = asyncio.Event(); state.release = asyncio.Event()
    setup = await configured(env); first_body = generate_body(setup)
    first = asyncio.create_task(env.monthly_client.post(PREFIX + "/customers/20/runs", json=first_body)); await state.started.wait()
    duplicate = await env.monthly_client.post(PREFIX + "/customers/20/runs", json=generate_body(setup))
    assert duplicate.status_code == 201 and duplicate.json()["status"] == "generating"
    assert duplicate.json()["canonical_request_id"] == first_body["request_id"] and len(state.calls) == 1
    state.release.set(); finished = await first
    assert finished.json()["id"] == duplicate.json()["id"] and len(finished.json()["items"]) == 12


@pytest.mark.asyncio
async def test_identical_profile_confirmation_does_not_create_new_input_revision(monthly):
    env = monthly; setup = await configured(env)
    repeated = await env.monthly_client.put(PREFIX + "/customers/20/profile", json=profile(env, expected_revision=setup["profile"]["revision"]))
    assert repeated.status_code == 200 and repeated.json()["profile"]["revision"] == setup["profile"]["revision"]
    assert repeated.json()["input_hash"] == setup["input_hash"]


@pytest.mark.asyncio
async def test_adopt_is_atomic_draft_only_exact_preview_and_original_uuid(monthly):
    env = monthly; run, _ = await generated(env)
    body = {"request_id": str(uuid4()), "expected_revision": run["revision"], "preview_hash": run["preview_hash"], "confirmed": True}
    wrong = await env.monthly_client.post(PREFIX + f"/runs/{run['id']}/adopt", json={**body, "preview_hash": "0" * 64})
    assert wrong.status_code == 409
    accepted = await env.monthly_client.post(PREFIX + f"/runs/{run['id']}/adopt", json=body)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "adopted" and all(r["task_id"] for r in accepted.json()["items"])
    again = await env.monthly_client.post(PREFIX + f"/runs/{run['id']}/adopt", json=body)
    assert again.json() == accepted.json()
    async with env.sessions() as db:
        tasks = list((await db.scalars(select(Task))).all())
        assert len(tasks) == 12 and all(row.status == "draft" and row.revision == 1 and row.platform == "google_business" for row in tasks)
        assert all("老板" not in row.content for row in tasks)
        assert await db.scalar(select(func.count()).select_from(Selection)) == 12
        assert set((await db.scalars(select(Event.action))).all()) == {"create"}
        assert await db.scalar(select(func.count()).select_from(GoogleAction)) == 0
        assert await db.scalar(select(func.count()).select_from(GoogleSchedule)) == 0
        assert await db.scalar(select(func.count()).select_from(Delivery)) == 0
        assert (await db.execute(text("SELECT * FROM financial_canary"))).one() == (1, "199.00", "closed", "original-owner")


@pytest.mark.asyncio
async def test_item_cas_edit_invalidates_batch_preview_and_chinese_summary_stays_private(monthly):
    env = monthly; run, _ = await generated(env); item = run["items"][0]
    body = {"expected_revision": item["revision"], "title": "Confirmed noodles", "content": "Northern Pasta, Houston.", "owner_summary": "这条仅介绍门店与已确认的位置。"}
    edited = await env.monthly_client.patch(PREFIX + f"/runs/{run['id']}/items/{item['id']}", json=body)
    assert edited.status_code == 200, edited.text
    assert edited.json()["preview_hash"] != run["preview_hash"] and edited.json()["revision"] == run["revision"] + 1
    assert (await env.monthly_client.patch(PREFIX + f"/runs/{run['id']}/items/{item['id']}", json=body)).status_code == 409


@pytest.mark.asyncio
async def test_native_validation_failure_rolls_back_entire_adoption(monthly, monkeypatch):
    env = monthly; run, _ = await generated(env); original = images.save_selection; calls = []
    async def fail_after_first(db, ctx, task, identity):
        calls.append(task.id)
        if len(calls) == 2: raise HTTPException(422, "Synthetic source changed during adoption")
        await original(db, ctx, task, identity)
    monkeypatch.setattr(images, "save_selection", fail_after_first)
    response = await env.monthly_client.post(PREFIX + f"/runs/{run['id']}/adopt", json={"request_id": str(uuid4()), "expected_revision": run["revision"], "preview_hash": run["preview_hash"], "confirmed": True})
    assert response.status_code == 422
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Task)) == 0
        assert await db.scalar(select(func.count()).select_from(Event)) == 0
        assert await db.scalar(select(func.count()).select_from(Selection)) == 0
        assert (await db.get(Run, run["id"])).status == "generated"
        assert all(item.task_id is None for item in (await db.scalars(select(Item))).all())


@pytest.mark.asyncio
async def test_same_month_new_input_cannot_adopt_second_twelve_tasks(monthly):
    env = monthly; first, _ = await generated(env)
    payload = lambda run: {"request_id": str(uuid4()), "expected_revision": run["revision"], "preview_hash": run["preview_hash"], "confirmed": True}
    assert (await env.monthly_client.post(PREFIX + f"/runs/{first['id']}/adopt", json=payload(first))).status_code == 200
    changed = profile(env, expected_revision=1); changed["public_facts"]["highlights"].append("Confirmed menu selection")
    setup = await env.monthly_client.put(PREFIX + "/customers/20/profile", json=changed)
    assert setup.status_code == 200
    other = await env.monthly_client.post(PREFIX + "/customers/20/runs", json=generate_body(setup.json()))
    assert other.status_code == 201 and other.json()["id"] != first["id"]
    rejected = await env.monthly_client.post(PREFIX + f"/runs/{other.json()['id']}/adopt", json=payload(other.json()))
    assert rejected.status_code == 409
    async with env.sessions() as db: assert await db.scalar(select(func.count()).select_from(Task)) == 12


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "duplicate", "unsupported", "price", "hours", "summary", "exception", "timeout"])
async def test_ai_invalid_output_or_timeout_never_creates_partial_or_fake_template(monthly, failure):
    env = monthly; env.monthly_state.failure = failure
    run, body = await generated(env)
    assert run["status"] == ("unknown" if failure == "timeout" else "failed") and run["ai_used"] is False and run["items"] == []
    assert "SECRET" not in json.dumps(run)
    repeat = await env.monthly_client.post(PREFIX + "/customers/20/runs", json=body)
    assert repeat.json()["id"] == run["id"] and len(env.monthly_state.calls) == 1


@pytest.mark.asyncio
async def test_source_runtime_and_role_changes_during_generation_invalidate_result(monthly):
    env = monthly; state = env.monthly_state; state.started = asyncio.Event(); state.release = asyncio.Event()
    setup = await configured(env); body = generate_body(setup)
    pending = asyncio.create_task(env.monthly_client.post(PREFIX + "/customers/20/runs", json=body)); await state.started.wait()
    async with env.sessions() as db:
        menu = await db.get(Menu, 201); menu.name = "Changed menu fact"; await db.commit()
    state.release.set(); response = await pending
    assert response.status_code == 201 and response.json()["status"] == "failed" and response.json()["items"] == []


@pytest.mark.asyncio
async def test_adopt_revalidates_source_and_runtime_not_just_old_preview(monthly):
    env = monthly; run, _ = await generated(env)
    env.monthly_state.runtime.model = "changed-model"
    response = await env.monthly_client.post(PREFIX + f"/runs/{run['id']}/adopt", json={"request_id": str(uuid4()), "expected_revision": run["revision"], "preview_hash": run["preview_hash"], "confirmed": True})
    assert response.status_code == 409
    async with env.sessions() as db: assert await db.scalar(select(func.count()).select_from(Task)) == 0


@pytest.mark.asyncio
async def test_lowres_reference_candidates_visible_but_adoption_blocked(monthly):
    env = monthly
    values = profile(env); values["images"] = [{"material_id": 203, "image_version_id": None, "menu_item_id": 201, "quality_confirmed": True}]
    run, _ = await generated(env, **values)
    assert run["status"] == "generated" and run["adoptable"] is False and all(r["quality_warnings"] for r in run["items"])
    response = await env.monthly_client.post(PREFIX + f"/runs/{run['id']}/adopt", json={"request_id": str(uuid4()), "expected_revision": run["revision"], "preview_hash": run["preview_hash"], "confirmed": True})
    assert response.status_code == 409
    async with env.sessions() as db:
        rows = await service.workspace_rows(db, OWNER, [20], datetime(2026, 11, 1, tzinfo=timezone.utc), datetime(2026, 12, 1, tzinfo=timezone.utc), "review")
        assert len(rows) == 1 and rows[0]["kind"] == "monthly_run" and rows[0]["status"] == "blocked" and rows[0]["review_eligible"] is False
        calendar_rows = await service.workspace_rows(db, OWNER, [20], datetime(2026, 11, 1, tzinfo=timezone.utc), datetime(2026, 12, 1, tzinfo=timezone.utc), "calendar")
        assert len(calendar_rows) == 12 and all(row["time_basis"] == "proposed_publish" for row in calendar_rows)


@pytest.mark.asyncio
async def test_central_projection_owner_review_calendar_staff_and_inbox_boundaries(monthly, monkeypatch):
    from routers.media_workspace import router as projection_router
    env = monthly; monkeypatch.setenv("JWT_SECRET_KEY", "synthetic-monthly-cursor-signing-key-32")
    env.monthly_client._transport.app.include_router(projection_router)
    run, _ = await generated(env)
    params = {"start": "2026-11-01T00:00:00Z", "end": "2026-12-01T00:00:00Z", "customer_id": 20, "limit": 100}
    review = await env.monthly_client.get("/api/v1/media-workspace/workspace", params={**params, "view": "review"})
    assert review.status_code == 200, review.text
    monthly_rows = [r for r in review.json()["items"] if r["kind"].startswith("monthly_")]
    assert len(monthly_rows) == 1 and monthly_rows[0]["kind"] == "monthly_run"
    assert monthly_rows[0]["navigation"] == {"workspace": "monthly", "run_id": run["id"]}
    assert monthly_rows[0]["review_eligible"] is False and review.json()["summary"]["review_candidates"] == 0
    calendar = await env.monthly_client.get("/api/v1/media-workspace/workspace", params={**params, "view": "calendar"})
    assert calendar.status_code == 200, calendar.text
    entries = [r for r in calendar.json()["items"] if r["kind"] == "monthly_item"]
    assert len(entries) == 12 and all(r["time_basis"] == "proposed_publish" and r["status"] == "generated" for r in entries)
    assert calendar.json()["summary"]["scheduled"] == 0
    inbox = await env.monthly_client.get("/api/v1/media-workspace/workspace", params={**params, "view": "inbox"})
    assert inbox.status_code == 200 and not any(r["kind"].startswith("monthly_") for r in inbox.json()["items"])
    other_platform = await env.monthly_client.get("/api/v1/media-workspace/workspace", params={**params, "view": "review", "platform": "facebook"})
    assert other_platform.status_code == 200 and not any(r["kind"].startswith("monthly_") for r in other_platform.json()["items"])
    async with env.sessions() as db:
        db.add(CustomerAccessGrant(customer_id=20, employee_id=2, access_level="read_write", invitation_source="owner_invitation", invitation_status="active", finance_access="none", scopes={"delivery": "read_write", "materials": "read_only"})); await db.commit()
    env.user = OPS
    async def forbidden(*args, **kwargs): raise AssertionError("Staff reached owner-only monthly data")
    monkeypatch.setattr(service, "workspace_rows", forbidden)
    staff = await env.monthly_client.get("/api/v1/media-workspace/workspace", params={**params, "view": "review"})
    assert staff.status_code == 200, staff.text
    assert not any(r["kind"].startswith("monthly_") for r in staff.json()["items"])
    assert next(s["state"] for s in staff.json()["sources"] if s["key"] == "monthly") == "locked"
    assert len(env.monthly_state.calls) == 1 and not env.fake.reads and not env.fake.writes


@pytest.mark.asyncio
async def test_no_menu_requires_explicit_generic_mode_and_profile_CAS(monthly):
    env = monthly
    setup = await configured(env, menu_item_ids=[], images=[{"material_id": 203, "image_version_id": env.version["id"], "menu_item_id": None, "quality_confirmed": False}])
    assert setup["capabilities"]["can_generate"] is False
    denied = await env.monthly_client.post(PREFIX + "/customers/20/runs", json=generate_body(setup))
    assert denied.status_code == 422 and not env.monthly_state.calls
    assert (await env.monthly_client.put(PREFIX + "/customers/20/profile", json=profile(env))).status_code == 409


@pytest.mark.asyncio
async def test_unmapped_storefront_rotates_confirmed_menu_without_guessing_picture(monthly):
    env = monthly
    async with env.sessions() as db:
        db.add(Menu(id=202, customer_id=20, user_id="1", name="Confirmed dumplings", status="active")); await db.commit()
    run, _ = await generated(env, menu_item_ids=[201, 202], images=[{"material_id": 203, "image_version_id": env.version["id"], "menu_item_id": None, "quality_confirmed": False}])
    assert [item["menu_item_ids"] for item in run["items"]] == [[201], [202]] * 6
    assert [item["menu_item_ids"] for item in env.monthly_state.calls[0]["slots"]] == [[201], [202]] * 6


@pytest.mark.asyncio
async def test_selected_oversized_menu_fact_rejected_before_ai_without_truncation(monthly):
    env = monthly
    async with env.sessions() as db:
        menu = await db.get(Menu, 201); menu.selling_points = "长" * 1001; await db.commit()
    result = await env.monthly_client.put(PREFIX + "/customers/20/profile", json=profile(env))
    assert result.status_code == 422 and not env.monthly_state.calls
    async with env.sessions() as db: assert await db.scalar(select(func.count()).select_from(Profile)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ops", "admin", "finance", "sales", "sales_partner"])
async def test_nonowner_denied_before_any_sql_or_runtime(role):
    class NoDb:
        def __getattr__(self, name): raise AssertionError("nonowner reached database")
    with pytest.raises(HTTPException) as error:
        await service.setup(NoDb(), SimpleNamespace(id="1", role=role), 20)
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_wrong_customer_stale_owner_and_unconfirmed_consent_fail_closed(monthly):
    env = monthly; assert (await env.monthly_client.get(PREFIX + "/customers/10/setup")).status_code == 404
    setup = await configured(env); body = generate_body(setup); body["consent"]["confirmed"] = False
    assert (await env.monthly_client.post(PREFIX + "/customers/20/runs", json=body)).status_code == 422
    assert not env.monthly_state.calls
    env.user = OPS
    assert (await env.monthly_client.get(PREFIX + "/customers/20/setup")).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("base", ["https://localhost/v1", "https://ai.internal/v1", "https://127.0.0.1/v1", "https://oneword/v1", "http://api.example.com/v1", "https://user:secret@api.example.com/v1"])
async def test_ai_runtime_rejects_private_or_credentialled_destinations(monthly, base):
    env = monthly; env.monthly_state.runtime.base_url = base
    response = await env.monthly_client.get(PREFIX + "/customers/20/setup")
    assert response.status_code == 503 and "secret" not in response.text


def test_additive_migration_exact_three_empty_tables_and_existing_rows_untouched(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "migration.db"))
    path = Path(__file__).resolve().parents[1] / "alembic/versions/df0ba123b469_media_monthly.py"
    spec = importlib.util.spec_from_file_location("monthly_migration", path); migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    assert migration.down_revision == "cefa9b12a358" and migration.revision == "df0ba123b469"
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE financial_canary(id INTEGER PRIMARY KEY,amount TEXT)")); conn.execute(text("INSERT INTO financial_canary VALUES(1,'199.00')"))
        conn.execute(text("CREATE TABLE media_operation_tasks(id INTEGER PRIMARY KEY)"))
        with Operations.context(MigrationContext.configure(conn)): migration.upgrade()
        names = set(inspect(conn).get_table_names())
        assert names - {"financial_canary", "media_operation_tasks"} == service.TABLES
        for name in service.TABLES: assert conn.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar() == 0
        assert conn.execute(text("SELECT * FROM financial_canary")).one() == (1, "199.00")
        for model in (Profile, Run, Item): assert set(inspect(conn).get_columns(model.__tablename__)[i]["name"] for i in range(len(inspect(conn).get_columns(model.__tablename__)))) == set(model.__table__.columns.keys())
        with Operations.context(MigrationContext.configure(conn)): migration.downgrade()
        assert set(inspect(conn).get_table_names()) == {"financial_canary", "media_operation_tasks"}
