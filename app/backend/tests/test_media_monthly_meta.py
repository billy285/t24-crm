"""Synthetic whole-month Meta: no live provider/account/data writes."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
import pytest_asyncio
from sqlalchemy import select, func, text
from models.meta_business import MetaBusinessBinding as ReadBinding
from models.meta_operations import MetaOperationsBinding as Binding, MetaOperationsCredential as Credential, MetaOperationsSchedule as Schedule, MetaOperationsDraft as Draft, MetaOperationsAction as Action
from models.media_monthly import MediaMonthlyRun as Run, MediaMonthlyItem as Item
from models.media_operations import MediaOperationTask as Task
from models.media_publication_images import MediaPublicationImage as Image
from routers.media_monthly_workflow import router as workflow_router
from routers.media_workspace import router as workspace_router
from services import media_monthly as monthly_service, meta_operations as native, meta_operations_provider as provider, meta_operations_scheduler as worker
from test_media_monthly import monthly, profile, generate_body, PREFIX
from test_meta_operations import ops_env
from test_meta_business import meta_env
from test_google_business import gbp_env, OWNER, OPS, SECOND_OWNER

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def meta_pipeline(monthly, ops_env, monkeypatch):
    env = monthly; env.clock = NOW
    monkeypatch.setattr(monthly_service, "now", lambda: env.clock)
    monkeypatch.setattr(native, "now", lambda: env.clock)
    monkeypatch.setattr(provider.OpsClient, "access", lambda self: ({}, set(provider.SCOPES)))
    monkeypatch.setenv("T24_META_OPS_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("JWT_SECRET_KEY", "synthetic-monthly-meta-signing-key-32")
    env.ops.execution = False
    async with env.sessions() as db:
        credential = await db.get(Credential, 1); credential.granted_scopes = sorted(provider.SCOPES)
        for identity, platform in [(201, "facebook"), (202, "instagram")]:
            fields = dict(id=identity, owner_id=1, customer_id=20, customer_name="Synthetic Northern", connection_id=1, connection_revision=1,
                platform=platform, external_id=str(identity), page_id="201", asset_name="Synthetic Northern", active=True, revision=1, created_at=NOW, updated_at=NOW)
            db.add(ReadBinding(**fields)); db.add(Binding(**fields, source_binding_id=identity, credential_id=1))
        await db.commit()
    env.monthly_client._transport.app.include_router(workflow_router)
    env.monthly_client._transport.app.include_router(workspace_router)
    yield env


async def generated(env, platform="facebook", **changes):
    response = await env.monthly_client.put(PREFIX + "/customers/20/profile", params={"platform": platform}, json=profile(env, **changes))
    assert response.status_code == 200, response.text
    setup = response.json(); body = generate_body(setup, platform=platform)
    response = await env.monthly_client.post(PREFIX + "/customers/20/runs", json=body)
    assert response.status_code == 201, response.text
    return response.json(), body


async def prepared(env, platform="facebook"):
    run, _ = await generated(env, platform); url = PREFIX + f"/runs/{run['id']}"
    data = (await env.monthly_client.get(url + "/workflow")).json()
    body = {"request_id": str(uuid4()), "expected_run_revision": run["revision"], "expected_workflow_revision": 0,
        "items": [{"item_id": r["item_id"], "image_version_id": env.version["id"], "rights_confirmed": True} for r in data["items"]], "facts_confirmed": True}
    response = await env.monthly_client.post(url + "/prepare", json=body)
    assert response.status_code == 200, response.text
    return url, response.json(), body


async def reviewed(env, platform="facebook"):
    url, data, _ = await prepared(env, platform)
    body = {"request_id": str(uuid4()), "expected_revision": data["workflow"]["revision"], "preview_hash": data["workflow"]["preview_hash"], "confirmed": True}
    response = await env.monthly_client.post(url + "/review", json=body)
    assert response.status_code == 200, response.text
    return url, response.json(), body


def schedule_body(data, public=False):
    return {"request_id": str(uuid4()), "expected_revision": data["workflow"]["revision"], "preview_hash": data["workflow"]["preview_hash"], "publication_confirmed": public, "confirmation_version": "monthly-publication-v1"}


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["facebook", "instagram"])
async def test_private_prepare_review_schedule_exact_jpeg_and_receipt(meta_pipeline, platform):
    env = meta_pipeline; url, data, review_body = await reviewed(env, platform)
    assert data["platform"] == platform and data["workflow"]["status"] == "reviewed" and not data["source_stale"]
    assert len({r["draft_id"] for r in data["items"]}) == 12
    assert all(r["task_id"] is None and r["meta_media"]["sha256"] != r["image_sha256"] for r in data["items"])
    assert data["capabilities"]["can_schedule"] and not data["scheduler"]["enabled"]
    assert (await env.monthly_client.post(url + "/review", json=review_body)).json() == data
    preview = await env.ops_client.get(data["items"][0]["meta_media"]["preview_path"])
    assert preview.status_code == 200 and preview.content.startswith(b"\xff\xd8")
    assert (await env.monthly_client.post(url + "/schedule", json=schedule_body(data, True))).status_code == 409
    body = schedule_body(data); response = await env.monthly_client.post(url + "/schedule", json=body)
    assert response.status_code == 200, response.text
    saved = response.json(); assert saved["workflow"]["status"] == "schedule_prepared" and saved["counts"]["prepared"] == 12
    assert not saved["capabilities"]["can_activate"]
    assert (await env.monthly_client.post(url + "/schedule", json=body)).json() == saved
    assert (await env.monthly_client.get(PREFIX + "/workflow-requests/" + body["request_id"])).json() == saved
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Schedule)) == 12
        assert await db.scalar(select(func.count()).select_from(Draft)) == 12
        assert await db.scalar(select(func.count()).select_from(Task)) == 0
        assert await db.scalar(select(func.count()).select_from(Action)) == 0
        assert (await db.execute(text("SELECT amount,closing_state,commission_owner FROM financial_canary"))).one() == ("199.00", "closed", "original-owner")
    merchants = await env.monthly_client.get("/api/v1/media-workspace/merchants", params={"start": "2026-10-31T16:00:00Z", "end": "2026-11-30T16:00:00Z", "customer_id": 20, "platform": platform})
    assert merchants.status_code == 200, merchants.text
    shop = merchants.json()["items"][0]
    assert shop["in_review"] >= 1 and any(r["code"] == "review" for r in shop["issues"])
    assert shop["work_queue"]["schedule_prepared"] == 12 and shop["work_queue"]["scheduled"] == 0
    assert await worker.run_tick(sessions=env.sessions) == {"stage": "disabled", "processed": 0}
    assert not env.ops.reads and not env.ops.writes


@pytest.mark.asyncio
async def test_platform_profile_and_dedup_preserve_google_hash(meta_pipeline):
    env = meta_pipeline
    google, _ = await generated(env, "google_business")
    facebook, fbbody = await generated(env, "facebook")
    instagram, _ = await generated(env, "instagram")
    assert len({r["input_hash"] for r in (google, facebook, instagram)}) == 3
    before_google = (await env.monthly_client.get(PREFIX + "/customers/20/setup")).json()
    before_instagram = (await env.monthly_client.get(PREFIX + "/customers/20/setup", params={"platform": "instagram"})).json()
    new_rules = {**before_instagram["profile"]["rules"], "weekdays": [1], "posts_per_week": 1}
    edited = await env.monthly_client.put(PREFIX + "/customers/20/profile", params={"platform": "facebook"}, json=profile(env, expected_revision=1, rules=new_rules))
    assert edited.status_code == 200
    assert (await env.monthly_client.get(PREFIX + "/customers/20/setup")).json()["input_hash"] == before_google["input_hash"]
    assert (await env.monthly_client.get(PREFIX + "/customers/20/setup", params={"platform": "instagram"})).json()["input_hash"] == before_instagram["input_hash"]
    for platform, expected in [("google_business", google), ("facebook", facebook), ("instagram", instagram)]:
        rows = (await env.monthly_client.get(PREFIX + "/customers/20/runs", params={"platform": platform})).json()["items"]
        assert len(rows) == 1 and rows[0]["id"] == expected["id"]
        assert rows[0]["source_stale"] is (platform == "facebook")
    assert (await env.monthly_client.post(PREFIX + "/customers/20/runs", json={**fbbody, "platform": "instagram"})).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["binding", "credential", "image", "draft", "source"])
async def test_stale_source_cannot_schedule(meta_pipeline, mutation):
    env = meta_pipeline; url, data, _ = await reviewed(env)
    async with env.sessions() as db:
        if mutation == "binding": (await db.get(Binding, 201)).revision += 1
        if mutation == "credential": (await db.get(Credential, 1)).active = False
        if mutation == "image": (await db.get(Image, env.version["id"])).revoked_at = NOW
        if mutation == "draft": (await db.get(Draft, data["items"][0]["draft_id"])).content = "Changed after review"
        if mutation == "source": (await db.get(ReadBinding, 201)).external_id = "999999"
        await db.commit()
    response = await env.monthly_client.post(url + "/schedule", json=schedule_body(data))
    assert response.status_code == 409
    async with env.sessions() as db: assert await db.scalar(select(func.count()).select_from(Schedule)) == 0
    assert not env.ops.writes


@pytest.mark.asyncio
async def test_readonly_and_nonowners_cannot_gain_operating_rights(meta_pipeline):
    env = meta_pipeline
    async with env.sessions() as db:
        (await db.get(Binding, 201)).active = False; await db.commit()
    response = await env.monthly_client.put(PREFIX + "/customers/20/profile", params={"platform": "facebook"}, json=profile(env))
    assert response.status_code == 409
    setup = (await env.monthly_client.get(PREFIX + "/customers/20/setup", params={"platform": "facebook"})).json()
    assert not setup["capabilities"]["can_generate"] and any("独立运营授权" in g for g in setup["gaps"])
    for actor in [OPS, SECOND_OWNER]:
        env.user = actor
        response = await env.monthly_client.get(PREFIX + "/customers/20/setup", params={"platform": "instagram"})
        if actor is SECOND_OWNER:
            assert response.status_code == 200 and response.json()["profile"] is None and not response.json()["capabilities"]["can_generate"]
        else: assert response.status_code in {403, 404}
    env.user = OWNER; run, _ = await generated(env, "instagram")
    assert (await env.monthly_client.post(PREFIX + f"/runs/{run['id']}/adopt", json={"request_id": str(uuid4()), "expected_revision": run["revision"], "preview_hash": run["preview_hash"], "confirmed": True})).status_code == 409


@pytest.mark.asyncio
async def test_cancel_replace_cannot_escape_native_lineage(meta_pipeline):
    env = meta_pipeline; url, data, _ = await reviewed(env); item = data["items"][0]
    async with env.sessions() as db:
        draft = await db.get(Draft, item["draft_id"])
        fields = {"request_id": str(uuid4()), "expected_revision": draft.revision, "preview_hash": draft.preview_hash, "confirmed": True}
    publish = f"/api/v1/meta-operations/drafts/{item['draft_id']}/publish"
    assert (await env.ops_client.post(publish, json=fields)).status_code == 409
    saved = (await env.monthly_client.post(url + "/schedule", json=schedule_body(data))).json()
    cancelled = await env.monthly_client.post(url + "/cancel", json={"request_id": str(uuid4()), "expected_revision": saved["workflow"]["revision"], "reason": "重新核对内容"})
    assert cancelled.status_code == 200
    raw = (await env.monthly_client.get(url + "/workflow")).json()
    body = {"request_id": str(uuid4()), "expected_run_revision": raw["run_revision"], "expected_workflow_revision": raw["workflow"]["revision"],
        "items": [{"item_id": r["item_id"], "image_version_id": env.version["id"], "rights_confirmed": True} for r in raw["items"]], "facts_confirmed": True}
    assert (await env.monthly_client.post(url + "/prepare", json=body)).status_code == 200
    assert (await env.ops_client.post(publish, json=fields)).status_code == 409
    assert not env.ops.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["facebook", "instagram"])
async def test_native_worker_once_and_stale_packet_blocks(meta_pipeline, platform, monkeypatch):
    env = meta_pipeline; url, data, _ = await reviewed(env, platform)
    saved = (await env.monthly_client.post(url + "/schedule", json=schedule_body(data))).json()
    env.ops.execution = True
    monkeypatch.setenv("T24_META_OPS_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("T24_META_OPS_SCHEDULER_ACTIVATION_FROM", (NOW - timedelta(days=1)).isoformat())
    public = await env.monthly_client.post(url + "/schedule", json=schedule_body(saved, True))
    assert public.status_code == 200, public.text
    current = public.json(); assert current["items"][0]["schedule"]["revision"] == 2
    env.clock = datetime.fromisoformat(current["items"][0]["proposed_publish_at"])
    result = await worker.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    assert result["processed"] == 1
    if platform == "instagram":
        env.ops.readiness = "FINISHED"; await worker.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    assert len([r for r in env.ops.writes if r[0] == "post"]) == 1
    count = len(env.ops.writes); await worker.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    assert len(env.ops.writes) == count
    env.clock = datetime.fromisoformat(current["items"][1]["proposed_publish_at"])
    async with env.sessions() as db:
        (await db.get(Image, env.version["id"])).revoked_at = NOW; await db.commit()
    result = await worker.run_tick(sessions=env.sessions, clock=lambda: env.clock)
    assert result["stage"] == "blocked" and len(env.ops.writes) == count


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["review", "schedule"])
async def test_partial_native_write_failure_rolls_back_whole_batch(meta_pipeline, monkeypatch, stage):
    from fastapi import HTTPException
    env = meta_pipeline
    if stage == "review": url, data, _ = await prepared(env)
    else: url, data, _ = await reviewed(env)
    name = "_snapshot" if stage == "review" else "_approved"; original = getattr(native, name); seen = []
    async def fail(*args, **kwargs):
        seen.append(1)
        if len(seen) == 5: raise HTTPException(409, "synthetic current version changed")
        return await original(*args, **kwargs)
    monkeypatch.setattr(native, name, fail)
    body = {"request_id": str(uuid4()), "expected_revision": data["workflow"]["revision"], "preview_hash": data["workflow"]["preview_hash"], "confirmed": True} if stage == "review" else schedule_body(data)
    response = await env.monthly_client.post(url + "/" + stage, json=body)
    assert response.status_code == 409
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Schedule)) == 0
        assert await db.scalar(select(func.count()).select_from(Action)) == 0
        assert await db.scalar(select(func.count()).select_from(Draft)) == (0 if stage == "review" else 12)
    assert not env.ops.writes


@pytest.mark.asyncio
async def test_30_merchants_two_platform_months_are_complete_and_not_double_counted(meta_pipeline):
    from models.customers import Customers
    from models.media_monthly import MediaMonthlyProfile as Profile
    from models.media_monthly_workflow import MediaMonthlyWorkflow as Workflow
    env = meta_pipeline
    from test_media_monthly import RULES
    async with env.sessions() as db:
        for offset in range(30):
            identity = 300 + offset
            db.add(Customers(id=identity, business_name=f"Synthetic Merchant {offset:02}", contact_name="Synthetic", phone=f"+1555555{identity:04}", status="closed"))
            base_profile = profile(env)
            meta_profiles = {platform: {"revision": 1, **{key: base_profile[key] for key in ("public_facts", "rules", "menu_item_ids", "images")}} for platform in ("facebook", "instagram")}
            saved_profile = Profile(owner_id=1, customer_id=identity, revision=0, public_facts={}, rules={"_meta_profiles": meta_profiles}, menu_item_ids=[], images=[], confirmed_at=NOW, created_at=NOW, updated_at=NOW)
            db.add(saved_profile); await db.flush()
            for platform in ("facebook", "instagram"):
                bid = identity * 10 + (1 if platform == "facebook" else 2)
                fields = dict(id=bid, owner_id=1, customer_id=identity, customer_name=f"Synthetic Merchant {offset:02}", connection_id=1, connection_revision=1,
                    platform=platform, external_id=str(bid), page_id=str(identity * 10), asset_name="Synthetic asset", active=True, revision=1, created_at=NOW, updated_at=NOW)
                db.add(ReadBinding(**fields)); db.add(Binding(**fields, source_binding_id=bid, credential_id=1))
                slots = monthly_service.slots("2026-11", RULES)
                run = Run(owner_id=1, customer_id=identity, profile_id=saved_profile.id, request_id=str(uuid4()), fingerprint="a" * 64,
                    input_hash=f"{identity:04}{1 if platform == 'facebook' else 2}".ljust(64, "0"), month="2026-11", snapshot={"platform": platform, "rules": RULES, "public_facts": base_profile["public_facts"], "slots": slots},
                    runtime={"fingerprint": "r" * 64}, consent={}, status="generated", revision=2, ai_used=True, message="Synthetic private plan", created_at=NOW, updated_at=NOW)
                db.add(run); await db.flush()
                for slot in slots:
                    db.add(Item(run_id=run.id, slot_id=slot["slot_id"], proposed_publish_at=datetime.fromisoformat(slot["proposed_publish_at"]), timezone=slot["timezone"], title="Synthetic item", content="Synthetic content", owner_summary="测试中文摘要", material_id=203, image_version_id=env.version["id"], image_sha256=env.version["image_sha256"], menu_item_ids=[], revision=1, copy_hash="b" * 64, quality_warnings=[], created_at=NOW, updated_at=NOW))
                db.add(Workflow(owner_id=1, customer_id=identity, run_id=run.id, revision=1, status="prepared", snapshot={"platform": platform, "source": {"profile": monthly_service.profile_data(saved_profile, platform)}, "items": []}, task_refs=[], schedule_refs=[], source_hash="c" * 64, preview_hash="d" * 64, expires_at=NOW + timedelta(days=1), created_at=NOW, updated_at=NOW))
        await db.commit()
    params = {"start": "2026-10-31T16:00:00Z", "end": "2026-11-30T16:00:00Z", "view": "review", "limit": 100}
    path = "/api/v1/media-workspace/workspace"
    for platform in ("facebook", "instagram"):
        response = await env.monthly_client.get(path, params={**params, "platform": platform})
        assert response.status_code == 200, response.text
        rows = [r for r in response.json()["items"] if r["kind"] == "monthly_run"]
        assert len(rows) == 30 and len({r["customer_id"] for r in rows}) == 30
        assert all(r["platform"] == r["navigation"]["platform"] == platform and r["navigation"]["month"] == "2026-11" for r in rows)
        assert all(g["platform"] == platform for g in response.json()["review_groups"])
    response = await env.monthly_client.get(path, params=params)
    rows = [r for r in response.json()["items"] if r["kind"] == "monthly_run"]
    assert len(rows) == 60 and len(response.json()["review_groups"]) == 60
    merchants = await env.monthly_client.get("/api/v1/media-workspace/merchants", params={"start": params["start"], "end": params["end"], "limit": 100})
    assert merchants.status_code == 200, merchants.text
    shops = [r for r in merchants.json()["items"] if 300 <= r["id"] < 330]
    assert len(shops) == 30
    for shop in shops:
        queue = shop["work_queue"]
        assert queue["target"] == queue["prepared"] == queue["in_review"] == 24
        assert len(queue["platform_progress"]) == 2
        assert queue["next_action"]["platform"] in {"facebook", "instagram"}
    assert not env.ops.writes and not env.ops.reads
