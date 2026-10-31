"""Single-store preparation checks use synthetic SQLite and never call Google."""
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from models.media_operations import MediaOperationTask
from models.media_publication_images import MediaPublicationImageDelivery as Delivery
from services import google_business_readiness as service
from test_google_business import OWNER, OPS, OTHER, ADMIN, SECOND_OWNER, PREFIX, gbp_env, ready_task, mutate_invitation
from test_google_business_management import management_env
from test_media_publication_images import image_env, prepared, reviewed_task, enable


async def snapshot(env):
    async with env.sessions() as db:
        names = (await db.scalars(text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))).all()
        return {name: sorted(repr(tuple(row)) for row in (await db.execute(text('SELECT * FROM "' + name.replace('"', '""') + '"'))).all()) for name in names}


async def get(env, task_id=None, binding_id=1):
    return await env.client.get(f"{PREFIX}/bindings/{binding_id}/readiness", params={"task_id": task_id} if task_id else {})


def steps(response):
    assert response.status_code == 200, response.text
    return {item["key"]: item for item in response.json()["checks"]}


@pytest.mark.asyncio
async def test_store_checklist_is_read_only_and_does_not_enable_policy_or_call_google(management_env):
    env = management_env; before = await snapshot(env)
    response = await get(env)
    data = response.json(); checks = steps(response)
    assert checks["operator"]["status"] == "passed"
    assert checks["image_delivery"]["status"] == "pending"
    assert data["image_delivery"]["scope"] == "owner_account" and not data["image_delivery"]["enabled"]
    assert data["task"] is None and not data["can_open_publish"] and not data["can_open_schedule"]
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert await snapshot(env) == before
    assert not env.fake.reads and not env.fake.writes
    assert all(secret not in response.text for secret in ("SYNTHETIC-ACCESS-TOKEN", "SYNTHETIC-REFRESH-TOKEN", "SECRET-PRIVATE-NOTES", "PRIVATE-OWNER-ONLY-CANARY"))


@pytest.mark.asyncio
@pytest.mark.parametrize("actor,binding_id", [(OTHER, 1), (ADMIN, 1), (SECOND_OWNER, 1), (OPS, 2), (OWNER, 2)])
async def test_uninvited_foreign_and_other_owner_cannot_inspect_preparation(management_env, actor, binding_id):
    env = management_env; env.user = actor
    response = await get(env, binding_id=binding_id)
    assert response.status_code in (403, 404)
    assert "SECRET-HIDDEN-MERCHANT" not in response.text
    assert not env.fake.reads and not env.fake.writes


@pytest.mark.asyncio
async def test_operator_can_prepare_own_task_but_not_another_assignees_task(management_env):
    env = management_env
    own = await ready_task(env); other = await ready_task(env, assignee_id=3, assignee_name=OTHER.name)
    env.user = OPS
    response = await get(env, own); checks = steps(response)
    assert checks["approval"]["status"] == "passed"
    assert response.json()["can_open_publish"] and response.json()["can_open_schedule"]
    assert (await get(env, other)).status_code == 404
    await mutate_invitation(env, invitation_status="revoked")
    assert (await get(env, own)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["draft", "in_review", "content", "customer", "platform"])
async def test_unapproved_changed_or_mismatched_task_cannot_appear_publishable(management_env, change):
    env = management_env
    task_id = await ready_task(env)
    async with env.sessions() as db:
        row = await db.get(MediaOperationTask, task_id)
        if change in {"draft", "in_review"}: row.status = change
        elif change == "content": row.content = "Changed content awaiting fresh owner approval"
        elif change == "customer": row.customer_id = 30
        else: row.platform = "instagram"
        await db.commit()
    before = await snapshot(env)
    response = await get(env, task_id)
    if change in {"customer", "platform"}: assert response.status_code == 404
    else:
        assert steps(response)["approval"]["status"] in {"pending", "blocked"}
        assert not response.json()["can_open_publish"] and not response.json()["can_open_schedule"]
    assert await snapshot(env) == before
    assert not env.fake.reads and not env.fake.writes


@pytest.mark.asyncio
async def test_missing_primary_only_blocks_scheduling_not_existing_owner_manual_permission(management_env):
    env = management_env; task_id = await ready_task(env)
    async with env.sessions() as db:
        row = await db.get(env.Binding, 1); row.primary_operator_id = None; row.primary_operator_name = None
        await db.commit()
    response = await get(env, task_id)
    assert steps(response)["operator"]["status"] == "pending"
    assert response.json()["can_open_publish"] and not response.json()["can_open_schedule"]


@pytest.mark.asyncio
async def test_disabled_provider_is_visible_without_exposing_configuration(management_env, monkeypatch):
    env = management_env; task_id = await ready_task(env)
    monkeypatch.setenv("T24_GBP_ENABLED", "false")
    response = await get(env, task_id)
    assert steps(response)["configuration"]["status"] == "blocked"
    assert not response.json()["can_open_publish"]
    assert "SYNTHETIC-CLIENT-SECRET" not in response.text and "TOKEN_KEY" not in response.text
    assert not env.fake.reads and not env.fake.writes


@pytest.mark.asyncio
async def test_reconnect_and_paused_store_are_advisory_blocks_without_changing_settings(management_env):
    env = management_env; task_id = await ready_task(env)
    async with env.sessions() as db:
        (await db.get(env.Binding, 1)).lifecycle = "paused"
        (await db.get(env.Connection, 1)).needs_reconnect = True
        await db.commit()
    before = await snapshot(env)
    response = await get(env, task_id); checks = steps(response)
    assert checks["merchant"]["status"] == checks["connection"]["status"] == "blocked"
    assert not response.json()["can_open_publish"]
    assert await snapshot(env) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "unknown", "accepted", "succeeded"])
async def test_existing_publication_is_linked_without_reconciliation_or_resubmission(management_env, status):
    env = management_env; task_id = await ready_task(env)
    async with env.sessions() as db:
        db.add(env.Action(binding_id=1, customer_id=10, kind="post_publish", request_id=str(uuid4()),
            fingerprint="a" * 64, actor_id=2, actor_name=OPS.name, task_id=task_id, status=status,
            payload={"summary": "Original frozen text", "topicType": "STANDARD",
                "media": [{"sourceUrl": "https://crm.example.com/SHOULD-NOT-LEAK-CAPABILITY"}]}))
        await db.commit()
    before = await snapshot(env)
    response = await get(env, task_id); data = response.json()
    assert steps(response)["existing_request"]["status"] == "blocked"
    assert data["active_action"]["status"] == status
    assert "SHOULD-NOT-LEAK-CAPABILITY" not in response.text
    assert not data["can_open_publish"] and not data["can_open_schedule"]
    assert await snapshot(env) == before
    assert not env.fake.reads and not env.fake.writes


@pytest.mark.asyncio
async def test_existing_schedule_shows_actual_time_and_prevents_second_send(management_env):
    from models.google_business import GoogleBusinessSchedule
    env = management_env; task_id = await ready_task(env)
    planned_at = env.clock + timedelta(hours=2)
    async with env.sessions() as db:
        db.add(GoogleBusinessSchedule(binding_id=1, task_id=task_id, task_revision=3, payload_fingerprint="b" * 64,
            operator_id=2, owner_id=1, request_id=str(uuid4()), planned_at=planned_at,
            timezone="America/Los_Angeles", status="scheduled", revision=1, created_by_id=1))
        await db.commit()
    response = await get(env, task_id)
    assert steps(response)["existing_request"]["status"] == "blocked"
    data = response.json()
    assert data["active_schedule"]["planned_at"] == planned_at.isoformat()
    assert data["active_schedule"]["task_id"] == data["task"]["id"]
    assert data["task"]["due_at"] != data["active_schedule"]["planned_at"]
    assert not data["can_open_publish"] and not env.fake.writes


@pytest.mark.asyncio
async def test_image_off_and_on_preflight_never_opens_lease_or_changes_real_policy(image_env):
    env = image_env; image = await prepared(env); task = await reviewed_task(env, image)
    before = await snapshot(env)
    response = await get(env, task["id"])
    assert "尚未启用" in steps(response)["approval"]["message"]
    assert not response.json()["can_open_publish"] and await snapshot(env) == before
    await enable(env)
    before = await snapshot(env)
    response = await get(env, task["id"]); data = response.json()
    assert steps(response)["approval"]["status"] == "passed" and data["can_open_publish"]
    assert data["image_delivery"]["enabled"] and "老板账号" in steps(response)["image_delivery"]["message"]
    assert await snapshot(env) == before
    async with env.sessions() as db:
        assert not (await db.scalars(select(Delivery))).all()
    assert not env.fake.reads and not env.fake.writes


@pytest.mark.asyncio
async def test_endpoint_works_with_database_in_query_only_mode(management_env):
    from core.database import get_db
    env = management_env; task_id = await ready_task(env)
    # A SQLite read-only transaction makes a hidden seed/reservation/write fail.
    async def read_only_database():
        async with env.sessions() as db:
            await db.execute(text("PRAGMA query_only=ON"))
            try:
                yield db
            finally:
                await db.rollback()
                await db.execute(text("PRAGMA query_only=OFF"))
    app = env.client._transport.app
    app.dependency_overrides[get_db] = read_only_database
    response = await get(env, task_id)
    assert response.status_code == 200 and response.json()["can_open_publish"], response.text
    assert not env.fake.reads and not env.fake.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["publish_revoked", "task_revision", "customer_revoked"])
async def test_late_preparation_change_cannot_return_stale_publishable_state(management_env, monkeypatch, change):
    env = management_env; env.user = OPS; task_id = await ready_task(env)
    original = service._approved_content
    async def changed_after_check(db, ctx, binding, task):
        await original(db, ctx, binding, task)
        async with env.sessions() as other_db:
            if change == "publish_revoked":
                grant = await other_db.scalar(select(env.Grant).where(env.Grant.binding_id == 1, env.Grant.employee_id == 2))
                grant.can_publish = False
            elif change == "task_revision":
                (await other_db.get(MediaOperationTask, task_id)).revision += 1
            else:
                from models.customer_access_grants import CustomerAccessGrant
                grant = await other_db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.customer_id == 10, CustomerAccessGrant.employee_id == 2))
                grant.invitation_status = "revoked"
            await other_db.commit()
    monkeypatch.setattr(service, "_approved_content", changed_after_check)
    response = await get(env, task_id)
    assert response.status_code in {404, 409}, response.text
    assert "can_open_publish" not in response.text
    assert not env.fake.reads and not env.fake.writes
