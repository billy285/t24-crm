"""Independent publication security checks: local SQLite and fake Google only.

These tests exercise real HTTP authorization, approval and scheduling boundaries.
They never use a production file, credential, platform account or live network.
"""
import asyncio
import copy
import importlib.util
import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, select, text
from alembic.migration import MigrationContext
from alembic.operations import Operations

from models.customer_access_grants import CustomerAccessGrant
from models.customer_materials import Customer_materials
from models.media_operations import MediaOperationEvent, MediaOperationTask
from test_google_business import OWNER, OPS, OTHER, SECOND_OWNER, PREFIX, gbp_env, ready_task
from test_google_business_management import management_env, NOW, enable_scheduler

MEDIA = "/api/v1/media-operations"


def event_spec(**updates):
    return {"topic_type": "EVENT", "event": {
        "title": "Confirmed open house", "start_at": "2026-12-01T09:00:00-08:00",
        "end_at": "2026-12-01T10:00:00-08:00"}, **updates}


def offer_spec(**updates):
    return {**event_spec(), "topic_type": "OFFER", "offer": {
        "coupon_code": "VISIT10", "redeem_online_url": "https://offers.example.com/visit",
        "terms_conditions": "One use per person. Confirmed terms only."}, **updates}


def create_body(**updates):
    return {"client_request_id": str(uuid4()), "customer_id": 10, "title": "Confirmed publication",
        "platform": "google_business", "due_at": "2026-12-01T17:00:00Z",
        "timezone": "America/Los_Angeles", "assignee_id": 2,
        "content": "Confirmed public merchant announcement.", **updates}


async def create(env, publication=None, **updates):
    body = create_body(publication=publication, **updates)
    result = await env.client.post(MEDIA, json=body)
    assert result.status_code == 201, result.text
    return result.json()


async def transition(env, row, action):
    result = await env.client.post(f"{MEDIA}/{row['id']}/transition", json={
        "request_id": str(uuid4()), "expected_revision": row["revision"], "action": action})
    assert result.status_code == 200, result.text
    return result.json()


async def approved(env, publication=None, **updates):
    env.user = OWNER
    row = await create(env, publication, **updates)
    env.user = OPS
    row = await transition(env, row, "submit")
    env.user = OWNER
    return await transition(env, row, "approve")


async def publish(env, row, request_id=None):
    return await env.client.post(PREFIX + "/bindings/1/posts", json={
        "request_id": request_id or str(uuid4()), "task_id": row["id"],
        "expected_revision": row["revision"], "confirmed": True})


async def plan(env, row, request_id=None):
    return await env.client.post(PREFIX + "/bindings/1/schedules", json={
        "request_id": request_id or str(uuid4()), "task_id": row["id"],
        "expected_revision": row["revision"], "planned_at": (env.clock + timedelta(minutes=2)).isoformat(),
        "timezone": "America/Los_Angeles", "confirmed": True})


async def safety_canaries(env):
    async with env.sessions() as db:
        return {table: [tuple(row) for row in (await db.execute(text('SELECT * FROM "' + table + '" ORDER BY id'))).all()]
                for table in ("financial_canary", "private_space_canary")}


@pytest_asyncio.fixture
async def publication_env(management_env):
    before = await safety_canaries(management_env)
    yield management_env
    assert await safety_canaries(management_env) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", [None, {"topic_type": "STANDARD"}])
async def test_default_google_publication_keeps_legacy_payload_and_no_spec_row(publication_env, spec):
    env = publication_env
    row = await approved(env, spec)
    assert row["publication"] == {"topic_type": "STANDARD"}
    async with env.sessions() as db:
        assert (await db.execute(text("SELECT count(*) FROM media_operation_publication_specs WHERE task_id=:id"), {"id": row["id"]})).scalar_one() == 0
    result = await publish(env, row)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "succeeded"
    assert env.fake.writes == [("publish", "accounts/100/locations/1000", {
        "languageCode": "en-US", "summary": row["content"], "topicType": "STANDARD"})]


@pytest.mark.asyncio
@pytest.mark.parametrize("spec,topic", [(event_spec(), "EVENT"), (offer_spec(), "OFFER")])
async def test_exact_owner_approved_structure_is_the_only_google_payload(publication_env, spec, topic):
    env = publication_env
    row = await approved(env, spec)
    result = await publish(env, row)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "succeeded"
    assert len(env.fake.writes) == 1
    sent = env.fake.writes[0][2]
    assert sent["topicType"] == topic and sent["summary"] == row["content"]
    assert sent["event"]["title"] == "Confirmed open house"
    times = sent["event"]["schedule"]
    assert times["startDate"] == times["endDate"] == {"year": 2026, "month": 12, "day": 1}
    for key, hour in (("startTime", 9), ("endTime", 10)):
        assert times[key]["hours"] == hour and times[key]["minutes"] == 0
        assert times[key].get("seconds", 0) == times[key].get("nanos", 0) == 0
    assert not {"publication", "scheduledTime", "recurrenceInfo", "name", "state", "searchUrl"}.intersection(sent)
    if topic == "OFFER":
        assert sent["offer"] == {"couponCode": "VISIT10", "redeemOnlineUrl": "https://offers.example.com/visit",
            "termsConditions": "One use per person. Confirmed terms only."}
        assert "callToAction" not in sent


def injected_specs():
    for value in ({"topic_type": "ALERT"}, {"topic_type": "STANDARD", "event": event_spec()["event"]},
                  {"topic_type": "EVENT"}, {"topic_type": "OFFER", "event": event_spec()["event"]},
                  event_spec(offer={}), offer_spec(call_to_action={"action_type": "CALL"}),
                  {"topic_type": "STANDARD", "scheduledTime": "2026-12-01T17:00:00Z"},
                  event_spec(recurrenceInfo={"dailyPattern": {}}),
                  {"topic_type": "STANDARD", "media": [{"sourceUrl": "https://images.example.com/new.png"}]},
                  {"topic_type": "STANDARD", "owner_id": 9}):
        yield value
    for name, value in (("state", "LIVE"), ("location_name", "accounts/200/locations/2000"), ("dataRef", {})):
        entry = event_spec(); entry["event"][name] = value; yield entry
    entry = offer_spec(); entry["offer"]["customer_id"] = 20; yield entry
    yield {"topic_type": "STANDARD", "call_to_action": {"action_type": "BOOK", "url": "https://book.example.com", "scope": "all"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", list(injected_specs()))
async def test_unknown_or_incompatible_json_cannot_be_persisted_or_sent(publication_env, spec):
    env = publication_env
    response = await env.client.post(MEDIA, json=create_body(publication=spec))
    assert response.status_code == 422, response.text
    async with env.sessions() as db:
        assert (await db.execute(text("SELECT count(*) FROM media_operation_tasks"))).scalar_one() == 0
        assert (await db.execute(text("SELECT count(*) FROM media_operation_publication_specs"))).scalar_one() == 0
    assert not env.fake.writes and not env.fake.reads


@pytest.mark.asyncio
@pytest.mark.parametrize("start,end", [
    ("2026-02-30T09:00:00-08:00", "2026-02-30T10:00:00-08:00"),
    ("2026-12-01T09:00:00", "2026-12-01T10:00:00"),
    ("2026-12-01T09:00:01-08:00", "2026-12-01T10:00:00-08:00"),
    ("2026-12-01T09:00:00.000001-08:00", "2026-12-01T10:00:00-08:00"),
    ("2026-12-01T09:00:00-05:00", "2026-12-01T10:00:00-05:00"),
    ("2026-12-01T10:00:00-08:00", "2026-12-01T09:00:00-08:00"),
    ("2026-12-01T09:00:00-08:00", "2026-12-01T09:00:00-08:00"),
    ("2026-03-08T02:30:00-08:00", "2026-03-08T04:00:00-07:00"),
    ("2026-11-01T01:30:00-07:00", "2026-11-01T02:30:00-08:00"),
    ("2026-11-01T09:30:00Z", "2026-11-01T10:30:00Z"),
    (True, "2026-12-01T10:00:00-08:00"),
])
async def test_invalid_or_ambiguous_time_never_reaches_google(publication_env, start, end):
    env = publication_env; spec = event_spec(); spec["event"].update(start_at=start, end_at=end)
    result = await env.client.post(MEDIA, json=create_body(publication=spec))
    assert result.status_code == 422, result.text
    assert not env.fake.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://offers.example.com/", "javascript:alert(1)", "file:///etc/passwd",
    "https://127.0.0.1/", "https://[::1]/", "https://10.0.0.5/", "https://2130706433/",
    "https://localhost/", "https://internal.local/", "https://service.internal/",
    "https://user:pass@offers.example.com/", "https://offers.example.com:444/",
    "https://offers.example.com/#fragment",
    "https://offers.example.com\\@127.0.0.1/", "https://offers.example.com/path\r\nX-Secret:value",
])
async def test_offer_and_cta_reject_unsafe_or_unreviewed_url_forms(publication_env, url):
    env = publication_env
    for spec in (event_spec(call_to_action={"action_type": "BOOK", "url": url}),
                 offer_spec(offer={"redeem_online_url": url})):
        result = await env.client.post(MEDIA, json=create_body(publication=spec))
        assert result.status_code == 422, (url, result.text)
    assert not env.fake.writes and not env.fake.reads


@pytest.mark.asyncio
@pytest.mark.parametrize("cta", [{"action_type": "CALL", "url": "https://book.example.com"},
    {"action_type": "BOOK"}, {"action_type": "GET_OFFER", "url": "https://book.example.com"},
    {"action_type": "ACTION_TYPE_UNSPECIFIED"}])
async def test_cta_cannot_silently_publish_a_different_button(publication_env, cta):
    result = await publication_env.client.post(MEDIA, json=create_body(publication=event_spec(call_to_action=cta)))
    assert result.status_code == 422, result.text
    assert not publication_env.fake.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("spec,expected", [
    (event_spec(call_to_action={"action_type": "CALL"}), {"actionType": "CALL"}),
    (event_spec(call_to_action={"action_type": "BOOK", "url": "https://booking.example.com/open-house?branch=CA&source=crm"}),
     {"actionType": "BOOK", "url": "https://booking.example.com/open-house?branch=CA&source=crm"}),
])
async def test_supported_cta_and_normal_query_survive_exact_owner_review(publication_env, spec, expected):
    env = publication_env; row = await approved(env, spec)
    result = await publish(env, row)
    assert result.status_code == 200 and result.json()["status"] == "succeeded", result.text
    assert env.fake.writes[0][2]["callToAction"] == expected


@pytest.mark.asyncio
async def test_offer_query_is_public_content_and_later_query_change_invalidates_approval(publication_env):
    env = publication_env; spec = offer_spec()
    spec["offer"]["redeem_online_url"] = "https://offers.example.com/visit?code=VISIT10&branch=CA"
    row = await approved(env, spec)
    await mutate_stored_spec(env, row["id"], lambda value: value["offer"].update(
        redeem_online_url="https://offers.example.com/visit?code=DIFFERENT&branch=CA"))
    result = await publish(env, row)
    assert result.status_code in {409, 422}, result.text
    assert not env.fake.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["facebook", "instagram", "tiktok", "xiaohongshu", "other"])
async def test_google_structure_is_not_a_backdoor_for_other_platforms(publication_env, platform):
    env = publication_env
    assert (await env.client.post(MEDIA, json=create_body(platform=platform, publication=offer_spec()))).status_code == 422
    row = await create(env, None, platform=platform)
    assert row["publication"] is None
    env.user = OPS; row = await transition(env, row, "submit")
    env.user = OWNER; row = await transition(env, row, "approve")
    result = await publish(env, row)
    assert result.status_code in {409, 422} and not env.fake.writes


@pytest.mark.asyncio
async def test_creation_replay_compares_normalized_publication_structure(publication_env):
    env = publication_env; body = create_body(publication=event_spec())
    first = await env.client.post(MEDIA, json=body)
    assert first.status_code == 201, first.text
    same = copy.deepcopy(body); same["publication"]["event"].update(start_at="2026-12-01T17:00:00Z", end_at="2026-12-01T18:00:00Z")
    replay = await env.client.post(MEDIA, json=same)
    assert replay.status_code == 201 and replay.json()["id"] == first.json()["id"]
    different = copy.deepcopy(body); different["publication"]["event"]["title"] = "Unreviewed different title"
    conflict = await env.client.post(MEDIA, json=different)
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_publication_edit_uses_task_cas_and_returns_to_owner_review(publication_env):
    env = publication_env; row = await create(env, event_spec())
    first = await env.client.put(f"{MEDIA}/{row['id']}", json={"expected_revision": row["revision"], "publication": offer_spec()})
    assert first.status_code == 200, first.text
    stale = await env.client.put(f"{MEDIA}/{row['id']}", json={"expected_revision": row["revision"], "publication": event_spec()})
    assert stale.status_code == 409
    env.user = OPS; submitted = await transition(env, first.json(), "submit")
    assert (await env.client.put(f"{MEDIA}/{row['id']}", json={"expected_revision": submitted["revision"], "publication": event_spec()})).status_code == 409
    assert (await publish(env, submitted)).status_code in {409, 422}
    assert not env.fake.writes


async def mutate_stored_spec(env, task_id, transform):
    async with env.sessions() as db:
        raw = (await db.execute(text("SELECT spec FROM media_operation_publication_specs WHERE task_id=:id"), {"id": task_id})).scalar_one()
        value = json.loads(raw) if isinstance(raw, str) else copy.deepcopy(raw)
        transform(value)
        await db.execute(text("UPDATE media_operation_publication_specs SET spec=:value WHERE task_id=:id"), {"value": json.dumps(value), "id": task_id})
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["title", "start_at", "coupon_code", "redeem_online_url", "terms_conditions", "missing_spec"])
async def test_out_of_band_structure_change_cannot_reuse_old_owner_approval(publication_env, field):
    env = publication_env; row = await approved(env, offer_spec())
    if field == "missing_spec":
        async with env.sessions() as db:
            await db.execute(text("DELETE FROM media_operation_publication_specs WHERE task_id=:id"), {"id": row["id"]}); await db.commit()
    else:
        def change(spec):
            section = spec["event"] if field in {"title", "start_at"} else spec["offer"]
            section[field] = "2026-12-01T17:30:00Z" if field == "start_at" else ("https://offers.example.com/changed" if field == "redeem_online_url" else "Changed after owner review")
        await mutate_stored_spec(env, row["id"], change)
    result = await publish(env, row)
    assert result.status_code in {409, 422}, result.text
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_reviewed_event_timezone_cannot_be_changed_under_the_same_utc_spec(publication_env):
    env = publication_env; row = await approved(env, event_spec())
    async with env.sessions() as db:
        task = await db.get(MediaOperationTask, row["id"])
        task.timezone = "America/New_York"
        await db.commit()
    result = await publish(env, row)
    assert result.status_code in {409, 422}, result.text
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_ready_task_preview_reports_exact_structure_and_blocks_stale_approval(publication_env):
    env = publication_env; row = await approved(env, offer_spec())
    env.user = OPS
    result = await env.client.get(PREFIX + "/bindings/1/ready-tasks")
    assert result.status_code == 200, result.text
    preview = next(item for item in result.json()["items"] if item["id"] == row["id"])
    assert preview["publication"] == row["publication"] and preview["timezone"] == "America/Los_Angeles"
    assert not preview["publish_blocked_reason"]
    await mutate_stored_spec(env, row["id"], lambda value: value["offer"].update(coupon_code="UNREVIEWED"))
    result = await env.client.get(PREFIX + "/bindings/1/ready-tasks")
    assert result.status_code == 200, result.text
    preview = next(item for item in result.json()["items"] if item["id"] == row["id"])
    assert preview["publish_blocked_reason"]
    assert "SECRET-" not in result.text and not env.fake.reads and not env.fake.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["owner_only", "wrong_customer", "private_url", "content_type"])
async def test_public_image_acl_and_reference_remain_enforced_for_offers(publication_env, change):
    env = publication_env; row = await approved(env, offer_spec(), material_id=1001)
    async with env.sessions() as db:
        material = await db.get(Customer_materials, 1001)
        if change == "owner_only": material.visibility = "owner"
        elif change == "wrong_customer": material.customer_id = 20
        elif change == "private_url": material.file_url = "https://127.0.0.1/private.png"
        else: material.content_type = "video/mp4"
        await db.commit()
    result = await publish(env, row)
    assert result.status_code in {403, 409, 422}, result.text
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_structured_task_does_not_grant_uninvited_operator_or_other_owner_access(publication_env):
    env = publication_env; row = await approved(env, offer_spec())
    for actor in (OTHER, SECOND_OWNER):
        env.user = actor
        result = await publish(env, row)
        assert result.status_code in {403, 404}, result.text
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_unknown_offer_is_not_resent_by_same_uuid_new_uuid_or_worker_restart(publication_env):
    env = publication_env; row = await approved(env, offer_spec()); key = str(uuid4()); env.fake.failure = "timeout_after"
    first = await publish(env, row, key)
    assert first.status_code == 200 and first.json()["status"] == "unknown", first.text
    env.fake.failure = None
    repeat = await publish(env, row, key)
    assert repeat.status_code == 200 and repeat.json()["status"] == "unknown"
    assert (await publish(env, row)).status_code == 409
    assert (await plan(env, row)).status_code == 409
    from services import google_business_scheduler as scheduler
    enable_scheduler(env); await scheduler.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    assert len(env.fake.writes) == 1


@pytest.mark.asyncio
async def test_saved_offer_schedule_rechecks_structure_before_any_publication(publication_env):
    env = publication_env; row = await approved(env, offer_spec())
    response = await plan(env, row)
    assert response.status_code == 200, response.text
    await mutate_stored_spec(env, row["id"], lambda value: value["offer"].update(coupon_code="AFTER_REVIEW"))
    enable_scheduler(env); env.clock += timedelta(minutes=2)
    from services import google_business_scheduler as scheduler
    await scheduler.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_legacy_approved_and_scheduled_standard_fingerprint_is_unchanged(publication_env):
    env = publication_env; task_id = await ready_task(env, due_at=NOW)
    response = await plan(env, {"id": task_id, "revision": 3})
    assert response.status_code == 200, response.text
    async with env.sessions() as db:
        task = await db.get(MediaOperationTask, task_id)
        row = (await db.execute(text("SELECT payload_fingerprint FROM google_business_schedules WHERE task_id=:id"), {"id": task_id})).scalar_one()
        assert row == env.service.digest({"languageCode": "en-US", "summary": task.content, "topicType": "STANDARD"})
    enable_scheduler(env); env.clock += timedelta(minutes=2)
    from services import google_business_scheduler as scheduler
    await scheduler.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    assert len(env.fake.writes) == 1 and env.fake.writes[0][2]["topicType"] == "STANDARD"


@pytest.mark.asyncio
async def test_structured_schedule_timeout_remains_unknown_across_worker_restarts(publication_env):
    env = publication_env; row = await approved(env, offer_spec())
    response = await plan(env, row)
    assert response.status_code == 200, response.text
    enable_scheduler(env); env.clock += timedelta(minutes=2); env.fake.failure = "timeout_after"
    from services import google_business_scheduler as scheduler
    await scheduler.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    env.fake.failure = None
    await scheduler.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    assert len(env.fake.writes) == 1 and env.fake.writes[0][2]["topicType"] == "OFFER"
    async with env.sessions() as db:
        status = (await db.execute(text("SELECT status FROM google_business_schedules WHERE task_id=:id"), {"id": row["id"]})).scalar_one()
        assert status == "unknown"
    assert (await plan(env, row)).status_code == 409
    assert (await publish(env, row)).status_code == 409


@pytest.mark.asyncio
async def test_slow_structured_publish_does_not_hold_company_database_write_lock(publication_env):
    env = publication_env; row = await approved(env, event_spec())
    env.fake.write_started = asyncio.Event(); env.fake.release_write = asyncio.Event()
    attempt = asyncio.create_task(publish(env, row))
    try:
        await asyncio.wait_for(env.fake.write_started.wait(), 2)
        async def independent_company_write():
            async with env.sessions() as db:
                # An UPDATE of the same value still acquires SQLite's writer
                # reservation; the canary content itself remains unchanged.
                await db.execute(text("UPDATE financial_canary SET amount=amount WHERE id=1"))
                await db.commit()
        await asyncio.wait_for(independent_company_write(), 1)
    finally:
        env.fake.release_write.set()
    result = await asyncio.wait_for(attempt, 2)
    assert result.status_code == 200 and result.json()["status"] == "succeeded", result.text


@pytest.mark.asyncio
async def test_history_http_uses_frozen_public_configuration_not_current_task(publication_env):
    env = publication_env; row = await approved(env, offer_spec())
    sent = await publish(env, row); assert sent.status_code == 200, sent.text
    identity = sent.json()["id"]
    async with env.sessions() as db:
        action = await db.get(env.Action, identity)
        payload = copy.deepcopy(action.payload)
        payload.update(credential="SECRET-HISTORY-EXTRA", media=[{"sourceUrl": "https://private.example.com/SECRET-ASSET"}])
        payload["event"]["schedule"]["internal"] = {"secret": "SECRET-HISTORY-NESTED"}
        payload["offer"]["private"] = "SECRET-HISTORY-OFFER"
        action.payload = payload
        task = await db.get(MediaOperationTask, row["id"]); task.timezone = "Asia/Shanghai"
        await db.commit()
    await mutate_stored_spec(env, row["id"], lambda spec: spec["event"].update(title="DIFFERENT-CURRENT-TASK"))
    env.user = OPS; reads, writes = len(env.fake.reads), len(env.fake.writes)
    result = await env.client.get(PREFIX + f"/actions/{identity}")
    assert result.status_code == 200 and result.headers["cache-control"] == "private, no-store", result.text
    configuration = result.json()["publication_payload"]
    assert configuration["topicType"] == "OFFER"
    assert configuration["event"]["title"] == "Confirmed open house"
    assert configuration["event"]["schedule"]["startTime"]["hours"] == 9
    assert "timezone" not in configuration and "start_at" not in configuration["event"]
    assert "media" not in configuration and "SECRET-" not in result.text and "DIFFERENT-CURRENT-TASK" not in result.text
    assert (len(env.fake.reads), len(env.fake.writes)) == (reads, writes)


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", [OTHER, SECOND_OWNER])
async def test_history_configuration_does_not_bypass_store_authorization(publication_env, actor):
    env = publication_env; row = await approved(env, offer_spec()); sent = await publish(env, row)
    assert sent.status_code == 200, sent.text
    env.user = actor; result = await env.client.get(PREFIX + f"/actions/{sent.json()['id']}")
    assert result.status_code in {403, 404}, result.text
    assert "VISIT10" not in result.text and "Confirmed open house" not in result.text


@pytest.mark.asyncio
@pytest.mark.parametrize("age,retained", [(timedelta(days=30), True), (timedelta(days=30, microseconds=1), False)])
async def test_history_http_expiry_does_not_depend_on_a_cleanup_job(publication_env, age, retained):
    env = publication_env; row = await approved(env, offer_spec()); sent = await publish(env, row)
    assert sent.status_code == 200, sent.text
    identity = sent.json()["id"]
    async with env.sessions() as db:
        action = await db.get(env.Action, identity); action.created_at = env.clock - age
        await db.commit()
    result = await env.client.get(PREFIX + f"/actions/{identity}")
    assert result.status_code == 200, result.text
    assert (result.json()["publication_payload"] is not None) is retained
    assert (result.json()["content"] is not None) is retained
    if not retained: assert "VISIT10" not in result.text and "Confirmed open house" not in result.text


def test_opt_in_migration_keeps_existing_rows_and_autoincrement_state(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/eaf5a7b8c914_media_publication_specs.py"
    module_spec = importlib.util.spec_from_file_location("independent_publication_migration", path)
    migration = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(migration)
    assert migration.down_revision == "d9e4f6a7b803"
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            conn.exec_driver_sql("CREATE TABLE media_operation_tasks(id INTEGER PRIMARY KEY AUTOINCREMENT,content TEXT NOT NULL)")
            conn.exec_driver_sql("CREATE TABLE media_operation_events(id INTEGER PRIMARY KEY AUTOINCREMENT,snapshot TEXT NOT NULL)")
            conn.exec_driver_sql("CREATE TABLE google_business_connections(id INTEGER PRIMARY KEY AUTOINCREMENT,token_encrypted TEXT NOT NULL)")
            conn.exec_driver_sql("CREATE TABLE financial_canary(id INTEGER PRIMARY KEY,amount TEXT,closed INTEGER)")
            conn.exec_driver_sql("INSERT INTO media_operation_tasks VALUES(9,'Approved legacy standard')")
            conn.exec_driver_sql("INSERT INTO media_operation_events VALUES(12,'{\"legacy\":true}')")
            conn.exec_driver_sql("INSERT INTO google_business_connections VALUES(3,'SYNTHETIC-ENCRYPTED-NOT-REAL')")
            conn.exec_driver_sql("INSERT INTO financial_canary VALUES(1,'199.00',1)")
            original = inspect(conn).get_table_names()
            before = {name: conn.exec_driver_sql('SELECT * FROM "' + name + '"').all() for name in original}
            seq_before = conn.exec_driver_sql("SELECT * FROM sqlite_sequence ORDER BY name").all()
            sql = []; conn.connection.driver_connection.set_trace_callback(sql.append)
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
            migration.upgrade()
            conn.connection.driver_connection.set_trace_callback(None)
            assert set(inspect(conn).get_table_names()) == set(original) | {"media_operation_publication_specs"}
            assert all(conn.exec_driver_sql('SELECT * FROM "' + name + '"').all() == value for name, value in before.items())
            assert conn.exec_driver_sql("SELECT * FROM sqlite_sequence ORDER BY name").all() == seq_before
            assert conn.exec_driver_sql("SELECT count(*) FROM media_operation_publication_specs").scalar_one() == 0
            assert not any(statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "DROP", "ALTER")) for statement in sql)
            fk = inspect(conn).get_foreign_keys("media_operation_publication_specs")
            assert len(fk) == 1 and fk[0]["referred_table"] == "media_operation_tasks"
            assert fk[0]["options"].get("ondelete") == "RESTRICT"
            with pytest.raises(RuntimeError): migration.downgrade()
            assert "media_operation_publication_specs" in inspect(conn).get_table_names()
    finally:
        engine.dispose()
