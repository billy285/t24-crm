"""Synthetic owner pilot acceptance. No real Meta, credentials or business data."""
import asyncio
import copy
from datetime import timedelta
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from cryptography.fernet import Fernet
from fastapi import FastAPI
import httpx
from PIL import Image
import pytest
import pytest_asyncio
from sqlalchemy import create_engine, inspect, select, text

from core.database import get_db
from dependencies.auth import get_current_user
from models.customers import Customers
from models.employees import Employees
from models.meta_business import MetaBusinessBinding as Binding, MetaBusinessConnection as Connection
from models.meta_operations import MetaOperationsCredential as Credential, MetaOperationsBinding as OperatingBinding, MetaOperationsAction as Action, MetaOperationsSchedule as Schedule, MetaOperationsDraft as Draft, MetaOperationsOAuthState as OAuthState
from routers.meta_operations import router, MetaOperationsAccessLogFilter
from services import meta_operations as service, meta_operations_media as images, meta_operations_scheduler as scheduler, meta_operations_provider as provider
from test_google_business import gbp_env, OWNER, OPS, ADMIN, SECOND_OWNER, actors
from test_meta_business import meta_env

PREFIX = "/api/v1/meta-operations"


@pytest_asyncio.fixture
async def ops_env(meta_env, tmp_path, monkeypatch):
    env = meta_env; root = tmp_path / "meta-images"; root.mkdir(mode=0o700)
    monkeypatch.setattr(images, "ROOT", root)
    monkeypatch.setenv("T24_META_OPS_SCHEDULER_ENABLED", "false")
    key = Fernet.generate_key(); cipher = Fernet(key)
    fake = SimpleNamespace(writes=[], reads=[], writable=True, execution=True, failure=None, readiness="IN_PROGRESS", started=None, release=None,
        comment={"external_id": "111_901", "content": "A synthetic comment that needs an owner-reviewed response.", "author_name": "Synthetic visitor",
                 "created_at": "2026-11-01T10:00:00+00:00", "post_external_id": "111_900", "reply": None})
    monkeypatch.setattr(provider, "configuration_fingerprint", lambda: "c" * 64)
    monkeypatch.setattr(provider, "require_config", lambda: {})
    monkeypatch.setattr(provider, "status", lambda: {"configured": True, "setup_missing": [], "authorization": None})
    monkeypatch.setattr(provider, "execution_enabled", lambda: fake.execution)
    monkeypatch.setattr(provider, "encrypt", lambda value: cipher.encrypt(json.dumps(value).encode()).decode())
    monkeypatch.setattr(provider, "decrypt", lambda value: json.loads(cipher.decrypt(value.encode())))
    monkeypatch.setattr(provider, "authorize_url", lambda state: "https://www.facebook.com/v26.0/dialog/oauth?client_id=1139445441758834&state=" + state)
    async def capabilities(db, user, binding):
        own = await db.get(OperatingBinding, binding.id, populate_existing=True)
        ready = bool(fake.writable and own and own.active)
        return {"can_publish": ready, "can_reply": ready, "can_read_posts": ready, "can_read_comments": ready,
                "blocked_reasons": [] if ready else ["authorization_required"]}
    async def posts(db, user, binding, cursor=None):
        fake.reads.append(("posts", binding.id, cursor))
        return {"items": [{"external_id": "111_900" if binding.platform == "facebook" else "900", "content": "Synthetic existing post.", "created_at": "2026-11-01T10:00:00+00:00", "permalink": "https://www.facebook.com/111/posts/900"}], "next_cursor": None}
    async def comments(db, user, binding, post_external_id, cursor=None):
        fake.reads.append(("comments", binding.id, post_external_id)); return {"items": [copy.deepcopy(fake.comment)], "next_cursor": None}
    async def comment(db, user, binding, comment_external_id, post_external_id=None):
        fake.reads.append(("comment", binding.id, comment_external_id)); return copy.deepcopy(fake.comment)
    async def dispatch(db, user, binding, kind, payload):
        fake.writes.append((kind, binding.id, copy.deepcopy(payload)))
        if fake.started is not None: fake.started.set(); await fake.release.wait()
        if fake.failure == "timeout": raise provider.OpsProviderError(uncertain=True)
        if fake.failure == "denied": raise provider.OpsProviderError("access_denied")
        if kind == "reply" and payload["expected_version"] != service.digest(fake.comment): raise provider.OpsProviderError("target_changed")
        if kind == "post" and binding.platform == "instagram": return {"status": "processing", "container_id": "777", "stage": "container_created"}
        return {"status": "published", "external_id": "111_999", "permalink": "https://www.facebook.com/111/posts/999"}
    async def progress(db, user, binding, checkpoint):
        fake.reads.append(("progress", checkpoint["container_id"])); return {"status": fake.readiness, "container_id": checkpoint["container_id"]}
    async def publish_container(db, user, binding, container_id):
        fake.writes.append(("media_publish", binding.id, container_id))
        if fake.failure == "timeout_publish": raise provider.OpsProviderError(uncertain=True)
        return {"status": "published", "external_id": "999", "permalink": None}
    async def exchange(code):
        return {"access_token": "SYNTHETIC-OPS-ACCESS-TOKEN", "configuration": "c" * 64, "expires_at": service.now().timestamp() + 86400,
                "observed_scopes": sorted(provider.SCOPES), "user_id": "100"}
    async def verify_assets(token, targets):
        fake.reads.append(("verify_assets", len(targets))); return copy.deepcopy(targets)
    for name, value in {"capabilities": capabilities, "read_posts": posts, "read_comments": comments, "read_comment": comment,
                        "dispatch": dispatch, "inspect_progress": progress, "publish_container": publish_container, "exchange": exchange, "verify_assets": verify_assets}.items():
        monkeypatch.setattr(provider, name, value)
    async with env.sessions() as db:
        db.add(Customers(id=38, business_name="Pokeco", contact_name="Synthetic", phone="+15555550111", status="closed"))
        db.add_all([Binding(id=101, owner_id=1, customer_id=38, customer_name="Pokeco", connection_id=1, connection_revision=1,
            platform="facebook", external_id="111", page_id="111", asset_name="PokeCo", active=True, revision=1, created_at=service.now(), updated_at=service.now()),
            Binding(id=102, owner_id=1, customer_id=38, customer_name="Pokeco", connection_id=1, connection_revision=1,
            platform="instagram", external_id="222", page_id="111", asset_name="PokeCo · Instagram", active=True, revision=1, created_at=service.now(), updated_at=service.now()),
            Binding(id=103, owner_id=1, customer_id=10, customer_name="Other", connection_id=1, connection_revision=1,
            platform="facebook", external_id="333", page_id="333", asset_name="Other", active=True, revision=1, created_at=service.now(), updated_at=service.now())])
        db.add(Credential(id=1, owner_id=1, connection_id=1, token_encrypted="SYNTHETIC-ENCRYPTED-OPS-CREDENTIAL", granted_scopes=[], active=True, needs_reconnect=False, revision=1, connected_at=service.now()))
        db.add_all([OperatingBinding(id=101, source_binding_id=101, owner_id=1, customer_id=38, customer_name="Pokeco", connection_id=1,
            credential_id=1, connection_revision=1, platform="facebook", external_id="111", page_id="111", asset_name="PokeCo", active=True, revision=1, created_at=service.now(), updated_at=service.now()),
            OperatingBinding(id=102, source_binding_id=102, owner_id=1, customer_id=38, customer_name="Pokeco", connection_id=1,
            credential_id=1, connection_revision=1, platform="instagram", external_id="222", page_id="111", asset_name="PokeCo · Instagram", active=True, revision=1, created_at=service.now(), updated_at=service.now())])
        await db.commit()
    app = FastAPI(); app.include_router(router)
    async def database():
        async with env.sessions() as db: yield db
    async def actor(): return env.user
    app.dependency_overrides[get_db] = database; app.dependency_overrides[get_current_user] = actor
    env.ops = fake
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://t24-crm.com", follow_redirects=False) as client:
        env.ops_client = client; yield env


async def protected_snapshot(env):
    async with env.sessions() as db:
        names = (await db.scalars(text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'meta_operations_%' ORDER BY name"))).all()
        return {name: sorted(repr(tuple(row)) for row in (await db.execute(text('SELECT * FROM "' + name.replace('"', '""') + '"'))).all()) for name in names}


async def new_draft(env, binding=101, **updates):
    body = {"request_id": str(uuid4()), "kind": "post", "title": "Synthetic owner pilot", "content": "Owner-confirmed synthetic content.", **updates}
    response = await env.ops_client.post(PREFIX + f"/bindings/{binding}/drafts", json=body)
    assert response.status_code == 201, response.text
    return response.json(), body


async def approved(env, binding=101, **updates):
    row, _ = await new_draft(env, binding, **updates)
    response = await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/preview", json={"expected_revision": row["revision"]})
    assert response.status_code == 200, response.text
    preview = response.json()
    response = await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/approve", json={"expected_revision": row["revision"], "preview_hash": preview["preview_hash"], "confirmed": True})
    assert response.status_code == 200, response.text
    return response.json(), preview


def jpeg(width=640, height=480):
    output = io.BytesIO(); image = Image.new("RGB", (width, height), "orange")
    exif = Image.Exif(); exif[315] = "PRIVATE-EXIF-MUST-DISAPPEAR"
    image.save(output, "JPEG", exif=exif)
    return output.getvalue()


async def upload(env, binding=101, body=None, request_id=None):
    response = await env.ops_client.post(PREFIX + f"/bindings/{binding}/media", data={"request_id": request_id or str(uuid4()), "rights_confirmed": "true"}, files={"file": ("synthetic.jpg", body or jpeg(), "image/jpeg")})
    assert response.status_code == 201, response.text
    return response.json()


def publish_body(draft, preview):
    return {"request_id": str(uuid4()), "expected_revision": draft["revision"], "preview_hash": preview["preview_hash"], "confirmed": True}


@pytest.mark.asyncio
async def test_owner_only_strict_customer_38_and_no_implicit_staff_or_other_owner_access(ops_env):
    env = ops_env
    response = await env.ops_client.get(PREFIX + "/status")
    assert response.status_code == 200 and [x["id"] for x in response.json()["bindings"]] == [101, 102]
    assert response.headers["cache-control"] == "private, no-store" and response.headers["referrer-policy"] == "no-referrer"
    assert (await env.ops_client.get(PREFIX + "/bindings/103/workspace")).status_code == 409
    for user in actors()[1:]:
        env.user = user
        for path in ("/status", "/bindings/101/workspace", "/bindings/101/posts"):
            actual = await env.ops_client.get(PREFIX + path)
            if user == SECOND_OWNER and path == "/status":
                assert actual.status_code == 200 and actual.json()["bindings"] == []
            else: assert actual.status_code in {403, 404}
    assert not env.ops.writes and not env.ops.reads


@pytest.mark.asyncio
async def test_drafts_prepare_preview_approve_without_write_permission_and_never_publish(ops_env):
    env = ops_env; before = await protected_snapshot(env); env.ops.writable = False
    row, preview = await approved(env)
    assert row["status"] == "approved" and preview["ready_for_publish"] is False
    result = await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/publish", json=publish_body(row, preview))
    assert result.status_code == 409 and not env.ops.writes
    assert await protected_snapshot(env) == before


@pytest.mark.asyncio
async def test_exact_preview_confirmation_stale_revision_and_target_fences(ops_env):
    env = ops_env; row, _ = await new_draft(env)
    preview = (await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/preview", json={"expected_revision": 1})).json()
    changed = await env.ops_client.patch(PREFIX + f"/drafts/{row['id']}", json={"expected_revision": 1, "content": "Different content."})
    assert changed.status_code == 200 and changed.json()["preview_hash"] is None
    assert (await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/approve", json={"expected_revision": 2, "preview_hash": preview["preview_hash"], "confirmed": True})).status_code == 409
    assert (await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/approve", json={"expected_revision": 1, "preview_hash": preview["preview_hash"], "confirmed": True})).status_code == 409
    assert not env.ops.writes


@pytest.mark.asyncio
async def test_publish_is_durable_idempotent_and_same_revision_cannot_send_new_request(ops_env):
    env = ops_env; before = await protected_snapshot(env); row, preview = await approved(env); body = publish_body(row, preview)
    response = await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/publish", json=body)
    assert response.status_code == 200 and response.json()["status"] == "succeeded"
    assert (await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/publish", json=body)).json() == response.json()
    assert (await env.ops_client.get(PREFIX + "/requests/" + body["request_id"])).json()["result"] == response.json()
    assert (await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/publish", json={**body, "request_id": str(uuid4())})).status_code == 409
    assert len(env.ops.writes) == 1 and await protected_snapshot(env) == before


@pytest.mark.asyncio
async def test_timeout_is_unknown_and_never_blindly_retried(ops_env):
    env = ops_env; row, preview = await approved(env); body = publish_body(row, preview); env.ops.failure = "timeout"
    response = await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/publish", json=body)
    value = response.json(); assert response.status_code == 200 and value["status"] == "unknown" and not value["can_continue"]
    assert (await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/publish", json=body)).json()["status"] == "unknown"
    assert (await env.ops_client.post(PREFIX + f"/actions/{value['id']}/continue", json={"expected_revision": value["revision"], "confirmed": True})).status_code == 409
    assert len(env.ops.writes) == 1


@pytest.mark.asyncio
async def test_private_jpeg_strips_metadata_and_upload_does_not_open_delivery(ops_env):
    env = ops_env; uploaded = await upload(env)
    response = await env.ops_client.get(PREFIX + uploaded["preview_path"].removeprefix(PREFIX))
    assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
    assert b"PRIVATE-EXIF" not in response.content and uploaded["sha256"] == service.hashlib.sha256(response.content).hexdigest()
    assert uploaded["width"] == 640 and uploaded["height"] == 480
    assert (await env.ops_client.get(PREFIX + "/delivery/" + "A" * 43 + ".jpg")).status_code == 404
    assert (await env.ops_client.head(PREFIX + "/delivery/" + "A" * 43 + ".jpg")).status_code == 404
    assert not env.ops.writes


@pytest.mark.asyncio
async def test_lease_exists_only_after_confirmed_dispatch_and_revokes_on_disconnect(ops_env):
    env = ops_env; image = await upload(env); row, preview = await approved(env, media_id=image["id"])
    result = await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/publish", json=publish_body(row, preview)); assert result.status_code == 200
    url = env.ops.writes[0][2]["image_url"]; path = urlsplit(url).path
    assert (await env.ops_client.get(path)).status_code == 200
    async with env.sessions() as db:
        binding = await db.get(OperatingBinding, 101); binding.active = False; binding.revision += 1; await db.commit()
    assert (await env.ops_client.get(path)).status_code == 404
    assert "delivery_token" not in result.text and "image_url" not in result.text


@pytest.mark.asyncio
async def test_instagram_container_is_durable_and_publish_requires_separate_claim(ops_env):
    env = ops_env; image = await upload(env, 102); row, preview = await approved(env, 102, media_id=image["id"])
    body = publish_body(row, preview); response = await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/publish", json=body)
    action = response.json(); assert action["status"] == "processing" and action["can_continue"]
    assert [x[0] for x in env.ops.writes] == ["post"]
    assert (await env.ops_client.get(PREFIX + f"/actions/{action['id']}")).json()["status"] == "processing"
    assert len(env.ops.writes) == 1
    waiting = await env.ops_client.post(PREFIX + f"/actions/{action['id']}/continue", json={"expected_revision": action["revision"], "confirmed": True})
    assert waiting.json()["status"] == "processing" and len(env.ops.writes) == 1
    env.ops.readiness = "FINISHED"
    done = await env.ops_client.post(PREFIX + f"/actions/{action['id']}/continue", json={"expected_revision": action["revision"], "confirmed": True})
    assert done.status_code == 200 and done.json()["status"] == "succeeded"
    assert [x[0] for x in env.ops.writes] == ["post", "media_publish"]
    assert (await env.ops_client.post(PREFIX + f"/actions/{action['id']}/continue", json={"expected_revision": action["revision"], "confirmed": True})).status_code == 409


@pytest.mark.asyncio
async def test_reply_target_is_opaque_current_and_changed_comment_blocks_approval(ops_env):
    env = ops_env
    post = (await env.ops_client.get(PREFIX + "/bindings/101/posts")).json()["items"][0]
    assert "external_id" not in post
    comment = (await env.ops_client.get(PREFIX + "/bindings/101/comments", params={"post_ref": post["target_ref"]})).json()["items"][0]
    row, _ = await new_draft(env, kind="reply", target_ref=comment["target_ref"], expected_target_version=comment["version"], content="Thank you for the details.")
    preview = (await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/preview", json={"expected_revision": row["revision"]})).json()
    assert preview["reply_to"]["content"] == comment["content"]
    env.ops.comment["content"] = "Changed original comment."
    response = await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/approve", json={"expected_revision": 1, "preview_hash": preview["preview_hash"], "confirmed": True})
    assert response.status_code == 409 and not env.ops.writes


@pytest.mark.asyncio
async def test_prepare_schedule_stays_inert_when_worker_changes_and_activation_is_explicit(ops_env):
    env = ops_env; row, preview = await approved(env)
    env.monkeypatch.setenv("T24_META_OPS_SCHEDULER_ENABLED", "true"); env.monkeypatch.setenv("T24_META_OPS_SCHEDULER_ACTIVATION_FROM", service.iso(service.now() - timedelta(minutes=1)))
    response = await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/schedules", json={**publish_body(row, preview), "planned_at": service.iso(service.now() + timedelta(hours=2)), "timezone": "America/Los_Angeles", "execute_confirmed": False})
    assert response.status_code == 201, response.text
    schedule = response.json(); assert schedule["status"] == "prepared"
    assert schedule["submitted_draft"]["content"] == row["content"] and schedule["preview_hash"] == preview["preview_hash"]
    result = await scheduler.run_tick(sessions=env.sessions); assert result["processed"] == 0 and not env.ops.writes
    enabled = await env.ops_client.post(PREFIX + f"/schedules/{schedule['id']}/activate", json={"expected_revision": schedule["revision"], "confirmed": True})
    assert enabled.status_code == 200 and enabled.json()["status"] == "scheduled"


@pytest.mark.asyncio
async def test_schedule_failed_action_sync_maps_to_blocked_not_invalid_status(ops_env):
    env = ops_env; row, preview = await approved(env)
    response = await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/schedules", json={**publish_body(row, preview), "planned_at": service.iso(service.now() + timedelta(hours=2)), "timezone": "America/Los_Angeles"})
    schedule = response.json()
    async with env.sessions() as db:
        action = Action(owner_id=1, binding_id=101, binding_revision=1, connection_revision=1, draft_id=row["id"], draft_revision=row["revision"], kind="post", request_id=str(uuid4()), fingerprint="d" * 64,
            preview_hash=preview["preview_hash"], submitted_snapshot={}, payload={}, status="failed", revision=1, dispatch_stage="failed", message="Definitive synthetic rejection", created_at=service.now(), updated_at=service.now())
        db.add(action); await db.commit(); identity = action.id
        await scheduler._sync(db, schedule["id"], identity)
        saved = await db.get(Schedule, schedule["id"], populate_existing=True); assert saved.status == "blocked"


@pytest.mark.asyncio
async def test_confirmed_future_schedule_executes_once_and_old_jobs_are_not_replayed(ops_env):
    env = ops_env; before = await protected_snapshot(env); row, preview = await approved(env)
    env.monkeypatch.setenv("T24_META_OPS_SCHEDULER_ENABLED", "true"); env.monkeypatch.setenv("T24_META_OPS_SCHEDULER_ACTIVATION_FROM", service.iso(service.now() - timedelta(minutes=1)))
    planned = service.now() + timedelta(hours=2)
    response = await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/schedules", json={**publish_body(row, preview), "planned_at": service.iso(planned), "timezone": "America/Los_Angeles", "execute_confirmed": True})
    assert response.status_code == 201 and response.json()["status"] == "scheduled", response.text
    result = await scheduler.run_tick(sessions=env.sessions, clock=lambda: planned + timedelta(seconds=1))
    assert result["processed"] == 1 and len(env.ops.writes) == 1
    assert (await scheduler.run_tick(sessions=env.sessions, clock=lambda: planned + timedelta(seconds=2)))["processed"] == 0
    async with env.sessions() as db:
        saved = await db.get(Schedule, response.json()["id"], populate_existing=True); assert saved.status == "succeeded"
    another, another_preview = await approved(env)
    old = await env.ops_client.post(PREFIX + f"/drafts/{another['id']}/schedules", json={**publish_body(another, another_preview), "planned_at": service.iso(planned + timedelta(hours=1)), "timezone": "America/Los_Angeles", "execute_confirmed": True})
    assert old.status_code == 201
    await scheduler.run_tick(sessions=env.sessions, clock=lambda: planned + timedelta(hours=2))
    async with env.sessions() as db:
        assert (await db.get(Schedule, old.json()["id"], populate_existing=True)).status == "missed"
    assert len(env.ops.writes) == 1 and await protected_snapshot(env) == before


@pytest.mark.asyncio
async def test_ig_ambiguous_publish_keeps_original_container_and_never_republishes(ops_env):
    env = ops_env; image = await upload(env, 102); row, preview = await approved(env, 102, media_id=image["id"])
    body = publish_body(row, preview)
    original = (await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/publish", json=body)).json()
    env.ops.readiness = "FINISHED"; env.ops.failure = "timeout_publish"
    value = (await env.ops_client.post(PREFIX + f"/actions/{original['id']}/continue", json={"expected_revision": original["revision"], "confirmed": True})).json()
    assert value["status"] == "unknown" and not value["can_continue"]
    assert (await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/publish", json=body)).json()["status"] == "unknown"
    assert (await env.ops_client.post(PREFIX + f"/actions/{original['id']}/continue", json={"expected_revision": value["revision"], "confirmed": True})).status_code == 409
    assert [x[0] for x in env.ops.writes] == ["post", "media_publish"]


@pytest.mark.asyncio
async def test_inflight_revoke_preserves_actual_outcome_without_new_employee_grants(ops_env):
    env = ops_env; row, preview = await approved(env); body = publish_body(row, preview)
    env.ops.started = asyncio.Event(); env.ops.release = asyncio.Event()
    pending = asyncio.create_task(env.ops_client.post(PREFIX + f"/drafts/{row['id']}/publish", json=body))
    await env.ops.started.wait()
    async with env.sessions() as db:
        binding = await db.get(OperatingBinding, 101); binding.active = False; binding.revision += 1; await db.commit()
    env.ops.release.set(); response = await pending
    assert response.status_code == 200 and response.json()["status"] == "succeeded"
    assert (await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/publish", json=body)).json()["status"] == "succeeded"
    assert len(env.ops.writes) == 1


@pytest.mark.asyncio
async def test_different_customer_cannot_reuse_private_media_or_comment_refs(ops_env):
    env = ops_env; image = await upload(env)
    row, _ = await new_draft(env)
    async with env.sessions() as db:
        other = await db.get(Customers, 10); other.business_name = "Pokeco"; await db.commit()
    response = await env.ops_client.post(PREFIX + "/bindings/103/drafts", json={"request_id": str(uuid4()), "kind": "post", "title": "Forged pilot name", "content": "Synthetic", "media_id": image["id"]})
    assert response.status_code == 409  # Stable ID38, never an editable name alone.
    for value in ({"expected_revision": 1, "company_profit": 100}, {"expected_revision": True}):
        assert (await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/preview", json=value)).status_code == 422
    assert not env.ops.writes


@pytest.mark.asyncio
async def test_independent_operating_authority_survives_old_read_expiry_without_old_writes(ops_env):
    env = ops_env
    async with env.sessions() as db:
        connection = await db.get(Connection, 1); connection.active = False; connection.needs_reconnect = True; connection.token_encrypted = None; connection.revision += 1
        for identity in (101, 102):
            source = await db.get(Binding, identity); source.active = False; source.revision += 1
        await db.commit()
    before = await protected_snapshot(env)
    status = await env.ops_client.get(PREFIX + "/status")
    assert status.status_code == 200 and [x["id"] for x in status.json()["bindings"]] == [101, 102]
    assert all(x["operations_active"] and not x["paused"] for x in status.json()["bindings"])
    row, preview = await approved(env)
    sent = await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/publish", json=publish_body(row, preview))
    assert sent.status_code == 200 and sent.json()["status"] == "succeeded"
    request_id = str(uuid4())
    start = await env.ops_client.post(PREFIX + "/oauth/start", json={"request_id": request_id, "connection_id": 1, "confirmed": True})
    assert start.status_code == 200, start.text
    state = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]
    callback = await env.ops_client.get(PREFIX + "/oauth/callback", params={"state": state, "code": "SYNTHETIC-CODE"})
    assert callback.headers["location"] == "/media-ops?meta_ops=connected"
    assert await protected_snapshot(env) == before


@pytest.mark.asyncio
async def test_own_pause_cannot_fallback_to_active_read_binding_and_blocks_future_plans(ops_env):
    env = ops_env; row, preview = await approved(env)
    planned = await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/schedules", json={**publish_body(row, preview), "planned_at": service.iso(service.now() + timedelta(hours=2)), "timezone": "America/Los_Angeles"})
    before = await protected_snapshot(env)
    paused = await env.ops_client.post(PREFIX + "/bindings/101/disconnect", json={"expected_revision": 1, "confirmed": True})
    assert paused.status_code == 200 and paused.json()["paused"] and not paused.json()["operations_active"]
    status = (await env.ops_client.get(PREFIX + "/status")).json()
    target = next(x for x in status["bindings"] if x["id"] == 101)
    assert target["paused"] and not target["can_pause"] and not target["capabilities"]["can_publish"]
    assert (await env.ops_client.post(PREFIX + "/bindings/101/drafts", json={"request_id": str(uuid4()), "kind": "post", "title": "Not allowed", "content": "Synthetic"})).status_code == 409
    async with env.sessions() as db:
        assert (await db.get(Binding, 101)).active is True
        assert (await db.get(Schedule, planned.json()["id"])).status == "blocked"
    assert await protected_snapshot(env) == before and not env.ops.writes


@pytest.mark.asyncio
async def test_initial_ops_binding_is_created_only_after_actual_verified_oauth_not_get_or_draft(ops_env):
    env = ops_env
    async with env.sessions() as db:
        for identity in (101, 102): await db.delete(await db.get(OperatingBinding, identity))
        await db.delete(await db.get(Credential, 1)); await db.commit()
    before = await protected_snapshot(env)
    status = (await env.ops_client.get(PREFIX + "/status")).json()
    assert all(not x["operations_active"] and not x["can_pause"] for x in status["bindings"])
    await new_draft(env)
    async with env.sessions() as db:
        assert (await db.scalars(select(OperatingBinding))).all() == []
    start = await env.ops_client.post(PREFIX + "/oauth/start", json={"request_id": str(uuid4()), "connection_id": 1, "confirmed": True})
    assert start.status_code == 200
    state = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]
    callback = await env.ops_client.get(PREFIX + "/oauth/callback", params={"state": state, "code": "SYNTHETIC-CODE"})
    assert callback.headers["location"] == "/media-ops?meta_ops=connected"
    assert any(x[0] == "verify_assets" for x in env.ops.reads)
    async with env.sessions() as db:
        assert len((await db.scalars(select(OperatingBinding))).all()) == 2
    assert await protected_snapshot(env) == before


@pytest.mark.asyncio
async def test_oauth_source_identity_change_and_own_pause_race_cannot_reactivate(ops_env):
    env = ops_env
    start = await env.ops_client.post(PREFIX + "/oauth/start", json={"request_id": str(uuid4()), "connection_id": 1, "confirmed": True})
    state = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]
    await env.ops_client.post(PREFIX + "/bindings/101/disconnect", json={"expected_revision": 1, "confirmed": True})
    callback = await env.ops_client.get(PREFIX + "/oauth/callback", params={"state": state, "code": "SYNTHETIC-CODE"})
    assert callback.headers["location"] == "/media-ops?meta_ops=failed"
    async with env.sessions() as db:
        assert not (await db.get(OperatingBinding, 101)).active and (await db.get(Credential, 1)).revision == 1
    another = await env.ops_client.post(PREFIX + "/oauth/start", json={"request_id": str(uuid4()), "connection_id": 1, "confirmed": True})
    assert another.status_code == 200
    other_state = parse_qs(urlsplit(another.json()["authorization_url"]).query)["state"][0]
    async with env.sessions() as db:
        source = await db.get(Binding, 102); source.external_id = "999999"; await db.commit()
    changed = await env.ops_client.get(PREFIX + "/oauth/callback", params={"state": other_state, "code": "SYNTHETIC-CODE"})
    assert changed.headers["location"] == "/media-ops?meta_ops=failed"
    async with env.sessions() as db:
        assert (await db.get(Credential, 1)).revision == 1


@pytest.mark.asyncio
async def test_approve_same_snapshot_is_idempotent_does_not_mint_new_dispatch_version(ops_env):
    env = ops_env; row, preview = await approved(env)
    again = await env.ops_client.post(PREFIX + f"/drafts/{row['id']}/approve", json={"expected_revision": row["revision"], "preview_hash": preview["preview_hash"], "confirmed": True})
    assert again.status_code == 200 and again.json()["revision"] == row["revision"]


@pytest.mark.asyncio
async def test_default_off_scheduler_never_reads_or_changes_tables(ops_env):
    env = ops_env; before = await protected_snapshot(env)
    result = await scheduler.run_tick(sessions=lambda: (_ for _ in ()).throw(AssertionError("NO_DATABASE")))
    assert result == {"stage": "disabled", "processed": 0} and await protected_snapshot(env) == before


@pytest.mark.asyncio
async def test_oauth_is_independent_one_use_and_preserves_read_token_bindings(ops_env):
    env = ops_env; before = await protected_snapshot(env); key = str(uuid4())
    response = await env.ops_client.post(PREFIX + "/oauth/start", json={"request_id": key, "connection_id": 1, "confirmed": True})
    assert response.status_code == 200, response.text
    assert "HttpOnly" in response.headers["set-cookie"] and "Secure" in response.headers["set-cookie"]
    state = parse_qs(urlsplit(response.json()["authorization_url"]).query)["state"][0]
    callback = await env.ops_client.get(PREFIX + "/oauth/callback", params={"state": state, "code": "SYNTHETIC-CODE"})
    assert callback.status_code == 303 and callback.headers["location"] == "/media-ops?meta_ops=connected"
    assert (await env.ops_client.get(PREFIX + "/oauth/callback", params={"state": state, "code": "SYNTHETIC-CODE"})).headers["location"] == "/media-ops?meta_ops=failed"
    assert await protected_snapshot(env) == before
    async with env.sessions() as db:
        assert (await db.get(Credential, 1)).revision == 2


def test_migration_is_additive_empty_and_unique_dispatch_revision():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "cefa9b12a358_meta_operations.py"
    spec = importlib.util.spec_from_file_location("meta_ops_migration", path); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE financial_canary(id INTEGER PRIMARY KEY, amount TEXT)")); db.execute(text("INSERT INTO financial_canary VALUES(1,'199.00')"))
        module.op = Operations(MigrationContext.configure(db)); module.upgrade()
        tables = [n for n in inspect(db).get_table_names() if n.startswith("meta_operations_")]
        assert len(tables) == 9 and all(db.execute(text('SELECT COUNT(*) FROM "'+name+'"')).scalar() == 0 for name in tables)
        assert db.execute(text("SELECT * FROM financial_canary")).all() == [(1, "199.00")]
        assert any(c["column_names"] == ["draft_id", "draft_revision"] for c in inspect(db).get_unique_constraints("meta_operations_actions"))
        with pytest.raises(RuntimeError): module.downgrade()


def test_access_log_masks_callback_and_capability_paths():
    import logging
    for path, expected in (("/api/v1/meta-operations/oauth/callback?code=SECRET&state=SECRET", "/api/v1/meta-operations/oauth/callback"),
                           ("/api/v1/meta-operations/delivery/SECRET.jpg", "/api/v1/meta-operations/delivery/[image].jpg")):
        record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "%s %s %s %s %s", ("client", "GET", path, "HTTP", 200), None)
        assert MetaOperationsAccessLogFilter().filter(record) and record.args[2] == expected and "SECRET" not in record.getMessage()
