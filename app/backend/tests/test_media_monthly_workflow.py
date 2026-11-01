"""Whole-month safety through real native workflows and isolated fake Google."""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi import HTTPException
import pytest
import pytest_asyncio
from sqlalchemy import select, func, text
from models.media_monthly_workflow import MediaMonthlyWorkflow as Workflow, MediaMonthlyWorkflowRequest as Request
from models.media_monthly import MediaMonthlyItem as Item
from models.media_operations import MediaOperationTask as Task, MediaOperationEvent as Event
from models.media_publication_images import MediaPublicationImageDelivery as Delivery, MediaPublicationImagePolicy as Policy
from models.google_business import GoogleBusinessSchedule as Schedule, GoogleBusinessAction as Action
from models.customer_materials import Customer_materials as Material
from models.customers import Customers
from routers.media_monthly_workflow import router
from services import media_monthly_workflow as service, media_monthly as monthly_service, google_business_scheduler as worker, media_operations as media
from test_media_monthly import monthly, generated, PREFIX
from test_google_business import gbp_env, OWNER, OPS, SECOND_OWNER

NOW = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def pipeline(monthly, monkeypatch):
    env = monthly; env.clock = NOW
    monkeypatch.setattr(monthly_service, "now", lambda: env.clock)
    monkeypatch.setattr(env.service, "now", lambda: env.clock)
    monkeypatch.setattr(media, "now", lambda: env.clock)
    monkeypatch.setenv("T24_GBP_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("T24_GBP_SCHEDULER_ACTIVATION_FROM", (NOW - timedelta(days=1)).isoformat())
    env.monthly_client._transport.app.include_router(router)
    async with env.sessions() as db:
        binding = await db.get(env.Binding, 2)
        binding.connection_id = 1; binding.customer_name = "Northern Pasta"; binding.title = "Northern Pasta"
        binding.primary_operator_id = 1; binding.primary_operator_name = OWNER.name; binding.lifecycle = "active"
        material = await db.get(Material, 203)
        material.approval_status = "pending"; material.copyright_status = "unknown"
        # These metadata predate the fixed image in production; restore the
        # exact source descriptor after test-only initial mutation.
        await db.commit()
        from models.media_publication_images import MediaPublicationImage as Image
        image = await db.get(Image, env.version["id"])
        from services.media_publication_images import source_fingerprint
        image.source_fingerprint = source_fingerprint(material)
        await db.commit()
    env.run, env.generate_request = await generated(env, images=[{"material_id": 203, "image_version_id": env.version["id"], "menu_item_id": 201, "quality_confirmed": True}])
    env.url = PREFIX + "/runs/" + str(env.run["id"])
    env.before_ai_calls = len(env.monthly_state.calls)
    yield env


async def view(env):
    response = await env.monthly_client.get(env.url + "/workflow")
    assert response.status_code == 200, response.text
    return response.json()


async def prepare(env, **updates):
    current = await view(env)
    body = {"request_id": str(uuid4()), "expected_run_revision": current["run_revision"],
        "expected_workflow_revision": current["workflow"]["revision"] if current["workflow"] else 0,
        "items": [{"item_id": item["item_id"], "image_version_id": env.version["id"], "rights_confirmed": True} for item in current["items"]], "facts_confirmed": True, **updates}
    response = await env.monthly_client.post(env.url + "/prepare", json=body)
    assert response.status_code == 200, response.text
    return response.json(), body


async def reviewed(env):
    prepared, _ = await prepare(env)
    body = {"request_id": str(uuid4()), "expected_revision": prepared["workflow"]["revision"], "preview_hash": prepared["workflow"]["preview_hash"], "confirmed": True}
    response = await env.monthly_client.post(env.url + "/review", json=body)
    assert response.status_code == 200, response.text
    return response.json(), body


async def enable_delivery(env):
    from services import media_publication_images as images
    async with env.sessions() as db:
        await images.set_delivery_policy(db, OWNER, enabled=True, public_delivery_confirmed=True)


async def scheduled(env):
    reviewed_data, _ = await reviewed(env); await enable_delivery(env)
    body = {"request_id": str(uuid4()), "expected_revision": reviewed_data["workflow"]["revision"], "preview_hash": reviewed_data["workflow"]["preview_hash"],
        "publication_confirmed": True, "confirmation_version": "monthly-publication-v1"}
    response = await env.monthly_client.post(env.url + "/schedule", json=body)
    assert response.status_code == 200, response.text
    return response.json(), body


async def counts(env):
    async with env.sessions() as db:
        return {model.__tablename__: await db.scalar(select(func.count()).select_from(model)) for model in (Task, Event, Schedule, Action, Delivery, Workflow, Request)}


@pytest.mark.asyncio
async def test_prepare_preserves_polished_copy_and_original_material_metadata_no_public_artifacts(pipeline):
    env = pipeline; before = await counts(env)
    data, body = await prepare(env)
    assert data["workflow"]["status"] == "prepared" and not data["source_stale"]
    assert all(not item["quality_warnings"] for item in data["items"])
    assert [item["content"] for item in data["items"]] == [item["content"] for item in env.run["items"]]
    assert data["capabilities"]["can_review"] and not data["capabilities"]["can_schedule"]
    assert data["delivery"]["enabled"] is False
    assert len(env.monthly_state.calls) == env.before_ai_calls
    assert not env.fake.writes and not env.fake.reads
    after = await counts(env)
    for name in (Task.__tablename__, Event.__tablename__, Schedule.__tablename__, Action.__tablename__, Delivery.__tablename__): assert after[name] == before[name]
    async with env.sessions() as db:
        material = await db.get(Material, 203)
        assert material.approval_status == "pending" and material.copyright_status == "unknown"
        assert (await db.execute(text("SELECT amount,closing_state,commission_owner FROM financial_canary"))).one() == ("199.00", "closed", "original-owner")
    assert "SECRET-PRIVATE" not in str(data) and "SYNTHETIC-API-SECRET" not in str(data)
    again = await env.monthly_client.post(env.url + "/prepare", json=body)
    assert again.json() == data


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", [OPS, SECOND_OWNER])
async def test_other_employee_or_owner_cannot_read_or_mutate_owner_packet(pipeline, actor):
    env = pipeline; env.user = actor
    assert (await env.monthly_client.get(env.url + "/workflow")).status_code in {403, 404}
    alerts = await env.monthly_client.get(PREFIX + "/customers/20/workflow-alerts")
    if actor is SECOND_OWNER: assert alerts.status_code == 200 and alerts.json()["items"] == [] and alerts.json()["run_id"] is None
    else: assert alerts.status_code in {403, 404}
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_review_uses_native_submit_approve_events_and_still_no_schedule_lease_or_action(pipeline):
    env = pipeline; data, body = await reviewed(env)
    assert data["workflow"]["status"] == "reviewed" and len({i["task_id"] for i in data["items"]}) == 12
    async with env.sessions() as db:
        tasks = list((await db.scalars(select(Task))).all())
        assert all(task.status == "ready" and task.revision == 3 for task in tasks)
        for task in tasks:
            events = list((await db.scalars(select(Event).where(Event.task_id == task.id).order_by(Event.revision))).all())
            assert [event.action for event in events] == ["create", "submit", "approve"]
            assert events[-1].snapshot["publication_image"]["image_sha256"] == env.version["image_sha256"]
    count = await counts(env)
    assert count[Schedule.__tablename__] == count[Action.__tablename__] == count[Delivery.__tablename__] == 0
    replay = await env.monthly_client.post(env.url + "/review", json=body)
    assert replay.json() == data and (await counts(env))[Task.__tablename__] == 12
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_mid_review_failure_rolls_back_every_task_event_and_receipt(pipeline, monkeypatch):
    env = pipeline; data, _ = await prepare(env); actual = media.transition_task_locked; seen = []
    async def fail(db, ctx, task_id, **kw):
        seen.append((task_id, kw["action"]))
        if len(seen) == 13: raise HTTPException(409, "synthetic validation changed")
        return await actual(db, ctx, task_id, **kw)
    monkeypatch.setattr(media, "transition_task_locked", fail)
    response = await env.monthly_client.post(env.url + "/review", json={"request_id": str(uuid4()), "expected_revision": data["workflow"]["revision"], "preview_hash": data["workflow"]["preview_hash"], "confirmed": True})
    assert response.status_code == 409
    count = await counts(env); assert count[Task.__tablename__] == count[Event.__tablename__] == 0
    assert (await view(env))["workflow"]["status"] == "prepared"


@pytest.mark.asyncio
async def test_copy_change_invalidates_old_packet_then_reprepare_keeps_new_copy_without_ai(pipeline):
    env = pipeline; before, _ = await prepare(env); item = env.run["items"][0]
    response = await env.monthly_client.patch(env.url + "/items/" + str(item["id"]), json={"expected_revision": item["revision"], "title": "Confirmed noodle menu", "content": "Explore Beef noodles at Northern Pasta in Houston.", "owner_summary": "仅使用已确认菜单及店名。"})
    assert response.status_code == 200
    assert (await view(env))["source_stale"]
    after, _ = await prepare(env)
    assert after["items"][0]["content"] == "Explore Beef noodles at Northern Pasta in Houston."
    assert before["workflow"]["preview_hash"] != after["workflow"]["preview_hash"]
    assert len(env.monthly_state.calls) == env.before_ai_calls


@pytest.mark.asyncio
async def test_cancel_review_returns_same_native_tasks_and_fences_historical_receipt(pipeline):
    env = pipeline; data, review_body = await reviewed(env)
    response = await env.monthly_client.post(env.url + "/cancel", json={"request_id": str(uuid4()), "expected_revision": data["workflow"]["revision"], "reason": "重新核对素材"})
    assert response.status_code == 200, response.text
    assert response.json()["workflow"]["status"] == "cancelled"
    assert (await env.monthly_client.get(PREFIX + "/workflow-requests/" + review_body["request_id"])).status_code == 409
    next_data, _ = await reviewed(env)
    assert {item["task_id"] for item in next_data["items"]} == {item["task_id"] for item in data["items"]}
    assert (await counts(env))[Task.__tablename__] == 12


@pytest.mark.asyncio
async def test_actual_schedule_requires_separate_consent_delivery_and_all12_atomic_jobs(pipeline):
    env = pipeline; data, _ = await reviewed(env)
    body = {"request_id": str(uuid4()), "expected_revision": data["workflow"]["revision"], "preview_hash": data["workflow"]["preview_hash"], "publication_confirmed": True, "confirmation_version": "monthly-publication-v1"}
    denied = await env.monthly_client.post(env.url + "/schedule", json=body)
    assert denied.status_code == 409 and (await counts(env))[Schedule.__tablename__] == 0
    await enable_delivery(env)
    false = await env.monthly_client.post(env.url + "/schedule", json={**body, "publication_confirmed": False})
    assert false.status_code == 422
    response = await env.monthly_client.post(env.url + "/schedule", json=body)
    assert response.status_code == 200, response.text
    scheduled_data = response.json()
    assert scheduled_data["workflow"]["preview_hash"] == data["workflow"]["preview_hash"]
    assert scheduled_data["counts"]["scheduled"] == 12
    assert all(item["schedule"]["planned_at"] == item["proposed_publish_at"] for item in scheduled_data["items"])
    assert (await counts(env))[Schedule.__tablename__] == 12 and not env.fake.writes
    assert (await env.monthly_client.post(env.url + "/schedule", json=body)).json() == scheduled_data


@pytest.mark.asyncio
async def test_mid_schedule_failure_leaves_zero_native_jobs(pipeline, monkeypatch):
    env = pipeline; data, _ = await reviewed(env); await enable_delivery(env)
    actual = service.management.schedule_locked; seen = []
    async def fail(db, ctx, binding_id, **kw):
        seen.append(kw["task_id"])
        if len(seen) == 10: raise HTTPException(409, "synthetic schedule conflict")
        return await actual(db, ctx, binding_id, **kw)
    monkeypatch.setattr(service.management, "schedule_locked", fail)
    response = await env.monthly_client.post(env.url + "/schedule", json={"request_id": str(uuid4()), "expected_revision": data["workflow"]["revision"], "preview_hash": data["workflow"]["preview_hash"], "publication_confirmed": True, "confirmation_version": "monthly-publication-v1"})
    assert response.status_code == 409
    assert (await counts(env))[Schedule.__tablename__] == 0


@pytest.mark.asyncio
async def test_native_direct_publish_and_extra_schedule_cannot_bypass_month_confirmation(pipeline):
    env = pipeline; data, _ = await reviewed(env); await enable_delivery(env); task_id = data["items"][0]["task_id"]
    result = await env.client.post("/api/v1/google-business/bindings/2/posts", json={"request_id": str(uuid4()), "task_id": task_id, "expected_revision": 3, "confirmed": True})
    assert result.status_code == 409, result.text
    async with env.sessions() as db:
        with pytest.raises(HTTPException) as error:
            await service.management.schedule(db, OWNER, 2, request_id=str(uuid4()), task_id=task_id, expected_revision=3,
                planned_at=data["items"][0]["proposed_publish_at"], timezone="America/Chicago")
        assert error.value.status_code == 409
    assert not env.fake.writes and (await counts(env))[Action.__tablename__] == 0


@pytest.mark.asyncio
async def test_due_native_worker_uses_one_send_and_does_not_expire_after_preview24h(pipeline):
    env = pipeline; data, _ = await scheduled(env)
    env.clock = datetime.fromisoformat(data["items"][0]["proposed_publish_at"])
    result = await worker.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    assert result["stage"] == "succeeded", result
    assert len(env.fake.writes) == 1
    await worker.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    assert len(env.fake.writes) == 1 and (await counts(env))[Delivery.__tablename__] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["timeout_after", "definitive"])
async def test_worker_unknown_or_failure_remains_owner_alert_and_never_blind_retry(pipeline, state):
    env = pipeline; data, _ = await scheduled(env); env.fake.failure = state
    env.clock = datetime.fromisoformat(data["items"][0]["proposed_publish_at"])
    await worker.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    await worker.run_tick(sessions=env.sessions, clock=lambda: env.clock + timedelta(seconds=30))
    alert = await env.monthly_client.get(PREFIX + "/customers/20/workflow-alerts")
    assert alert.status_code == 200 and alert.json()["counts"]["attention"] == 1
    assert alert.json()["items"][0]["status"] == ("unknown" if state == "timeout_after" else "failed")
    assert len(env.fake.writes) == 1


@pytest.mark.asyncio
async def test_rejected_post_and_stopped_customer_still_have_readable_owner_alerts(pipeline):
    env = pipeline; data, _ = await scheduled(env); env.fake.post_state = "REJECTED"
    env.clock = datetime.fromisoformat(data["items"][0]["proposed_publish_at"])
    await worker.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    async with env.sessions() as db:
        (await db.get(Customers, 20)).status = "lost"; await db.commit()
    alert = await env.monthly_client.get(PREFIX + "/customers/20/workflow-alerts")
    assert alert.status_code == 200, alert.text
    assert any(row["status"] == "rejected" for row in alert.json()["items"])
    assert alert.json()["counts"]["failed"] == 1
    assert (await view(env))["source_stale"]


@pytest.mark.asyncio
async def test_worker_fences_source_change_before_real_send(pipeline):
    env = pipeline; data, _ = await scheduled(env)
    async with env.sessions() as db:
        item = await db.get(Item, env.run["items"][0]["id"]); item.content = "Different unreviewed copy"; item.revision += 1; await db.commit()
    env.clock = datetime.fromisoformat(data["items"][0]["proposed_publish_at"])
    result = await worker.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    assert result["stage"] == "blocked" and not env.fake.writes


@pytest.mark.asyncio
async def test_cancel_stops_remaining_jobs_and_no_automatic_reactivation(pipeline):
    env = pipeline; data, _ = await scheduled(env)
    cancelled = await env.monthly_client.post(env.url + "/cancel", json={"request_id": str(uuid4()), "expected_revision": data["workflow"]["revision"], "reason": "先暂停本月发布"})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["counts"]["cancelled"] == 12
    env.clock = datetime.fromisoformat(data["items"][0]["proposed_publish_at"])
    await worker.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    assert not env.fake.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["cancel", "copy"])
async def test_revocation_after_durable_reservation_is_checked_again_before_network_and_lease(pipeline, monkeypatch, change):
    env = pipeline; data, _ = await scheduled(env); actual = env.service._reserve
    async def reserve_then_change(db, ctx, *args, **kwargs):
        result = await actual(db, ctx, *args, **kwargs)
        async with env.sessions() as separate:
            if change == "cancel":
                await service.cancel(separate, OWNER, env.run["id"], request_id=str(uuid4()), expected_revision=data["workflow"]["revision"], reason="撤销尚未提交内容")
            else:
                item = await separate.get(Item, env.run["items"][0]["id"]); item.content = "Changed after reservation"; item.revision += 1; await separate.commit()
        return result
    monkeypatch.setattr(env.service, "_reserve", reserve_then_change)
    env.clock = datetime.fromisoformat(data["items"][0]["proposed_publish_at"])
    result = await worker.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    assert result["stage"] == "failed", result
    assert not env.fake.writes and (await counts(env))[Delivery.__tablename__] == 0
    async with env.sessions() as db:
        action = await db.scalar(select(Action)); assert action.dispatch_started_at is None


@pytest.mark.asyncio
async def test_missing_new_schema_blocks_only_marked_monthly_jobs(pipeline):
    env = pipeline; data, _ = await scheduled(env)
    async with env.sessions() as db:
        await db.execute(text("DROP TABLE media_monthly_workflow_requests")); await db.execute(text("DROP TABLE media_monthly_workflows")); await db.commit()
        # An unrelated native task never reads the new workflow schema.
        await service.authorize_schedule(db, schedule=None, task=type("NativeTask", (), {"client_request_id": str(uuid4())})())
    env.clock = datetime.fromisoformat(data["items"][0]["proposed_publish_at"])
    result = await worker.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    assert result["stage"] == "blocked" and not env.fake.writes


@pytest.mark.asyncio
async def test_prepared_material_ack_cannot_override_known_wrong_dish_link(pipeline):
    env = pipeline
    async with env.sessions() as db:
        material = await db.get(Material, 203); material.linked_item_id = 999
        from models.media_publication_images import MediaPublicationImage as Image
        from services.media_publication_images import source_fingerprint
        image = await db.get(Image, env.version["id"]); image.source_fingerprint = source_fingerprint(material)
        await db.commit()
    packet, _ = await prepare(env)
    assert all("其他菜品" in " ".join(item["quality_warnings"]) for item in packet["items"])
    assert not packet["capabilities"]["can_review"]
    denied = await env.monthly_client.post(env.url + "/review", json={"request_id": str(uuid4()), "expected_revision": packet["workflow"]["revision"], "preview_hash": packet["workflow"]["preview_hash"], "confirmed": True})
    assert denied.status_code == 409 and (await counts(env))[Task.__tablename__] == 0


@pytest.mark.asyncio
async def test_nonowner_denied_before_sql_even_if_new_tables_do_not_exist():
    class NoSQL:
        def __getattr__(self, name): raise AssertionError("nonowner touched database")
    with pytest.raises(HTTPException) as caught: await service.get_workflow(NoSQL(), OPS, 1)
    assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_old_monthly_page_retains_readonly_history_when_cooperation_stops(pipeline):
    env = pipeline; await prepare(env)
    async with env.sessions() as db:
        (await db.get(Customers, 20)).status = "lost"; await db.commit()
    setup = await env.monthly_client.get(PREFIX + "/customers/20/setup")
    assert setup.status_code == 200 and not setup.json()["capabilities"]["cooperation_active"] and not setup.json()["capabilities"]["can_generate"]
    assert (await env.monthly_client.get(env.url)).status_code == 200
    current = await view(env)
    assert not current["capabilities"]["can_prepare"] and not current["capabilities"]["can_review"]
    assert any(check["key"] == "binding" and check["state"] == "blocked" for check in current["checks"])


@pytest.mark.asyncio
async def test_revoked_old_image_profile_can_be_rebound_without_losing_copy_or_calling_ai(pipeline):
    env = pipeline; original_copy = [row["content"] for row in env.run["items"]]
    from models.media_publication_images import MediaPublicationImage as Image
    from services import media_publication_images as native_images
    async with env.sessions() as db:
        (await db.get(Image, env.version["id"])).revoked_at = env.clock
        await db.commit()
        raw = (env.root / "20" / "front.png").read_bytes()
        import hashlib
        new_image = await native_images.prepare(db, OWNER, customer_id=20, material_id=203, source_sha256=hashlib.sha256(raw).hexdigest(), rights_basis="client_provided", rights_confirmed=True, request_id=str(uuid4()), body=raw)
    setup = await env.monthly_client.get(PREFIX + "/customers/20/setup")
    assert setup.status_code == 200 and setup.json()["input_hash"] is None and not setup.json()["capabilities"]["can_generate"]
    env.version = new_image
    packet, _ = await prepare(env)
    assert [row["content"] for row in packet["items"]] == original_copy
    assert all(row["image_version_id"] == new_image["id"] for row in packet["items"])
    assert not packet["source_stale"] and packet["capabilities"]["can_review"]
    assert len(env.monthly_state.calls) == env.before_ai_calls


@pytest.mark.asyncio
async def test_late_receipt_recovery_cannot_restore_stale_source_proof(pipeline):
    env = pipeline; packet, body = await prepare(env)
    async with env.sessions() as db:
        item = await db.get(Item, env.run["items"][0]["id"]); item.revision += 1; item.content = "Changed menu copy"; await db.commit()
    recovered = await env.monthly_client.get(PREFIX + "/workflow-requests/" + body["request_id"])
    assert recovered.status_code == 409
    current = await view(env)
    assert current["source_stale"] and not current["capabilities"]["can_review"]


@pytest.mark.asyncio
async def test_expired_packet_cannot_review_or_schedule_but_copy_can_be_prepared_again(pipeline):
    env = pipeline; packet, _ = await prepare(env); env.clock += timedelta(hours=25)
    rejected = await env.monthly_client.post(env.url + "/review", json={"request_id": str(uuid4()), "expected_revision": packet["workflow"]["revision"], "preview_hash": packet["workflow"]["preview_hash"], "confirmed": True})
    assert rejected.status_code == 409 and (await counts(env))[Task.__tablename__] == 0
    next_packet, _ = await prepare(env)
    assert next_packet["items"][0]["content"] == packet["items"][0]["content"]
    assert next_packet["capabilities"]["can_review"]


@pytest.mark.asyncio
async def test_simultaneous_whole_month_review_same_request_creates_only_twelve_tasks(pipeline):
    env = pipeline; packet, _ = await prepare(env)
    body = {"request_id": str(uuid4()), "expected_revision": packet["workflow"]["revision"], "preview_hash": packet["workflow"]["preview_hash"], "confirmed": True}
    responses = await asyncio.gather(*[env.monthly_client.post(env.url + "/review", json=body) for _ in range(2)])
    assert all(response.status_code == 200 for response in responses)
    assert responses[0].json() == responses[1].json() and (await counts(env))[Task.__tablename__] == 12


@pytest.mark.asyncio
async def test_adding_unselected_fixed_image_version_does_not_invalidate_selected_month(pipeline):
    env = pipeline; packet, _ = await prepare(env)
    from services import media_publication_images as native_images
    import hashlib
    async with env.sessions() as db:
        raw = (env.root / "20" / "front.png").read_bytes()
        new_image = await native_images.prepare(db, OWNER, customer_id=20, material_id=203, source_sha256=hashlib.sha256(raw).hexdigest(), rights_basis="client_provided", rights_confirmed=True, request_id=str(uuid4()), body=raw)
    assert new_image["id"] != env.version["id"]
    current = await view(env)
    assert current["workflow"]["preview_hash"] == packet["workflow"]["preview_hash"] and not current["source_stale"]
    assert all(item["image_version_id"] == env.version["id"] for item in current["items"])


@pytest.mark.asyncio
async def test_stopped_binding_does_not_prevent_owner_revoking_remaining_blocked_jobs(pipeline):
    env = pipeline; data, _ = await scheduled(env)
    async with env.sessions() as db:
        binding = await db.get(env.Binding, 2); binding.active = False; binding.lifecycle = "stopped"; binding.revision += 1
        jobs = list((await db.scalars(select(Schedule).order_by(Schedule.id))).all())
        jobs[0].status = "blocked"; jobs[1].status = "missed"
        for row in jobs[2:]: row.status = "cancelled"
        (await db.get(Customers, 20)).status = "lost"
        await db.commit()
    cancelled = await env.monthly_client.post(env.url + "/cancel", json={"request_id": str(uuid4()), "expected_revision": data["workflow"]["revision"], "reason": "合作停止撤销剩余"})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["workflow"]["status"] == "cancelled" and cancelled.json()["counts"]["cancelled"] == 12
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_cancel_after_public_submission_preserves_frozen_history_and_original_store(pipeline):
    env = pipeline; data, _ = await scheduled(env)
    env.clock = datetime.fromisoformat(data["items"][0]["proposed_publish_at"])
    await worker.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    cancelled = await env.monthly_client.post(env.url + "/cancel", json={"request_id": str(uuid4()), "expected_revision": data["workflow"]["revision"], "reason": "停止剩余排期"})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["counts"]["succeeded"] == 1 and cancelled.json()["counts"]["cancelled"] == 11
    async with env.sessions() as db:
        binding = await db.get(env.Binding, 2); binding.title = "Newly rebound store label"; binding.revision += 1
        item = await db.get(Item, env.run["items"][0]["id"]); item.content = "Changed database copy after publication"; item.revision += 1; await db.commit()
    current = await view(env)
    assert current["binding"]["title"] == "Northern Pasta" and current["current_binding"]["title"] == "Newly rebound store label"
    assert current["items"][0]["content"] == data["items"][0]["content"] and current["history_frozen"]
    assert not current["capabilities"]["can_prepare"]
    item = env.run["items"][0]
    response = await env.monthly_client.patch(env.url + "/items/" + str(item["id"]), json={"expected_revision": 2, "title": "New title", "content": "New content", "owner_summary": "修改文案"})
    assert response.status_code == 409
