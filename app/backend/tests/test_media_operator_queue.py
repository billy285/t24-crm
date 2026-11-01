"""30-store local queue and generic monthly workflow; provider is a fixture fake."""
from datetime import datetime, timedelta, timezone
import hashlib
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import event, func, select
from models.customers import Customers
from models.customer_menu_items import Customer_menu_items as Menu
from models.customer_materials import Customer_materials as Material
from models.media_monthly import MediaMonthlyProfile as Profile, MediaMonthlyRun as Run, MediaMonthlyItem as Item
from models.media_operations import MediaOperationTask as Task
from models.google_business import GoogleBusinessSchedule as Schedule
from services import media_monthly as service, media_workspace as portfolio, media_publication_images as images, media_operations as media, google_business_scheduler as worker
from routers.media_monthly_workflow import router
from test_google_business import gbp_env, OWNER, OPS
from test_media_monthly import monthly, png, PREFIX, generate_body, generated, profile
from test_media_workspace import projection

PERIOD = {"start": "2026-11-30T16:00:00Z", "end": "2026-12-31T16:00:00Z"}
RULES = {"timezone": "America/Los_Angeles", "weekdays": [1, 5], "local_time": "10:30", "posts_per_week": 2, "language": "en", "include_prices": False, "generic_mode": False, "forbidden_claims": []}


def test_generic_rules_legacy_dates_leap_year_and_dst():
    assert len(service.slots("2026-12", RULES)) == 8
    legacy = service.slots("2026-11", {**RULES, "timezone": "America/Chicago", "weekdays": [2, 4, 6], "local_time": "11:00", "posts_per_week": 3})
    assert len(legacy) == 12 and legacy[0]["proposed_publish_at"] == "2026-11-03T17:00:00+00:00"
    assert len(service.slots("2028-02", {**RULES, "weekdays": list(range(1, 8)), "posts_per_week": 7})) == 29
    invalid = [("2026-13", {}), ("2100-01", {}), ("2026-11", {"weekdays": [1, 1]}), ("2026-11", {"timezone": "../private"}), ("2026-11", {"posts_per_week": 7}),
        ("2026-11", {"timezone": "America/New_York", "weekdays": [7], "posts_per_week": 1, "local_time": "01:30"}),
        ("2026-03", {"timezone": "America/New_York", "weekdays": [7], "posts_per_week": 1, "local_time": "02:30"})]
    for month, changes in invalid:
        with pytest.raises(HTTPException) as error: service.slots(month, {**RULES, **changes})
        assert error.value.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["sales", "finance", "operations", "admin", "customer_service"])
async def test_owner_boundary_before_database(role):
    class NoDb:
        def __getattr__(self, key): raise AssertionError("Deny before SQL")
    for write in (False, True):
        with pytest.raises(HTTPException) as error: await service.context(NoDb(), SimpleNamespace(role=role), 10, write=write)
        assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_other_merchant_december_eight_items_review_then_explicit_schedule(monthly, monkeypatch):
    env = monthly; env.clock = datetime(2026, 11, 1, tzinfo=timezone.utc)
    for component in (service, media, env.service): monkeypatch.setattr(component, "now", lambda: env.clock)
    monkeypatch.setenv("T24_GBP_SCHEDULER_ENABLED", "true"); monkeypatch.setenv("T24_GBP_SCHEDULER_ACTIVATION_FROM", (env.clock - timedelta(days=1)).isoformat())
    env.monthly_client._transport.app.include_router(router)
    (env.root / "10").mkdir(); data = png(); (env.root / "10" / "front.png").write_bytes(data)
    async with env.sessions() as db:
        binding = await db.get(env.Binding, 1); binding.primary_operator_id = 1; binding.primary_operator_name = OWNER.name
        db.add(Menu(id=301, customer_id=10, user_id="1", name="Confirmed noodles", category="Menu", status="active"))
        db.add(Material(id=303, user_id="1", customer_id=10, title="Actual storefront", material_type="image", visibility="team", content_type="image/png", source_type="upload", file_path="10/front.png", approval_status="approved", copyright_status="client_provided", linked_item_id=301))
        await db.commit()
        version = await images.prepare(db, OWNER, customer_id=10, material_id=303, source_sha256=hashlib.sha256(data).hexdigest(), rights_basis="client_provided", rights_confirmed=True, request_id=str(uuid4()), body=data)
    payload = {"expected_revision": 0, "public_facts": {"public_name": "Other Merchant", "location": "Los Angeles, CA", "highlights": ["Confirmed menu selection"]}, "rules": RULES, "menu_item_ids": [301], "images": [{"material_id": 303, "image_version_id": version["id"], "menu_item_id": 301, "quality_confirmed": False}], "confirmed_facts": True}
    response = await env.monthly_client.put(PREFIX + "/customers/10/profile?month=2026-12", json=payload)
    assert response.status_code == 200, response.text
    setup = response.json(); assert setup["month"] == "2026-12" and len(setup["slots"]) == 8
    created = await env.monthly_client.post(PREFIX + "/customers/10/runs", json=generate_body(setup, month="2026-12"))
    assert created.status_code == 201, created.text
    run = created.json(); assert run["customer_id"] == 10 and run["month"] == "2026-12" and len(run["items"]) == 8
    url = PREFIX + f"/runs/{run['id']}"
    assert (await env.monthly_client.get(url)).json()["source_stale"] is False
    assert [r["id"] for r in (await env.monthly_client.get(PREFIX + "/customers/10/runs?month=2026-12")).json()["items"]] == [run["id"]]
    assert (await env.monthly_client.get(PREFIX + "/customers/10/runs?month=2026-11")).json()["items"] == []
    view = (await env.monthly_client.get(url + "/workflow")).json(); assert view["rules"] == RULES and view["customer_id"] == 10
    prepared = await env.monthly_client.post(url + "/prepare", json={"request_id": str(uuid4()), "expected_run_revision": run["revision"], "expected_workflow_revision": 0, "items": [{"item_id": row["item_id"], "image_version_id": version["id"], "rights_confirmed": True} for row in view["items"]], "facts_confirmed": True})
    assert prepared.status_code == 200, prepared.text
    packet = prepared.json()["workflow"]
    reviewed = await env.monthly_client.post(url + "/review", json={"request_id": str(uuid4()), "expected_revision": packet["revision"], "preview_hash": packet["preview_hash"], "confirmed": True})
    assert reviewed.status_code == 200, reviewed.text
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Task).where(Task.customer_id == 10)) == 8
        assert await db.scalar(select(func.count()).select_from(Schedule)) == 0
        await images.set_delivery_policy(db, OWNER, enabled=True, public_delivery_confirmed=True)
    packet = reviewed.json()["workflow"]; body = {"request_id": str(uuid4()), "expected_revision": packet["revision"], "preview_hash": packet["preview_hash"], "confirmation_version": "monthly-publication-v1", "publication_confirmed": False}
    assert (await env.monthly_client.post(url + "/schedule", json=body)).status_code == 422
    body["publication_confirmed"] = True; scheduled = await env.monthly_client.post(url + "/schedule", json=body)
    assert scheduled.status_code == 200, scheduled.text
    assert not env.fake.writes
    env.clock = datetime.fromisoformat(run["items"][0]["proposed_publish_at"]); await worker.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    assert len(env.fake.writes) == 1
    assert (await env.monthly_client.get(PREFIX + "/customers/10/workflow-alerts?month=2026-11")).json()["run_id"] is None
    env.user = OPS
    assert (await env.monthly_client.get(url + "/workflow")).status_code == 403
    assert (await env.monthly_client.get(PREFIX + "/customers/10/setup?month=2026-12")).status_code == 403


@pytest.mark.asyncio
async def test_thirty_queue_entries_exact_month_no_provider_or_dml(projection, monkeypatch):
    env = projection; now = datetime(2026, 12, 1, tzinfo=timezone.utc); monkeypatch.setattr(portfolio, "now", lambda: now)
    async with env.sessions() as db:
        for n in range(30):
            identity = 1000 + n
            db.add(Customers(id=identity, business_name=f"Queue Merchant {n:02}", contact_name="Synthetic", phone="111", status="closed"))
            db.add(env.Binding(id=identity, customer_id=identity, customer_name=f"Queue Merchant {n:02}", connection_id=1, location_name=f"accounts/100/locations/{10000 + identity}", title=f"Queue Merchant {n:02}", address="", active=True, revision=1, primary_operator_id=1, created_by_id=1, request_id=str(uuid4())))
            db.add(Material(id=identity + 10000, user_id="1", customer_id=identity, title="Shared reference", material_type="image", visibility="team", content_type="image/png"))
            db.add(Menu(id=identity, customer_id=identity, user_id="1", name="Confirmed menu", status="active"))
            db.add(Profile(id=identity, owner_id=1, customer_id=identity, revision=1, public_facts={"public_name": "Merchant", "location": "CA", "highlights": ["Confirmed"]}, rules=RULES, menu_item_ids=[identity], images=[], confirmed_at=now, created_at=now, updated_at=now))
            slots = service.slots("2026-12", RULES); run_id = identity * 10
            db.add(Run(id=run_id, owner_id=1, customer_id=identity, profile_id=identity, request_id=str(uuid4()), fingerprint="f" * 64, input_hash="a" * 64, month="2026-12", snapshot={"profile_revision": 1, "public_facts": {"public_name": "Merchant", "location": "CA", "highlights": ["Confirmed"]}, "rules": RULES, "menu_items": [{"id": identity}], "images": [], "slots": slots}, runtime={"fingerprint": "b" * 64}, consent={}, status="generated", revision=2, ai_used=True, message="Fixture saved draft", created_at=now, updated_at=now))
            for slot in slots:
                db.add(Item(run_id=run_id, slot_id=slot["slot_id"], proposed_publish_at=datetime.fromisoformat(slot["proposed_publish_at"]), timezone=RULES["timezone"], title="Confirmed menu", content="Confirmed merchant information", owner_summary="已确认门店事实", material_id=identity + 10000, menu_item_ids=[identity], quality_warnings=[], revision=1, copy_hash="c" * 64, created_at=now, updated_at=now))
        await db.commit()
    statements = []
    def audit(conn, cursor, statement, parameters, context, executemany): statements.append(statement)
    event.listen(env.engine.sync_engine, "before_cursor_execute", audit)
    try:
        response = await env.projection.get("/api/v1/media-workspace/merchants", params={**PERIOD, "q": "Queue Merchant", "limit": 100})
        assert response.status_code == 200, response.text
        result = response.json(); assert result["total"] == 30 and len(result["items"]) == 30
        for item in result["items"]:
            queue = item["work_queue"]
            assert queue["month"] == "2026-12" and queue["target"] == 8 and queue["prepared"] == 8 and queue["scheduled"] == queue["published"] == 0
            assert queue["can_prepare_monthly"] and queue["next_action"]["kind"] == "monthly" and queue["next_action"]["run_id"] == item["id"] * 10
            assert queue["basis"] == "monthly_plan"
            assert queue["readiness"] == "needs_setup" and any(c["key"] == "images" and c["state"] == "missing" for c in queue["checks"])
        assert len(statements) < 90, len(statements)
        assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")) for s in statements)
    finally: event.remove(env.engine.sync_engine, "before_cursor_execute", audit)
    assert not env.fake.reads and not env.fake.writes
    custom = await env.projection.get("/api/v1/media-workspace/merchants", params={"start": "2026-12-02T00:00:00Z", "end": "2026-12-04T00:00:00Z", "q": "Queue Merchant", "limit": 100})
    assert all(r["work_queue"]["month"] is None and r["work_queue"]["target"] is None for r in custom.json()["items"])
    env.user = OPS; staff = await env.projection.get("/api/v1/media-workspace/merchants", params=PERIOD)
    assert staff.status_code == 200 and "Queue Merchant" not in staff.text
    for row in staff.json()["items"]:
        queue = row["work_queue"]
        assert queue["target"] is None and not queue["can_prepare_monthly"] and queue["next_action"]["kind"] != "monthly" and "run_id" not in queue["next_action"]


@pytest.mark.asyncio
async def test_archive_unused_draft_preserves_copy_recovers_once_and_allows_changed_input(monthly):
    env = monthly; run, _ = await generated(env)
    body = {"request_id": str(uuid4()), "expected_revision": run["revision"], "confirmed": True}
    url = PREFIX + f"/runs/{run['id']}/archive"
    archived = await env.monthly_client.post(url, json=body)
    assert archived.status_code == 200, archived.text
    result = archived.json(); assert result["status"] == "archived" and result["items"] == run["items"]
    assert (await env.monthly_client.post(url, json=body)).json() == result
    assert (await env.monthly_client.get(PREFIX + "/requests/" + body["request_id"])).json() == result
    assert (await env.monthly_client.post(url, json={**body, "expected_revision": result["revision"]})).status_code == 409
    changed = profile(env, expected_revision=1); changed["public_facts"]["highlights"].append("Confirmed menu choices")
    setup = await env.monthly_client.put(PREFIX + "/customers/20/profile", json=changed)
    assert setup.status_code == 200
    new_body = generate_body(setup.json())
    assert (await env.monthly_client.post(PREFIX + "/customers/20/runs", json={**new_body, "request_id": body["request_id"]})).status_code == 409
    newer = await env.monthly_client.post(PREFIX + "/customers/20/runs", json=new_body)
    assert newer.status_code == 201 and newer.json()["id"] != run["id"] and newer.json()["status"] == "generated"
    assert len(env.monthly_state.calls) == 2 and not env.fake.writes
    env.user = OPS
    assert (await env.monthly_client.post(url, json=body)).status_code == 403


@pytest.mark.asyncio
async def test_archive_denies_unknown_and_any_existing_workflow(monthly):
    env = monthly; env.monthly_client._transport.app.include_router(router)
    run, _ = await generated(env); url = PREFIX + f"/runs/{run['id']}"
    async with env.sessions() as db:
        from models.media_monthly import MediaMonthlyRun
        stored = await db.get(MediaMonthlyRun, run["id"]); stored.status = "unknown"; await db.commit()
    body = {"request_id": str(uuid4()), "expected_revision": run["revision"], "confirmed": True}
    assert (await env.monthly_client.post(url + "/archive", json=body)).status_code == 409
    async with env.sessions() as db:
        from models.media_monthly import MediaMonthlyRun
        stored = await db.get(MediaMonthlyRun, run["id"]); stored.status = "generated"; await db.commit()
    view = (await env.monthly_client.get(url + "/workflow")).json()
    prepared = await env.monthly_client.post(url + "/prepare", json={"request_id": str(uuid4()), "expected_run_revision": run["revision"], "expected_workflow_revision": 0, "items": [{"item_id": r["item_id"], "image_version_id": env.version["id"], "rights_confirmed": True} for r in view["items"]], "facts_confirmed": True})
    assert prepared.status_code == 200, prepared.text
    assert (await env.monthly_client.post(url + "/archive", json=body)).status_code == 409
    assert not env.fake.writes
