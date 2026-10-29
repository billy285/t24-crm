"""Independent synthetic permission, workflow and retry tests for Media Operations.

No provider calls, production DB, automatic publishing, or real customer data.
"""
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from alembic.migration import MigrationContext
from alembic.operations import Operations

from core.database import Base, get_db
from dependencies.auth import get_current_user
from models.customer_access_grants import CustomerAccessGrant
from models.customer_materials import Customer_materials
from models.customers import Customers
from models.employees import Employees
from models.service_progresses import Service_progresses
from models.service_tasks import Service_tasks
from schemas.auth import UserResponse


PREFIX = "/api/v1/media-operations"
OWNER = UserResponse(id="1", role="super_admin", name="Synthetic Owner", email="owner@example.test")
OPS = UserResponse(id="2", role="ops", name="Assigned Operator", email="ops@example.test")
OTHER = UserResponse(id="3", role="ops", name="Other Operator", email="other@example.test")
ADMIN = UserResponse(id="5", role="admin", name="Ordinary Admin", email="admin@example.test")


def task_payload(**updates):
    return {
        "client_request_id": str(uuid4()),
        "customer_id": 10,
        "service_progress_id": 101,
        "title": "Synthetic October content",
        "platform": "instagram",
        "due_at": "2026-10-29T12:00:00-04:00",
        "timezone": "America/New_York",
        "assignee_id": 2,
        "content": "Confirmed synthetic service details only.",
        "material_id": 1001,
        **updates,
    }


@pytest_asyncio.fixture
async def media_env(tmp_path):
    # Delayed imports make this independent file usable while the additive
    # router is being developed in parallel.
    import models.media_operations
    from routers.media_operations import router

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'synthetic-media.db'}", connect_args={"timeout": 5})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE TABLE IF NOT EXISTS app_settings(config_key TEXT PRIMARY KEY,value_json TEXT)"))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add_all([
            Employees(id=int(actor.id), user_id=actor.id, name=actor.name, role=actor.role, status="active", password="SECRET-EMPLOYEE-PASSWORD")
            for actor in (OWNER, OPS, OTHER, ADMIN)
        ])
        db.add(Employees(id=6, user_id="6", name="Inactive Operator", role="ops", status="disabled"))
        db.add_all([
            Customers(id=10, business_name="Granted Synthetic Merchant", contact_name="Synthetic", phone="111", private_notes="SECRET-PRIVATE-NOTES", notes="SECRET-OWNER-NOTES"),
            Customers(id=20, business_name="Hidden Synthetic Merchant", contact_name="Private", phone="222", private_notes="SECRET-HIDDEN-NOTES"),
        ])
        for employee_id in (2, 3):
            db.add(CustomerAccessGrant(customer_id=10, employee_id=employee_id, access_level="read_write", invitation_source="owner_invitation", invitation_status="active", finance_access="none", scopes={"basic": "read_only", "delivery": "read_write", "materials": "read_only"}))
        db.add_all([
            Service_progresses(id=101, customer_id=10, customer_name="Granted Synthetic Merchant", service_stage="content_prep", package_name="Synthetic Service", user_id="1"),
            Service_progresses(id=201, customer_id=20, customer_name="Hidden Synthetic Merchant", service_stage="content_prep", package_name="Hidden Service", user_id="1"),
            Customer_materials(id=1001, customer_id=10, user_id="1", title="Team Image", material_type="image", visibility="team", content_type="image/png", file_path="SECRET-STORAGE-PATH", file_url="https://private.example.test/SECRET-RAW-URL"),
            Customer_materials(id=1002, customer_id=10, user_id="1", title="SECRET-OWNER-MATERIAL", material_type="image", visibility="owner", content_type="image/png"),
            Customer_materials(id=1003, customer_id=10, user_id="1", title="SECRET-FINANCE-MATERIAL", material_type="image", visibility="finance", content_type="image/png"),
            Customer_materials(id=1004, customer_id=10, user_id="1", title="Team PDF", material_type="document", visibility="team", content_type="application/pdf"),
            Customer_materials(id=2001, customer_id=20, user_id="1", title="Hidden Image", material_type="image", visibility="team", content_type="image/png"),
        ])
        config = {role: {"pages": ["/media-ops", "/service-board", "/customers"], "buttons": ["task_create", "task_edit"], "dataScope": "all"} for role in ("super_admin", "ops", "admin")}
        # A forged broad page/button configuration never promotes another role.
        for role in ("finance", "sales", "sales_partner", "design"):
            config[role] = {"pages": ["/media-ops", "/service-board", "/customers"], "buttons": ["task_create", "task_edit"], "dataScope": "all"}
        await db.execute(text("INSERT INTO app_settings(config_key,value_json) VALUES('role_permissions',:v)"), {"v": json.dumps(config)})
        await db.commit()
    app = FastAPI()
    app.include_router(router)
    state = SimpleNamespace(user=OWNER, sessions=sessions, engine=engine)
    async def database():
        async with sessions() as db:
            yield db
    async def actor():
        return state.user
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = actor
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://synthetic.test") as client:
        state.client = client
        yield state
    await engine.dispose()


async def create(env, **updates):
    result = await env.client.post(PREFIX, json=task_payload(**updates))
    assert result.status_code == 201, result.text
    assert result.headers.get("cache-control") == "private, no-store"
    return result.json()


async def transition(env, row, action, **updates):
    return await env.client.post(f"{PREFIX}/{row['id']}/transition", json={"expected_revision": row["revision"], "request_id": str(uuid4()), "action": action, **updates})


async def move(env, row, action, **updates):
    result = await transition(env, row, action, **updates)
    assert result.status_code == 200, result.text
    return result.json()


async def grant(env, employee_id=2, **updates):
    async with env.sessions() as db:
        entry = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id == employee_id, CustomerAccessGrant.customer_id == 10))
        for key, value in updates.items():
            setattr(entry, key, value)
        await db.commit()


@pytest.mark.asyncio
async def test_owner_create_and_operator_full_reviewed_manual_publication_loop(media_env):
    env = media_env
    row = await create(env)
    assert row["status"] == "draft" and row["revision"] == 1
    env.user = OPS
    row = await move(env, row, "submit")
    assert row["status"] == "in_review"
    assert (await transition(env, row, "approve")).status_code == 403
    env.user = OWNER
    row = await move(env, row, "approve")
    assert row["status"] == "ready"
    env.user = OPS
    row = await move(env, row, "complete", proof_url="https://www.instagram.com/p/SYNTHETIC-ONLY/")
    assert row["status"] == "completed" and row["completed_at"]
    detail = (await env.client.get(f"{PREFIX}/{row['id']}")).json()
    assert len(detail["events"]) >= 4
    assert not detail["permissions"]["can_edit"]
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Service_tasks)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["finance", "sales", "sales_partner", "design"])
async def test_non_operations_roles_cannot_gain_media_access_from_forged_pages(media_env, role):
    env = media_env
    row = await create(env)
    env.user = UserResponse(id="2", role=role, email="forged@example.test")
    for path in (PREFIX, PREFIX + "/options", f"{PREFIX}/{row['id']}"):
        assert (await env.client.get(path)).status_code == 403
    assert (await env.client.post(PREFIX, json=task_payload())).status_code == 403
    assert (await transition(env, row, "submit")).status_code == 403


@pytest.mark.asyncio
async def test_operator_list_summary_detail_and_options_do_not_leak_other_assignees(media_env):
    env = media_env
    mine = await create(env)
    theirs = await create(env, assignee_id=3, title="OTHER-ASSIGNEE-TITLE")
    hidden = await create(env, customer_id=20, service_progress_id=201, assignee_id=1, material_id=None, title="SECRET-HIDDEN-TITLE")
    env.user = OPS
    listing = await env.client.get(PREFIX)
    data = listing.json()
    assert data["total"] == 1
    assert [item["id"] for item in data["items"]] == [mine["id"]]
    assert data["summary"]["draft"] == 1
    assert (await env.client.get(f"{PREFIX}/{theirs['id']}")).status_code == 404
    assert (await env.client.get(f"{PREFIX}/{hidden['id']}")).status_code == 404
    assert (await env.client.get(PREFIX + "?customer_id=20")).json()["total"] == 0
    options = await env.client.get(PREFIX + "/options")
    assert [item["id"] for item in options.json()["customers"]] == [10]
    for response in (listing, options):
        assert response.headers.get("cache-control") == "private, no-store"
        for secret in ("SECRET-", "Hidden Synthetic Merchant", "OTHER-ASSIGNEE-TITLE", "password", "finance_access", "amount_paid", "monthlyRevenue", "private_notes", "file_url", "file_path"):
            assert secret not in response.text
    material_ids = [item["id"] for item in options.json()["customers"][0]["materials"]]
    assert 1001 in material_ids and 1002 not in material_ids and 1003 not in material_ids and 2001 not in material_ids


@pytest.mark.asyncio
async def test_revocation_blocks_reads_replays_options_and_writes_immediately(media_env):
    env = media_env
    row = await create(env)
    env.user = OPS
    key = str(uuid4())
    row = await move(env, row, "submit", request_id=key)
    await grant(env, invitation_status="revoked")
    assert (await env.client.get(PREFIX)).json()["total"] == 0
    assert (await env.client.get(PREFIX + "/options")).json()["customers"] == []
    assert (await env.client.get(f"{PREFIX}/{row['id']}")).status_code == 404
    assert (await transition(env, row, "submit", request_id=key)).status_code == 404
    assert (await env.client.put(f"{PREFIX}/{row['id']}", json={"expected_revision": row["revision"], "title": "FORGED"})).status_code in {403, 404}


@pytest.mark.asyncio
async def test_read_only_assignee_can_read_but_cannot_mutate(media_env):
    env = media_env
    row = await create(env)
    await grant(env, access_level="read_only", scopes={"basic": "read_only", "delivery": "read_only", "materials": "read_only"})
    env.user = OPS
    detail = await env.client.get(f"{PREFIX}/{row['id']}")
    assert detail.status_code == 200
    assert not detail.json()["permissions"]["can_edit"]
    assert (await transition(env, row, "submit")).status_code in {403, 404}
    assert (await env.client.put(f"{PREFIX}/{row['id']}", json={"expected_revision": 1, "title": "FORGED"})).status_code in {403, 404}
    assert (await env.client.post(PREFIX, json=task_payload())).status_code in {403, 404}


@pytest.mark.asyncio
async def test_ordinary_admin_is_not_global_owner_or_reviewer(media_env):
    env = media_env
    row = await create(env)
    env.user = ADMIN
    assert (await env.client.get(PREFIX)).json()["total"] == 0
    assert (await env.client.get(f"{PREFIX}/{row['id']}")).status_code == 404
    assert (await transition(env, row, "approve")).status_code in {403, 404}
    assert (await env.client.post(PREFIX, json=task_payload(assignee_id=5))).status_code in {403, 404}


@pytest.mark.asyncio
@pytest.mark.parametrize("updates", [
    {"service_progress_id": 201},
    {"material_id": 2001},
    {"material_id": 1002},
    {"material_id": 1003},
    {"assignee_id": 5},
    {"assignee_id": 6},
    {"assignee_id": 999999},
])
async def test_forged_links_and_uninvited_or_disabled_assignees_rejected(media_env, updates):
    result = await media_env.client.post(PREFIX, json=task_payload(**updates))
    assert result.status_code in {403, 404, 422}, result.text
    assert (await media_env.client.get(PREFIX)).json()["total"] == 0


@pytest.mark.asyncio
async def test_material_permission_removed_after_draft_cannot_submit_material_reference(media_env):
    env = media_env
    row = await create(env)
    await grant(env, scopes={"basic": "read_only", "delivery": "read_write", "materials": "none"})
    env.user = OPS
    result = await transition(env, row, "submit")
    assert result.status_code in {403, 404, 422}, result.text


@pytest.mark.asyncio
async def test_create_retry_is_stable_and_changed_payload_conflicts(media_env):
    env = media_env
    payload = task_payload()
    first = await env.client.post(PREFIX, json=payload)
    second = await env.client.post(PREFIX, json=payload)
    assert first.status_code == 201 and second.status_code in {200, 201}
    assert first.json()["id"] == second.json()["id"]
    payload["title"] = "A different operation"
    assert (await env.client.post(PREFIX, json=payload)).status_code == 409
    assert (await env.client.get(PREFIX)).json()["total"] == 1


@pytest.mark.asyncio
async def test_request_replay_cannot_change_action_or_parameters(media_env):
    env = media_env
    row = await create(env)
    key = str(uuid4())
    submitted = await move(env, row, "submit", request_id=key)
    repeated = await move(env, row, "submit", request_id=key)
    assert repeated["revision"] == submitted["revision"]
    changed = await transition(env, row, "block", request_id=key, note="Changed request intent")
    assert changed.status_code == 409
    assert len((await env.client.get(f"{PREFIX}/{row['id']}")).json()["events"]) == len(submitted["events"])


@pytest.mark.asyncio
async def test_concurrent_submit_creates_only_one_transition(media_env):
    env = media_env
    row = await create(env)
    results = await asyncio.gather(transition(env, row, "submit"), transition(env, row, "submit"))
    assert sorted(result.status_code for result in results) == [200, 409]
    data = (await env.client.get(f"{PREFIX}/{row['id']}")).json()
    assert data["status"] == "in_review" and data["revision"] == 2
    assert sum(event["action"] == "submit" for event in data["events"]) == 1


@pytest.mark.asyncio
async def test_stale_revision_and_post_review_edit_rejected(media_env):
    env = media_env
    row = await create(env)
    result = await env.client.put(f"{PREFIX}/{row['id']}", json={"expected_revision": 0, "title": "FORGED"})
    assert result.status_code in {409, 422}
    row = await move(env, row, "submit")
    for actor in (OWNER, OPS):
        env.user = actor
        result = await env.client.put(f"{PREFIX}/{row['id']}", json={"expected_revision": row["revision"], "content": "Silently changed"})
        assert result.status_code == 409


@pytest.mark.asyncio
async def test_owner_return_requires_reason_and_preserves_audit_then_edit_allowed(media_env):
    env = media_env
    row = await move(env, await create(env), "submit")
    assert (await transition(env, row, "return", note=" ")).status_code == 422
    row = await move(env, row, "return", note="Please verify the opening hours")
    assert row["status"] == "draft"
    env.user = OPS
    result = await env.client.put(f"{PREFIX}/{row['id']}", json={"expected_revision": row["revision"], "content": "Verified opening hours"})
    assert result.status_code == 200, result.text
    assert any(event["action"] == "return" for event in result.json()["events"])


@pytest.mark.asyncio
async def test_block_resume_cannot_skip_review_and_reason_is_required(media_env):
    env = media_env
    row = await create(env)
    assert (await transition(env, row, "block", note=" ")).status_code == 422
    row = await move(env, row, "block", note="Waiting for client image confirmation")
    assert row["status"] == "blocked"
    row = await move(env, row, "resume")
    assert row["status"] == "draft"
    assert (await transition(env, row, "complete", proof_url="https://www.instagram.com/p/SYNTHETIC/")).status_code == 409
    row = await move(env, row, "submit")
    row = await move(env, row, "approve")
    row = await move(env, row, "block", note="Platform unavailable")
    row = await move(env, row, "resume")
    assert row["status"] == "ready"


@pytest.mark.asyncio
async def test_completion_requires_url_or_image_proof_and_terminal_is_locked(media_env):
    env = media_env
    row = await move(env, await create(env), "submit")
    row = await move(env, row, "approve")
    assert (await transition(env, row, "complete")).status_code == 422
    for material_id in (1002, 1003, 1004, 2001):
        result = await transition(env, row, "complete", proof_material_id=material_id)
        assert result.status_code in {403, 404, 422}, result.text
    row = await move(env, row, "complete", proof_material_id=1001)
    assert row["status"] == "completed"
    assert (await transition(env, row, "block", note="Cannot reopen terminal")).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "http://www.instagram.com/p/test", "https://localhost/private", "https://127.0.0.1/private",
    "https://10.0.0.1/private", "https://169.254.169.254/latest/meta-data", "https://[::1]/private",
    "https://user:password@www.instagram.com/p/test", "https://example.test/unsafe\nInjected: true",
])
async def test_unsafe_proof_urls_rejected(media_env, url):
    env = media_env
    row = await move(env, await create(env), "submit")
    row = await move(env, row, "approve")
    result = await transition(env, row, "complete", proof_url=url)
    assert result.status_code == 422, result.text


@pytest.mark.asyncio
@pytest.mark.parametrize("updates", [
    {"due_at": "2026-10-29T12:00:00"}, {"due_at": "not-a-date"}, {"timezone": "Mars/Unknown"},
    {"platform": "private_internal_route"}, {"status": "completed"}, {"completed_by": "Boss"},
    {"finance_access": "profit"}, {"customer_name": "Forged Name"}, {"client_request_id": "not-a-uuid"},
])
async def test_invalid_dates_platform_and_server_managed_fields_fail_closed(media_env, updates):
    result = await media_env.client.post(PREFIX, json=task_payload(**updates))
    assert result.status_code == 422, result.text


@pytest.mark.asyncio
async def test_submit_requires_draft_content_and_pagination_is_bounded(media_env):
    env = media_env
    row = await create(env, content="")
    assert (await transition(env, row, "submit")).status_code == 422
    await create(env, title="Second row")
    first = (await env.client.get(PREFIX + "?skip=0&limit=1")).json()
    second = (await env.client.get(PREFIX + "?skip=1&limit=1")).json()
    assert first["total"] == second["total"] == 2
    assert len(first["items"]) == len(second["items"]) == 1
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert (await env.client.get(PREFIX + "?limit=1000")).status_code == 422


@pytest.mark.asyncio
async def test_delivery_and_material_scope_are_independent(media_env):
    env = media_env
    await grant(env, scopes={"basic": "read_only", "delivery": "none", "materials": "read_write"})
    env.user = OPS
    assert (await env.client.get(PREFIX + "/options")).json()["customers"] == []
    assert (await env.client.post(PREFIX, json=task_payload())).status_code in {403, 404}


@pytest.mark.asyncio
async def test_list_cannot_leak_records_when_effective_detail_permission_is_denied(media_env):
    env = media_env
    row = await create(env)
    async with env.sessions() as db:
        config = json.loads(await db.scalar(text("SELECT value_json FROM app_settings WHERE config_key='role_permissions'")))
        config["ops"]["pages"] = ["/media-ops"]
        await db.execute(text("UPDATE app_settings SET value_json=:v WHERE config_key='role_permissions'"), {"v": json.dumps(config)})
        await db.commit()
    env.user = OPS
    detail = await env.client.get(f"{PREFIX}/{row['id']}")
    listing = await env.client.get(PREFIX)
    # The product can explicitly permit the new operations page on its own, or
    # preserve the old delivery-page prerequisite. Every surface must agree.
    if detail.status_code == 200:
        assert listing.status_code == 200 and listing.json()["total"] == 1
    else:
        assert detail.status_code in {403, 404}
        assert listing.status_code == 403 or listing.json()["total"] == 0


@pytest.mark.asyncio
async def test_changed_material_visibility_hides_saved_pointers_and_stops_submit(media_env):
    env = media_env
    row = await create(env)
    async with env.sessions() as db:
        material = await db.get(Customer_materials, 1001)
        material.visibility = "finance"
        material.title = "SECRET-NEW-FINANCIAL-DOCUMENT"
        await db.commit()
    env.user = OPS
    for response in (await env.client.get(PREFIX), await env.client.get(f"{PREFIX}/{row['id']}")):
        assert response.status_code == 200
        assert "SECRET-NEW" not in response.text
        data = response.json()
        record = data["items"][0] if "items" in data else data
        assert record["material_id"] is None and record["material_title"] is None
    assert (await transition(env, row, "submit")).status_code in {403, 404, 422}


@pytest.mark.asyncio
async def test_only_owner_reassigns_to_currently_authorized_operator(media_env):
    env = media_env
    row = await create(env)
    env.user = OPS
    assert (await env.client.post(PREFIX, json=task_payload(assignee_id=3))).status_code == 403
    assert (await env.client.put(f"{PREFIX}/{row['id']}", json={"expected_revision": 1, "assignee_id": 3})).status_code == 403
    env.user = OWNER
    result = await env.client.put(f"{PREFIX}/{row['id']}", json={"expected_revision": 1, "assignee_id": 3})
    assert result.status_code == 200, result.text
    assert result.json()["assignee_id"] == 3
    env.user = OPS
    assert (await env.client.get(f"{PREFIX}/{row['id']}")).status_code == 404
    env.user = OTHER
    assert (await env.client.get(f"{PREFIX}/{row['id']}")).status_code == 200


@pytest.mark.asyncio
async def test_owner_cannot_assign_staff_after_role_edit_button_removed(media_env):
    env = media_env
    async with env.sessions() as db:
        config = json.loads(await db.scalar(text("SELECT value_json FROM app_settings WHERE config_key='role_permissions'")))
        config["ops"]["buttons"] = ["task_create"]
        await db.execute(text("UPDATE app_settings SET value_json=:v WHERE config_key='role_permissions'"), {"v": json.dumps(config)})
        await db.commit()
    result = await env.client.post(PREFIX, json=task_payload())
    assert result.status_code in {403, 422}
    options = (await env.client.get(PREFIX + "/options")).json()
    assert not any(person["id"] == 2 and 10 in person.get("eligible_customer_ids", []) for person in options["assignees"])


@pytest.mark.asyncio
async def test_manual_workflow_leaves_existing_financial_and_service_rows_unchanged(media_env):
    env = media_env
    async with env.sessions() as db:
        await db.execute(text("CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY,customer_id INTEGER NOT NULL,amount_due FLOAT NOT NULL,amount_paid FLOAT NOT NULL,user_id TEXT NOT NULL)"))
        await db.execute(text("CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY,expense_type TEXT NOT NULL,amount FLOAT NOT NULL,user_id TEXT NOT NULL)"))
        await db.execute(text("CREATE TABLE IF NOT EXISTS company_expenses(id INTEGER PRIMARY KEY,category TEXT NOT NULL,amount FLOAT NOT NULL,user_id TEXT NOT NULL)"))
        await db.execute(text("INSERT INTO payments(id,customer_id,amount_due,amount_paid,user_id) VALUES(987,10,1234.56,1234.56,'1')"))
        await db.execute(text("INSERT INTO expenses(id,expense_type,amount,user_id) VALUES(987,'design_fee',123.45,'1')"))
        await db.execute(text("INSERT INTO company_expenses(id,category,amount,user_id) VALUES(987,'software',67.89,'1')"))
        await db.commit()
        baseline = {name: [tuple(row) for row in (await db.execute(text(f"SELECT * FROM {name} ORDER BY id"))).all()] for name in ("payments", "expenses", "company_expenses", "service_tasks", "service_progresses", "customer_access_grants")}
    row = await move(env, await create(env), "submit")
    row = await move(env, row, "approve")
    await move(env, row, "complete", proof_url="https://www.instagram.com/p/SYNTHETIC-ONLY/")
    async with env.sessions() as db:
        after = {name: [tuple(row) for row in (await db.execute(text(f"SELECT * FROM {name} ORDER BY id"))).all()] for name in baseline}
    assert after == baseline


def test_migration_is_additive_empty_and_preserves_old_finance_sentinel(tmp_path):
    path = Path(__file__).parents[1] / "alembic/versions/b7c2d9e4a601_media_operations.py"
    spec = importlib.util.spec_from_file_location("synthetic_media_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "a8d4e2c6f901"
    engine = create_engine(f"sqlite:///{tmp_path / 'synthetic-migration.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE existing_finance_sentinel(id INTEGER PRIMARY KEY,amount INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO existing_finance_sentinel VALUES(1,12345)"))
        before = conn.execute(text("SELECT sql FROM sqlite_master WHERE name='existing_finance_sentinel'")).scalar()
        module.op = Operations(MigrationContext.configure(conn))
        module.upgrade()
        names = set(conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars())
        assert names == {"existing_finance_sentinel", "media_operation_tasks", "media_operation_events"}
        assert conn.execute(text("SELECT sql FROM sqlite_master WHERE name='existing_finance_sentinel'")).scalar() == before
        assert conn.execute(text("SELECT amount FROM existing_finance_sentinel")).scalar() == 12345
        assert conn.execute(text("SELECT COUNT(*) FROM media_operation_tasks")).scalar() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM media_operation_events")).scalar() == 0
        with pytest.raises(RuntimeError, match="forward migration"):
            module.downgrade()
        assert conn.execute(text("SELECT amount FROM existing_finance_sentinel")).scalar() == 12345
    engine.dispose()
