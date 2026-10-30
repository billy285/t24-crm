"""Independent synthetic GBP access, external-write, OAuth and retry checks.

The only provider used here is a deterministic in-memory double. No production
database, browser session, credentials or live Google endpoint is accessed.
"""
import asyncio
import base64
import copy
import hashlib
import importlib.util
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from alembic.migration import MigrationContext
from alembic.operations import Operations

from core.database import Base, get_db
from dependencies.auth import get_current_user
from models.customer_access_grants import CustomerAccessGrant
from models.customer_materials import Customer_materials
from models.customers import Customers
from models.employees import Employees
from models.media_operations import MediaOperationEvent, MediaOperationTask
from schemas.auth import UserResponse


PREFIX = "/api/v1/google-business"
OWNER = UserResponse(id="1", role="super_admin", name="Synthetic Owner", email="owner@example.test")
OPS = UserResponse(id="2", role="ops", name="Synthetic Operator", email="ops@example.test")
OTHER = UserResponse(id="3", role="ops", name="Other Operator", email="other@example.test")
ADMIN = UserResponse(id="4", role="admin", name="Ordinary Admin", email="admin@example.test")
SECOND_OWNER = UserResponse(id="9", role="super_admin", name="Another Owner", email="otherowner@example.test")
LOCATION = "accounts/100/locations/1000"
HIDDEN_LOCATION = "accounts/200/locations/2000"
REVIEW = LOCATION + "/reviews/review_1"


def actors():
    return [OWNER, OPS, OTHER, ADMIN, SECOND_OWNER] + [
        UserResponse(id=str(i), role=role, name=role, email=role + "@example.test")
        for i, role in ((5, "finance"), (6, "sales"), (7, "design"), (8, "sales_partner"))
    ]


@pytest_asyncio.fixture
async def gbp_env(tmp_path, monkeypatch):
    from models.google_business import GoogleBusinessAction as Action, GoogleBusinessBinding as Binding, GoogleBusinessConnection as Connection, GoogleBusinessGrant as Grant, GoogleBusinessOAuthState as OAuthState
    from routers.google_business import router
    from routers.media_operations import router as media_router
    from services import google_business as service, google_business_provider as provider

    for key, value in {
        "ENABLED": "true", "API_APPROVED": "true", "CLIENT_ID": "synthetic-client.apps.googleusercontent.com",
        "CLIENT_SECRET": "SYNTHETIC-CLIENT-SECRET-NOT-REAL", "TOKEN_KEY": Fernet.generate_key().decode(),
        "PUBLIC_URL": "https://crm.example.com",
    }.items():
        monkeypatch.setenv("T24_GBP_" + key, value)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'gbp-synthetic.db'}", connect_args={"timeout": 5})
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE TABLE IF NOT EXISTS app_settings(config_key TEXT PRIMARY KEY,value_json TEXT)"))
        await conn.execute(text("CREATE TABLE financial_canary(id INTEGER PRIMARY KEY,amount TEXT,closing_state TEXT,commission_owner TEXT)"))
        await conn.execute(text("INSERT INTO financial_canary VALUES(1,'199.00','closed','original-owner')"))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    fake = SimpleNamespace(writes=[], reads=[], failure=None, post_state="LIVE", reply_state="APPROVED", posts=[], exchange_calls=[], read_started=None, release_read=None, write_started=None, release_write=None,
        location_items=[{"location_name": LOCATION, "title": "Synthetic Google Merchant", "address": "100 Synthetic Street, CA"}],
        review={"name": REVIEW, "reviewer": {"displayName": "SECRET-REVIEWER-ORIGINAL"}, "starRating": "FIVE", "comment": "SECRET-REVIEW-ORIGINAL", "createTime": "2026-10-29T10:00:00Z", "updateTime": "2026-10-29T10:00:00Z"})
    real_client = provider.GoogleClient

    async def wait_for_read():
        if fake.read_started is not None:
            fake.read_started.set()
            await fake.release_read.wait()

    async def wait_for_write():
        if fake.write_started is not None:
            fake.write_started.set()
            await fake.release_write.wait()

    class FakeClient:
        def __init__(self, connection=None): self.connection = connection
        async def exchange(self, code, verifier):
            fake.exchange_calls.append((code, verifier))
            return {"access_token": "SYNTHETIC-ACCESS-TOKEN", "refresh_token": "SYNTHETIC-REFRESH-TOKEN", "scope": provider.SCOPE, "expires_at": time.time() + 3600}
        async def locations(self):
            fake.reads.append(("locations", getattr(self.connection, "id", None)))
            await wait_for_read()
            return {"items": copy.deepcopy(fake.location_items), "truncated": False}
        async def reviews(self, location, page_token=None):
            fake.reads.append(("reviews", location, page_token))
            await wait_for_read()
            return {"reviews": [copy.deepcopy(fake.review)], "nextPageToken": None}
        async def review(self, name):
            fake.reads.append(("review", name))
            await wait_for_read()
            if fake.failure == "read_denied": raise provider.ProviderError("access_denied")
            return copy.deepcopy(fake.review)
        async def reply(self, name, payload):
            fake.writes.append(("reply", name, copy.deepcopy(payload)))
            await wait_for_write()
            if fake.failure == "definitive": raise provider.ProviderError("invalid_request")
            if fake.failure == "secret_error": raise provider.ProviderError("SECRET-RAW-ACCESS-TOKEN-AND-PROVIDER-BODY")
            if fake.failure == "uncertain_before": raise provider.ProviderError("provider_unavailable", uncertain=True)
            fake.review["reviewReply"] = {"comment": payload["comment"], "updateTime": "2026-10-30T10:00:00Z", **({"reviewReplyState": fake.reply_state} if fake.reply_state else {})}
            if fake.failure == "cancel_after": raise asyncio.CancelledError()
            if fake.failure == "timeout_after": raise provider.ProviderError("provider_unavailable", uncertain=True)
            return copy.deepcopy(fake.review["reviewReply"])
        async def publish(self, location, payload):
            fake.writes.append(("publish", location, copy.deepcopy(payload)))
            await wait_for_write()
            if fake.failure == "definitive": raise provider.ProviderError("invalid_request")
            if fake.failure == "uncertain_before": raise provider.ProviderError("provider_unavailable", uncertain=True)
            result = {**copy.deepcopy(payload), "name": location + "/localPosts/post_" + str(len(fake.posts) + 1), "state": fake.post_state,
                      "searchUrl": "https://www.google.com/search?synthetic=1", "createTime": service.now().isoformat()}
            fake.posts.append(result)
            if fake.failure == "cancel_after": raise asyncio.CancelledError()
            if fake.failure == "timeout_after": raise provider.ProviderError("provider_unavailable", uncertain=True)
            return copy.deepcopy(result)
        async def posts(self, location):
            fake.reads.append(("posts", location))
            await wait_for_read()
            return {"localPosts": copy.deepcopy(fake.posts)}
        async def post(self, name):
            fake.reads.append(("post", name))
            await wait_for_read()
            return copy.deepcopy(next(row for row in fake.posts if row["name"] == name))
    monkeypatch.setattr(provider, "GoogleClient", FakeClient)

    async with sessions() as db:
        db.add_all([Employees(id=int(user.id), user_id=user.id, name=user.name, role=user.role, status="active", password="SECRET-EMPLOYEE-PASSWORD") for user in actors()])
        db.add_all([
            Customers(id=10, business_name="Synthetic Invited Merchant", contact_name="Synthetic", phone="111", private_notes="SECRET-PRIVATE-NOTES", status="closed"),
            Customers(id=20, business_name="SECRET-HIDDEN-MERCHANT", contact_name="Hidden", phone="222", private_notes="SECRET-HIDDEN-NOTES", status="closed"),
        ])
        db.add_all([CustomerAccessGrant(customer_id=10, employee_id=i, access_level="read_write", invitation_source="owner_invitation", invitation_status="active", finance_access="none", scopes={"basic": "read_only", "delivery": "read_write", "materials": "read_only"}) for i in (2, 3, 4)])
        db.add_all([
            Customer_materials(id=1001, user_id="1", customer_id=10, title="Synthetic Team Public Image", material_type="image", visibility="team", content_type="image/png", file_url="https://images.example.com/synthetic.png"),
            Customer_materials(id=1002, user_id="1", customer_id=10, title="SECRET-PRIVATE-IMAGE", material_type="image", visibility="owner", content_type="image/png", file_path="SECRET-PRIVATE-PATH"),
        ])
        db.add_all([
            Connection(id=1, owner_id=1, label="Owner Google", token_encrypted=provider.encrypt({"access_token": "SYNTHETIC-ACCESS-TOKEN", "refresh_token": "SYNTHETIC-REFRESH-TOKEN", "scope": provider.SCOPE, "expires_at": time.time() + 3600}), active=True, needs_reconnect=False),
            Connection(id=2, owner_id=9, label="SECRET-OTHER-OWNER-CONNECTION", token_encrypted=provider.encrypt({"access_token": "OTHER-ACCESS-TOKEN", "refresh_token": "OTHER-REFRESH-TOKEN", "scope": provider.SCOPE, "expires_at": time.time() + 3600}), active=True, needs_reconnect=False),
        ])
        db.add_all([
            Binding(id=1, customer_id=10, customer_name="Synthetic Invited Merchant", connection_id=1, location_name=LOCATION, title="Synthetic Invited Merchant", address="", active=True, revision=1, created_by_id=1, request_id=str(uuid4())),
            Binding(id=2, customer_id=20, customer_name="SECRET-HIDDEN-MERCHANT", connection_id=2, location_name=HIDDEN_LOCATION, title="SECRET-HIDDEN-MERCHANT", address="", active=True, revision=1, created_by_id=9, request_id=str(uuid4())),
        ])
        db.add(Grant(binding_id=1, employee_id=2, can_reply=True, can_publish=True, granted_by_id=1))
        config = {user.role: {"pages": ["/media-ops", "/service-board", "/customers"], "buttons": ["task_create", "task_edit"], "dataScope": "all"} for user in actors()}
        await db.execute(text("INSERT INTO app_settings(config_key,value_json) VALUES('role_permissions',:value)"), {"value": json.dumps(config)})
        await db.commit()
    app = FastAPI(); app.include_router(router); app.include_router(media_router)
    env = SimpleNamespace(user=OWNER, sessions=sessions, engine=engine, fake=fake, provider=provider, service=service, real_client=real_client,
                          Action=Action, Binding=Binding, Connection=Connection, Grant=Grant, OAuthState=OAuthState, monkeypatch=monkeypatch)
    async def database():
        async with sessions() as db: yield db
    async def actor(): return env.user
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = actor
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=True), base_url="https://crm.example.com", follow_redirects=False) as client:
        env.client = client
        yield env
    await engine.dispose()


async def current_review(env):
    response = await env.client.get(PREFIX + "/bindings/1/reviews")
    assert response.status_code == 200, response.text
    return response.json()["items"][0]


async def reply(env, **updates):
    row = await current_review(env)
    body = {"request_id": str(uuid4()), "review_name": row["name"], "expected_version": row["version"], "reply": "Thank you for your visit.", "confirmed": True, **updates}
    return await env.client.post(PREFIX + "/bindings/1/review-replies", json=body), body


async def ready_task(env, **updates):
    values = {"customer_id": 10, "customer_name": "Synthetic Invited Merchant", "title": "Approved Synthetic Post", "platform": "google_business", "due_at": datetime.now(timezone.utc), "timezone": "America/Los_Angeles", "assignee_id": 2, "assignee_name": OPS.name, "content": "Our confirmed opening hours remain unchanged.", "status": "ready", "revision": 3, "created_by_id": 1, "client_request_id": str(uuid4()), "creation_fingerprint": "f" * 64, **updates}
    async with env.sessions() as db:
        row = MediaOperationTask(**values); db.add(row); await db.flush()
        db.add(MediaOperationEvent(task_id=row.id, revision=3, action="approve", actor_id=1, actor_name=OWNER.name, before_status="in_review", after_status="ready", snapshot={"content": values["content"], "material_id": values.get("material_id")}, request_id=str(uuid4())))
        await db.commit()
        return row.id


async def publish(env, task_id, **updates):
    body = {"request_id": str(uuid4()), "task_id": task_id, "expected_revision": 3, "confirmed": True, **updates}
    return await env.client.post(PREFIX + "/bindings/1/posts", json=body), body


async def reviewed_image_task(env):
    """Use the real create/submit/owner-approve flow to freeze a public image."""
    original_user = env.user
    env.user = OWNER
    response = await env.client.post("/api/v1/media-operations", json={
        "client_request_id": str(uuid4()), "customer_id": 10, "title": "Actually approved Google image post", "platform": "google_business",
        "due_at": datetime.now(timezone.utc).isoformat(), "timezone": "America/Los_Angeles", "assignee_id": 2,
        "content": "Confirmed merchant details, with a specifically reviewed public image.", "material_id": 1001,
    })
    assert response.status_code == 201, response.text
    row = response.json(); env.user = OPS
    response = await env.client.post(f"/api/v1/media-operations/{row['id']}/transition", json={"request_id": str(uuid4()), "expected_revision": row["revision"], "action": "submit"})
    assert response.status_code == 200, response.text
    row = response.json(); env.user = OWNER
    response = await env.client.post(f"/api/v1/media-operations/{row['id']}/transition", json={"request_id": str(uuid4()), "expected_revision": row["revision"], "action": "approve"})
    assert response.status_code == 200, response.text
    env.user = original_user
    return response.json()["id"]


async def mutate_invitation(env, **values):
    async with env.sessions() as db:
        grant = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.customer_id == 10, CustomerAccessGrant.employee_id == 2))
        for key, value in values.items(): setattr(grant, key, value)
        await db.commit()


@pytest.mark.asyncio
async def test_owner_and_staff_status_redaction_and_no_implicit_grants(gbp_env):
    env = gbp_env
    owner = await env.client.get(PREFIX + "/status")
    assert owner.status_code == 200
    assert owner.headers.get("cache-control") == "private, no-store"
    assert [row["id"] for row in owner.json()["connections"]] == [1]
    env.user = OPS
    response = await env.client.get(PREFIX + "/status")
    assert response.status_code == 200
    assert response.json()["connections"] == []
    assert [row["id"] for row in response.json()["bindings"]] == [1]
    for forbidden in ("SECRET-", "token_encrypted", "refresh_token", "access_token", "CLIENT_SECRET", "TOKEN_KEY", "finance_access", "password"):
        assert forbidden not in response.text
    env.user = OTHER
    assert (await env.client.get(PREFIX + "/status")).json()["bindings"] == []
    env.user = ADMIN
    assert (await env.client.get(PREFIX + "/status")).json()["bindings"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["finance", "sales", "design", "sales_partner"])
async def test_other_roles_denied_even_with_forged_broad_role_config(gbp_env, role):
    env = gbp_env; env.user = next(user for user in actors() if user.role == role)
    for path in ("/status", "/options", "/bindings/1/reviews", "/bindings/1/ready-tasks", "/bindings/1/actions"):
        assert (await env.client.get(PREFIX + path)).status_code == 403
    assert (await env.client.post(PREFIX + "/oauth/start", json={"confirmed": True})).status_code == 403
    assert not env.fake.reads and not env.fake.writes


@pytest.mark.asyncio
async def test_staff_cannot_manage_connections_bindings_or_external_grants(gbp_env):
    env = gbp_env; env.user = OPS
    paths = [("GET", "/options", None), ("GET", "/connections/1/locations", None), ("GET", "/bindings/1/grants", None),
             ("POST", "/oauth/start", {"confirmed": True}), ("POST", "/bindings", {"request_id": str(uuid4()), "customer_id": 10, "connection_id": 1, "location_name": LOCATION, "confirmed": True}),
             ("PUT", "/bindings/1/grants", {"expected_revision": 1, "employee_id": 3, "can_reply": True, "can_publish": True}),
             ("POST", "/connections/1/disconnect", {"confirmed": True}), ("POST", "/bindings/1/disconnect", {"confirmed": True, "expected_revision": 1})]
    for method, path, body in paths:
        response = await env.client.request(method, PREFIX + path, json=body)
        assert response.status_code == 403, (path, response.text)
    assert not env.fake.reads and not env.fake.writes


@pytest.mark.asyncio
async def test_reply_idempotency_payload_conflict_and_no_google_original_cache(gbp_env):
    env = gbp_env; env.user = OPS
    response, body = await reply(env)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded"
    duplicate = await env.client.post(PREFIX + "/bindings/1/review-replies", json=body)
    assert duplicate.status_code == 200 and duplicate.json()["id"] == response.json()["id"]
    conflict = await env.client.post(PREFIX + "/bindings/1/review-replies", json={**body, "reply": "A different statement"})
    assert conflict.status_code == 409
    assert len(env.fake.writes) == 1
    async with env.sessions() as db:
        actions = (await db.execute(select(env.Action))).scalars().all()
        values = json.dumps([row.payload for row in actions])
        assert "SECRET-REVIEW-ORIGINAL" not in values and "SECRET-REVIEWER-ORIGINAL" not in values
        connection = await db.get(env.Connection, 1)
        assert "SYNTHETIC-ACCESS-TOKEN" not in connection.token_encrypted
        assert env.provider.decrypt(connection.token_encrypted)["access_token"] == "SYNTHETIC-ACCESS-TOKEN"


@pytest.mark.asyncio
async def test_changed_review_version_fails_before_provider_write(gbp_env):
    env = gbp_env; env.user = OPS
    review = await current_review(env)
    env.fake.review["reviewReply"] = {"comment": "Someone else already replied", "updateTime": "2026-10-30T11:00:00Z"}
    response = await env.client.post(PREFIX + "/bindings/1/review-replies", json={"request_id": str(uuid4()), "review_name": review["name"], "expected_version": review["version"], "reply": "Do not overwrite", "confirmed": True})
    assert response.status_code in {200, 409}
    if response.status_code == 200: assert response.json()["status"] == "failed"
    assert not env.fake.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [HIDDEN_LOCATION + "/reviews/hidden", REVIEW + "?target=other", REVIEW + "/../../reply", "https://attacker.example/steal", REVIEW + "%2fsecret"])
async def test_review_path_and_cross_store_injection_rejected_without_provider(gbp_env, name):
    env = gbp_env; env.user = OPS
    response = await env.client.post(PREFIX + "/bindings/1/review-replies", json={"request_id": str(uuid4()), "review_name": name, "expected_version": "a" * 64, "reply": "Synthetic", "confirmed": True})
    assert response.status_code == 422, response.text
    assert not env.fake.reads and not env.fake.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["revoked", "read_only", "inactive_employee", "owner_disabled", "google_grant_revoked"])
async def test_current_permissions_fence_reads_writes_and_idempotency_replay(gbp_env, mutation):
    env = gbp_env; env.user = OPS
    response, body = await reply(env)
    assert response.status_code == 200
    if mutation == "revoked": await mutate_invitation(env, invitation_status="revoked")
    elif mutation == "read_only": await mutate_invitation(env, access_level="read_only", scopes={"delivery": "read_only", "materials": "read_only"})
    else:
        async with env.sessions() as db:
            if mutation in {"inactive_employee", "owner_disabled"}:
                employee = await db.get(Employees, 2 if mutation == "inactive_employee" else 1); employee.status = "disabled"
            else:
                grant = await db.scalar(select(env.Grant).where(env.Grant.employee_id == 2)); grant.can_reply = grant.can_publish = False
            await db.commit()
    replay = await env.client.post(PREFIX + "/bindings/1/review-replies", json=body)
    assert replay.status_code in {403, 404}, replay.text
    assert len(env.fake.writes) == 1
    if mutation != "read_only": assert (await env.client.get(PREFIX + "/bindings/1/reviews")).status_code in {403, 404}


@pytest.mark.asyncio
async def test_reply_and_publish_grants_are_independent(gbp_env):
    env = gbp_env; env.user = OPS
    async with env.sessions() as db:
        grant = await db.scalar(select(env.Grant).where(env.Grant.employee_id == 2)); grant.can_publish = False
        await db.commit()
    response, _ = await reply(env)
    assert response.status_code == 200
    task_id = await ready_task(env)
    response, _ = await publish(env, task_id)
    assert response.status_code == 403
    assert len(env.fake.writes) == 1


@pytest.mark.asyncio
async def test_post_requires_approved_customer_platform_revision_and_assignee(gbp_env):
    env = gbp_env; env.user = OPS
    for updates in ({"status": "draft"}, {"status": "in_review"}, {"platform": "instagram"}, {"assignee_id": 3}, {"customer_id": 20}, {"revision": 4}):
        identity = await ready_task(env, **updates)
        response, _ = await publish(env, identity)
        assert response.status_code in {403, 404, 409, 422}, (updates, response.text)
    listing = await env.client.get(PREFIX + "/bindings/1/ready-tasks")
    assert listing.status_code == 200
    assert all(row["title"] != "SECRET-HIDDEN-TITLE" for row in listing.json()["items"])
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_ready_flag_without_real_approval_event_cannot_publish(gbp_env):
    env = gbp_env; env.user = OPS
    identity = await ready_task(env)
    async with env.sessions() as db:
        events = (await db.execute(select(MediaOperationEvent).where(MediaOperationEvent.task_id == identity))).scalars().all()
        for event in events: await db.delete(event)
        await db.commit()
    response, _ = await publish(env, identity)
    assert response.status_code == 422 and not env.fake.writes


@pytest.mark.asyncio
async def test_changed_content_after_approval_cannot_be_published(gbp_env):
    env = gbp_env; env.user = OPS
    identity = await ready_task(env)
    async with env.sessions() as db:
        row = await db.get(MediaOperationTask, identity); row.content = "Unreviewed content changed after approval"
        await db.commit()
    response, _ = await publish(env, identity)
    assert response.status_code == 422 and not env.fake.writes


@pytest.mark.asyncio
async def test_real_owner_reviewed_image_reference_is_publishable(gbp_env):
    env = gbp_env; env.user = OPS
    identity = await reviewed_image_task(env)
    response, _ = await publish(env, identity)
    assert response.status_code == 200 and response.json()["status"] == "succeeded", response.text
    assert env.fake.writes[0][2]["media"] == [{"mediaFormat": "PHOTO", "sourceUrl": "https://images.example.com/synthetic.png"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["file_url", "updated_at", "visibility", "customer_id", "legacy_missing_fingerprint"])
async def test_changed_or_unfrozen_image_reference_requires_new_review(gbp_env, change):
    env = gbp_env; env.user = OPS
    identity = await reviewed_image_task(env)
    async with env.sessions() as db:
        material = await db.get(Customer_materials, 1001)
        if change == "file_url": material.file_url = "https://images.example.com/unreviewed-image.png"
        elif change == "updated_at": material.updated_at = datetime.now(timezone.utc)
        elif change == "visibility": material.visibility = "owner"
        elif change == "customer_id": material.customer_id = 20
        else:
            event = await db.scalar(select(MediaOperationEvent).where(MediaOperationEvent.task_id == identity, MediaOperationEvent.action == "approve"))
            event.snapshot = {key: value for key, value in event.snapshot.items() if key != "google_material_fingerprint"}
        await db.commit()
    response, _ = await publish(env, identity)
    assert response.status_code in {403, 422} and not env.fake.writes, response.text


@pytest.mark.asyncio
async def test_post_idempotency_cross_uuid_duplicate_and_original_tables_unchanged(gbp_env):
    env = gbp_env; env.user = OPS
    async with env.sessions() as db:
        original = (await db.execute(text("SELECT * FROM financial_canary"))).all()
        settings = (await db.execute(text("SELECT * FROM app_settings"))).all()
        invitation = (await db.execute(text("SELECT * FROM customer_access_grants ORDER BY id"))).all()
    identity = await ready_task(env)
    response, body = await publish(env, identity)
    assert response.status_code == 200 and response.json()["status"] == "succeeded", response.text
    replay = await env.client.post(PREFIX + "/bindings/1/posts", json=body)
    assert replay.status_code == 200 and replay.json()["id"] == response.json()["id"]
    repeat, _ = await publish(env, identity)
    assert repeat.status_code == 409
    assert len(env.fake.writes) == 1
    async with env.sessions() as db:
        assert (await db.execute(text("SELECT * FROM financial_canary"))).all() == original
        assert (await db.execute(text("SELECT * FROM app_settings"))).all() == settings
        assert (await db.execute(text("SELECT * FROM customer_access_grants ORDER BY id"))).all() == invitation
        task = await db.get(MediaOperationTask, identity)
        assert task.status == "ready" and task.revision == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["reply", "post"])
async def test_uncertain_write_never_automatically_resubmits_and_read_reconciles(gbp_env, kind):
    env = gbp_env; env.user = OPS; env.fake.failure = "timeout_after"
    if kind == "reply": response, body = await reply(env); endpoint = "/bindings/1/review-replies"
    else: identity = await ready_task(env); response, body = await publish(env, identity); endpoint = "/bindings/1/posts"
    assert response.status_code == 200 and response.json()["status"] == "unknown", response.text
    identity = response.json()["id"]
    repeated = await env.client.post(PREFIX + endpoint, json=body)
    assert repeated.status_code == 200 and repeated.json()["id"] == identity
    assert len(env.fake.writes) == 1
    env.fake.failure = None
    result = await env.client.post(f"{PREFIX}/actions/{identity}/reconcile", json={"confirmed": True})
    assert result.status_code == 200 and result.json()["status"] == ("succeeded" if kind == "reply" else "unknown"), result.text
    assert len(env.fake.writes) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["reply", "post"])
async def test_cancelled_http_write_keeps_durable_reservation_and_never_resends(gbp_env, kind):
    env = gbp_env; env.user = OPS; env.fake.failure = "cancel_after"
    if kind == "reply":
        review = await current_review(env)
        endpoint = "/bindings/1/review-replies"
        body = {"request_id": str(uuid4()), "review_name": REVIEW, "expected_version": review["version"], "reply": "Thank you for visiting.", "confirmed": True}
    else:
        endpoint = "/bindings/1/posts"
        body = {"request_id": str(uuid4()), "task_id": await ready_task(env), "expected_revision": 3, "confirmed": True}
    with pytest.raises(asyncio.CancelledError):
        await env.client.post(PREFIX + endpoint, json=body)
    env.fake.failure = None
    recovery = await env.client.get(PREFIX + "/requests/" + body["request_id"])
    assert recovery.status_code == 200 and recovery.json()["status"] == "pending"
    replay = await env.client.post(PREFIX + endpoint, json=body)
    assert replay.status_code == 200 and replay.json()["id"] == recovery.json()["id"]
    assert len(env.fake.writes) == 1
    result = await env.client.post(f"{PREFIX}/actions/{recovery.json()['id']}/reconcile", json={"confirmed": True})
    assert result.status_code == 200 and result.json()["status"] == ("succeeded" if kind == "reply" else "unknown")
    assert len(env.fake.writes) == 1


@pytest.mark.asyncio
async def test_unmatched_unknown_post_blocks_new_request_and_remains_unknown(gbp_env):
    env = gbp_env; env.user = OPS; env.fake.failure = "uncertain_before"
    task_id = await ready_task(env)
    response, _ = await publish(env, task_id)
    assert response.json()["status"] == "unknown"
    env.fake.failure = None
    reread = await env.client.post(f"{PREFIX}/actions/{response.json()['id']}/reconcile", json={"confirmed": True})
    assert reread.json()["status"] == "unknown"
    repeat, _ = await publish(env, task_id)
    assert repeat.status_code == 409 and len(env.fake.writes) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("state,status", [("PROCESSING", "accepted"), ("LIVE", "succeeded"), ("REJECTED", "rejected")])
async def test_google_processing_and_public_success_are_distinct(gbp_env, state, status):
    env = gbp_env; env.user = OPS; env.fake.post_state = state
    response, _ = await publish(env, await ready_task(env))
    assert response.status_code == 200 and response.json()["status"] == status


@pytest.mark.asyncio
@pytest.mark.parametrize("state,status", [("PENDING", "accepted"), (None, "accepted"), ("APPROVED", "succeeded"), ("REJECTED", "rejected")])
async def test_reply_moderation_is_distinct_from_public_success(gbp_env, state, status):
    env = gbp_env; env.user = OPS; env.fake.reply_state = state
    response, _ = await reply(env)
    assert response.status_code == 200 and response.json()["status"] == status, response.text


@pytest.mark.asyncio
async def test_reply_enforces_google_utf8_byte_limit_not_python_character_count(gbp_env):
    env = gbp_env; env.user = OPS
    response, _ = await reply(env, reply="谢" * 1400)
    assert response.status_code == 422 and not env.fake.writes


@pytest.mark.asyncio
async def test_provider_body_and_tokens_are_never_reflected(gbp_env):
    env = gbp_env; env.user = OPS; env.fake.failure = "secret_error"
    response, _ = await reply(env)
    assert response.status_code == 200 and response.json()["status"] == "failed"
    assert "SECRET-" not in response.text and "SYNTHETIC-ACCESS" not in response.text


@pytest.mark.asyncio
async def test_same_request_double_click_cannot_dispatch_two_posts(gbp_env):
    env = gbp_env; env.user = OPS
    identity = await ready_task(env)
    body = {"request_id": str(uuid4()), "task_id": identity, "expected_revision": 3, "confirmed": True}
    replies = await asyncio.gather(*(env.client.post(PREFIX + "/bindings/1/posts", json=body) for _ in range(2)))
    assert all(response.status_code in {200, 409} for response in replies), [r.text for r in replies]
    assert any(response.status_code == 200 for response in replies)
    assert len(env.fake.writes) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [{"connection_id": 2}, {"access_token": "FORGED"}, {"publish_without_review": True}])
async def test_strict_action_bodies_reject_privileged_extra_fields(gbp_env, extra):
    env = gbp_env; env.user = OPS
    body = {"request_id": str(uuid4()), "review_name": REVIEW, "expected_version": "a" * 64, "reply": "Synthetic", "confirmed": True, **extra}
    response = await env.client.post(PREFIX + "/bindings/1/review-replies", json=body)
    assert response.status_code == 422 and not env.fake.writes


@pytest.mark.asyncio
async def test_oauth_owner_pkce_cookie_replay_and_encrypted_storage(gbp_env):
    env = gbp_env
    started = await env.client.post(PREFIX + "/oauth/start", json={"confirmed": True})
    assert started.status_code == 200, started.text
    url = urlsplit(started.json()["authorization_url"]); values = parse_qs(url.query)
    assert url.scheme == "https" and url.hostname == "accounts.google.com"
    assert values["scope"] == [env.provider.SCOPE] and values["code_challenge_method"] == ["S256"]
    assert values["redirect_uri"] == ["https://crm.example.com" + env.provider.CALLBACK_PATH]
    cookie = started.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    assert "CLIENT_SECRET" not in started.text and "TOKEN_KEY" not in started.text
    params = {"state": values["state"][0], "code": "SYNTHETIC-OAUTH-CODE"}
    response = await env.client.get(PREFIX + "/oauth/callback", params=params)
    assert response.status_code in {302, 303, 307}
    assert response.headers["location"].endswith("/media-ops?google=connected")
    assert "code=" not in response.headers["location"]
    repeated = await env.client.get(PREFIX + "/oauth/callback", params=params)
    assert repeated.headers["location"].endswith("/media-ops?google=failed")
    assert len(env.fake.exchange_calls) == 1
    expected_challenge = base64.urlsafe_b64encode(hashlib.sha256(env.fake.exchange_calls[0][1].encode()).digest()).decode().rstrip("=")
    assert values["code_challenge"] == [expected_challenge]
    async with env.sessions() as db:
        states = (await db.execute(select(env.OAuthState))).scalars().all()
        assert all(row.consumed and row.verifier_encrypted == "" for row in states)
        rows = (await db.execute(select(env.Connection))).scalars().all()
        assert len(rows) == 3
        assert all("SYNTHETIC-OAUTH-CODE" not in (row.token_encrypted or "") for row in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("attack", ["missing_cookie", "wrong_cookie", "expired", "owner_disabled"])
async def test_oauth_invalid_state_context_never_exchanges_code(gbp_env, attack):
    env = gbp_env
    started = await env.client.post(PREFIX + "/oauth/start", json={"confirmed": True})
    values = parse_qs(urlsplit(started.json()["authorization_url"]).query)
    if attack == "missing_cookie": env.client.cookies.clear()
    if attack == "wrong_cookie":
        env.client.cookies.clear(); env.client.cookies.set(env.service.COOKIE, "WRONG-COOKIE", domain="crm.example.com", path=env.provider.CALLBACK_PATH)
    if attack in {"expired", "owner_disabled"}:
        async with env.sessions() as db:
            if attack == "expired":
                row = await db.scalar(select(env.OAuthState)); row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            else:
                row = await db.get(Employees, 1); row.status = "disabled"
            await db.commit()
    response = await env.client.get(PREFIX + "/oauth/callback", params={"state": values["state"][0], "code": "SYNTHETIC-OAUTH-CODE"})
    assert response.status_code in {302, 303, 307} and response.headers["location"].endswith("/media-ops?google=failed")
    assert not env.fake.exchange_calls


@pytest.mark.asyncio
async def test_dedicated_google_config_does_not_fall_back_to_private_credentials(gbp_env):
    env = gbp_env
    for suffix in ("CLIENT_ID", "CLIENT_SECRET", "TOKEN_KEY", "PUBLIC_URL", "API_APPROVED"):
        env.monkeypatch.delenv("T24_GBP_" + suffix, raising=False)
    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "PRIVATE_WORKSPACE_GOOGLE_CLIENT_ID", "PRIVATE_WORKSPACE_GOOGLE_CLIENT_SECRET", "PRIVATE_WORKSPACE_PUBLIC_URL"):
        env.monkeypatch.setenv(key, "SECRET-PRIVATE-CREDENTIAL")
    status = await env.client.get(PREFIX + "/status")
    assert status.status_code == 200 and not status.json()["configured"]
    response = await env.client.post(PREFIX + "/oauth/start", json={"confirmed": True})
    assert response.status_code == 503
    assert "SECRET-PRIVATE-CREDENTIAL" not in status.text + response.text and not env.fake.exchange_calls


@pytest.mark.parametrize("url", ["http://images.example.com/a.png", "https://127.0.0.1/a.png", "https://user:password@images.example.com/a.png", "https://images.example.com/a.png?token=SECRET", "https://images.example.com/a.png#SECRET", "https://secret.internal/a.png", "https://localhost/a.png", "https://192.168.1.1/a.png", "https://[::1]/a.png"])
def test_public_image_url_never_exports_private_or_signed_assets(url):
    from services.google_business_provider import public_image_url
    assert public_image_url(url) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("api,path", [("business", "https://attacker.example"), ("business", "../secrets"), ("business", "accounts/1?target=secret"), ("business", "accounts/1%2flocations/2"), ("unknown", "accounts")])
async def test_provider_cannot_be_used_as_arbitrary_url_or_path_proxy(gbp_env, api, path):
    env = gbp_env
    class NeverNetwork(env.real_client):
        async def _access(self): raise AssertionError("invalid resource reached token access")
        async def _raw(self, *args, **kwargs): raise AssertionError("invalid resource reached network")
    with pytest.raises(env.provider.ProviderError):
        await NeverNetwork().request("GET", api, path)


@pytest.mark.asyncio
async def test_grant_updates_are_owner_only_revisioned_and_do_not_change_customer_invites(gbp_env):
    env = gbp_env
    async with env.sessions() as db:
        original = (await db.execute(text("SELECT * FROM customer_access_grants ORDER BY id"))).all()
    result = await env.client.put(PREFIX + "/bindings/1/grants", json={"expected_revision": 1, "employee_id": 3, "can_reply": True, "can_publish": False})
    assert result.status_code == 200 and result.json()["revision"] == 2
    employee = next(item for item in result.json()["employees"] if item["employee_id"] == 3)
    assert employee["can_reply"] and not employee["can_publish"]
    stale = await env.client.put(PREFIX + "/bindings/1/grants", json={"expected_revision": 1, "employee_id": 3, "can_reply": False, "can_publish": False})
    assert stale.status_code == 409
    invalid = await env.client.put(PREFIX + "/bindings/1/grants", json={"expected_revision": 2, "employee_id": 5, "can_reply": True, "can_publish": True})
    assert invalid.status_code in {403, 422}
    async with env.sessions() as db:
        assert (await db.execute(text("SELECT * FROM customer_access_grants ORDER BY id"))).all() == original
    env.user = OTHER
    assert (await env.client.get(PREFIX + "/status")).json()["bindings"][0]["permissions"] == {"can_read": True, "can_reply": True, "can_publish": False, "can_manage": False}


@pytest.mark.asyncio
async def test_second_owner_cannot_take_over_first_owner_connection_or_binding(gbp_env):
    env = gbp_env; env.user = SECOND_OWNER
    status = await env.client.get(PREFIX + "/status")
    assert status.status_code == 200
    assert [row["id"] for row in status.json()["connections"]] == [2]
    assert [row["id"] for row in status.json()["bindings"]] == [2]
    assert (await env.client.get(PREFIX + "/connections/1/locations")).status_code == 404
    assert (await env.client.get(PREFIX + "/bindings/1/grants")).status_code == 404
    assert (await env.client.post(PREFIX + "/connections/1/disconnect", json={"confirmed": True})).status_code == 404
    assert not env.fake.reads and not env.fake.writes


@pytest.mark.asyncio
async def test_disconnect_scrubs_own_tokens_and_all_delegations_without_touching_invitations(gbp_env):
    env = gbp_env
    async with env.sessions() as db:
        original = (await db.execute(text("SELECT * FROM customer_access_grants ORDER BY id"))).all()
    response = await env.client.post(PREFIX + "/connections/1/disconnect", json={"confirmed": True})
    assert response.status_code == 200 and response.json()["disconnected"]
    async with env.sessions() as db:
        connection = await db.get(env.Connection, 1)
        binding = await db.get(env.Binding, 1)
        grant = await db.scalar(select(env.Grant).where(env.Grant.employee_id == 2))
        assert connection.token_encrypted is None and not connection.active
        assert not binding.active and not grant.can_reply and not grant.can_publish
        assert (await db.execute(text("SELECT * FROM customer_access_grants ORDER BY id"))).all() == original
        other = await db.get(env.Connection, 2)
        assert other.active and other.token_encrypted
    env.user = OPS
    assert (await env.client.get(PREFIX + "/bindings/1/reviews")).status_code == 404
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_binding_requires_current_owner_discovery_and_exact_customer_mapping(gbp_env):
    env = gbp_env
    async with env.sessions() as db:
        db.add(Customers(id=30, business_name="New Synthetic Merchant", contact_name="Synthetic", phone="333")); await db.commit()
    body = {"request_id": str(uuid4()), "customer_id": 30, "connection_id": 1, "location_name": HIDDEN_LOCATION, "confirmed": True}
    not_discovered = await env.client.post(PREFIX + "/bindings", json=body)
    assert not_discovered.status_code == 422
    body.update(location_name=LOCATION)
    already_bound = await env.client.post(PREFIX + "/bindings", json=body)
    assert already_bound.status_code == 409
    body.update(connection_id=2)
    wrong_owner = await env.client.post(PREFIX + "/bindings", json=body)
    assert wrong_owner.status_code == 404
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_same_global_google_location_under_another_account_cannot_bind_different_customer(gbp_env):
    env = gbp_env
    async with env.sessions() as db:
        db.add(Customers(id=30, business_name="New Synthetic Merchant", contact_name="Synthetic", phone="333")); await db.commit()
    alias = "accounts/300/locations/1000"
    env.fake.location_items.append({"location_name": alias, "title": "Same physical Google location via another parent", "address": "100 Synthetic Street, CA"})
    response = await env.client.post(PREFIX + "/bindings", json={"request_id": str(uuid4()), "customer_id": 30, "connection_id": 1, "location_name": alias, "confirmed": True})
    assert response.status_code == 409, "A globally identical location cannot be attached to a second CRM customer through an account alias"
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_revocation_after_reservation_prevents_dispatch_and_records_not_sent(gbp_env):
    env = gbp_env; env.user = OPS
    version = (await current_review(env))["version"]
    async with env.sessions() as db:
        ctx = await env.service.context(db, OPS)
        action_id, fresh = await env.service._reserve(db, ctx, 1, "review_reply", str(uuid4()), {"comment": "Do not send after revoke"}, target_name=REVIEW, expected_version=version)
        assert fresh
    await mutate_invitation(env, invitation_status="revoked")
    from fastapi import HTTPException
    async with env.sessions() as db:
        with pytest.raises(HTTPException) as info:
            await env.service._dispatch(db, OPS, action_id, expected_version=version)
        assert info.value.status_code in {403, 404}
    async with env.sessions() as db:
        row = await db.get(env.Action, action_id)
        assert row.status == "failed", "A known not-dispatched reservation must not stay pending forever"
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_slow_google_review_read_does_not_hold_company_database_write_lock(gbp_env):
    env = gbp_env; env.user = OPS
    env.fake.read_started = asyncio.Event(); env.fake.release_read = asyncio.Event()
    reading = asyncio.create_task(env.client.get(PREFIX + "/bindings/1/reviews"))
    async def unrelated_company_write():
        async with env.sessions() as db:
            await db.execute(text("UPDATE financial_canary SET amount='200.00' WHERE id=1"))
            await db.commit()
    try:
        await asyncio.wait_for(env.fake.read_started.wait(), timeout=2)
        await asyncio.wait_for(unrelated_company_write(), timeout=0.75)
    finally:
        env.fake.release_read.set()
        response = await reading
    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["reply", "post"])
@pytest.mark.parametrize("revoke", [None, "google_grant", "customer_invite", "connection"])
async def test_slow_public_write_releases_company_writer_and_records_result_after_dispatch_revoke(gbp_env, kind, revoke):
    env = gbp_env; env.user = OPS
    if kind == "reply":
        review = await current_review(env)
        endpoint = "/bindings/1/review-replies"
        body = {"request_id": str(uuid4()), "review_name": REVIEW, "expected_version": review["version"], "reply": "Thank you for visiting.", "confirmed": True}
    else:
        endpoint = "/bindings/1/posts"
        body = {"request_id": str(uuid4()), "task_id": await ready_task(env), "expected_revision": 3, "confirmed": True}
    env.fake.write_started = asyncio.Event(); env.fake.release_write = asyncio.Event()
    writing = asyncio.create_task(env.client.post(PREFIX + endpoint, json=body))
    try:
        await asyncio.wait_for(env.fake.write_started.wait(), timeout=2)
        async def unrelated_write_and_optional_revoke():
            async with env.sessions() as db:
                reservation = await db.scalar(select(env.Action).where(env.Action.request_id == body["request_id"]))
                assert reservation and reservation.dispatch_started_at is not None and reservation.status == "pending"
                await db.execute(text("UPDATE financial_canary SET amount='200.00' WHERE id=1"))
                if revoke == "google_grant":
                    row = await db.scalar(select(env.Grant).where(env.Grant.employee_id == 2)); row.can_reply = row.can_publish = False
                elif revoke == "customer_invite":
                    row = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id == 2)); row.invitation_status = "revoked"
                elif revoke == "connection":
                    row = await db.get(env.Connection, 1); row.active = False; row.token_encrypted = None
                await db.commit()
        await asyncio.wait_for(unrelated_write_and_optional_revoke(), timeout=0.75)
    finally:
        env.fake.release_write.set()
        result = await writing
    if revoke:
        assert result.status_code in {403, 404} and "Thank you" not in result.text
    else:
        assert result.status_code == 200 and result.json()["status"] == "succeeded", result.text
    async with env.sessions() as db:
        reservation = await db.scalar(select(env.Action).where(env.Action.request_id == body["request_id"]))
        assert reservation.status == "succeeded" and reservation.dispatch_started_at is not None
        assert (await db.execute(text("SELECT amount FROM financial_canary WHERE id=1"))).scalar() == "200.00"
        if revoke == "connection":
            connection = await db.get(env.Connection, 1)
            assert not connection.active and connection.token_encrypted is None
    if revoke:
        repeated = await env.client.post(PREFIX + endpoint, json={**body, "request_id": str(uuid4())})
        assert repeated.status_code in {403, 404}
    assert len(env.fake.writes) == 1


@pytest.mark.asyncio
async def test_revoke_during_pre_dispatch_google_read_prevents_public_reply(gbp_env):
    env = gbp_env; env.user = OPS
    review = await current_review(env)
    body = {"request_id": str(uuid4()), "review_name": REVIEW, "expected_version": review["version"], "reply": "Do not send after revoke.", "confirmed": True}
    env.fake.read_started = asyncio.Event(); env.fake.release_read = asyncio.Event()
    writing = asyncio.create_task(env.client.post(PREFIX + "/bindings/1/review-replies", json=body))
    try:
        await asyncio.wait_for(env.fake.read_started.wait(), timeout=2)
        async with env.sessions() as db:
            reservation = await db.scalar(select(env.Action).where(env.Action.request_id == body["request_id"]))
            assert reservation and reservation.dispatch_started_at is None
            row = await db.scalar(select(env.Grant).where(env.Grant.employee_id == 2)); row.can_reply = row.can_publish = False
            await db.commit()
    finally:
        env.fake.release_read.set()
        result = await writing
    assert result.status_code in {403, 404} and not env.fake.writes
    async with env.sessions() as db:
        reservation = await db.scalar(select(env.Action).where(env.Action.request_id == body["request_id"]))
        assert reservation.status == "failed" and reservation.dispatch_started_at is None


@pytest.mark.asyncio
async def test_owner_can_return_ready_google_task_fix_image_and_reapprove_without_recreating(gbp_env):
    env = gbp_env; env.user = OPS
    task_id = await reviewed_image_task(env)
    async with env.sessions() as db:
        image = await db.get(Customer_materials, 1001); image.file_url = "https://images.example.com/new-reviewed-image.png"
        await db.commit()
    blocked, _ = await publish(env, task_id)
    assert blocked.status_code == 422 and not env.fake.writes
    env.user = OWNER
    body = {"request_id": str(uuid4()), "expected_revision": 3, "action": "return", "note": "重新核对当前图片引用"}
    returned = await env.client.post(f"/api/v1/media-operations/{task_id}/transition", json=body)
    assert returned.status_code == 200 and returned.json()["status"] == "draft" and returned.json()["revision"] == 4, returned.text
    repeated = await env.client.post(f"/api/v1/media-operations/{task_id}/transition", json=body)
    assert repeated.status_code == 200 and repeated.json()["revision"] == 4
    env.user = OPS
    submitted = await env.client.post(f"/api/v1/media-operations/{task_id}/transition", json={"request_id": str(uuid4()), "expected_revision": 4, "action": "submit"})
    assert submitted.status_code == 200
    env.user = OWNER
    approved = await env.client.post(f"/api/v1/media-operations/{task_id}/transition", json={"request_id": str(uuid4()), "expected_revision": 5, "action": "approve"})
    assert approved.status_code == 200 and approved.json()["revision"] == 6
    env.user = OPS
    published, _ = await publish(env, task_id, expected_revision=6)
    assert published.status_code == 200 and published.json()["status"] == "succeeded", published.text
    assert env.fake.writes[0][2]["media"][0]["sourceUrl"] == "https://images.example.com/new-reviewed-image.png"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "unknown", "accepted", "succeeded"])
async def test_active_or_sent_google_post_blocks_return_and_is_hidden_from_ready_picker(gbp_env, status):
    env = gbp_env
    identity = await ready_task(env)
    async with env.sessions() as db:
        db.add(env.Action(binding_id=1, customer_id=10, kind="post_publish", request_id=str(uuid4()), fingerprint="f" * 64, actor_id=2, actor_name=OPS.name,
                          task_id=identity, payload={"summary": "Synthetic"}, status=status, dispatch_started_at=datetime.now(timezone.utc) if status != "pending" else None))
        await db.commit()
    detail = await env.client.get(f"/api/v1/media-operations/{identity}")
    assert detail.status_code == 200 and not detail.json()["permissions"]["can_return"]
    response = await env.client.post(f"/api/v1/media-operations/{identity}/transition", json={"request_id": str(uuid4()), "expected_revision": 3, "action": "return", "note": "不得将已经发送的任务重新发布"})
    assert response.status_code == 409
    ready = await env.client.get(PREFIX + "/bindings/1/ready-tasks")
    assert ready.status_code == 200 and identity not in [row["id"] for row in ready.json()["items"]]
    assert not env.fake.writes


@pytest.mark.asyncio
async def test_operator_cannot_return_ready_google_and_owner_cannot_change_other_platform_flow(gbp_env):
    env = gbp_env
    google_id = await ready_task(env)
    env.user = OPS
    forbidden = await env.client.post(f"/api/v1/media-operations/{google_id}/transition", json={"request_id": str(uuid4()), "expected_revision": 3, "action": "return", "note": "员工不得自行取消老板审核"})
    assert forbidden.status_code == 403
    env.user = OWNER
    other_id = await ready_task(env, platform="instagram")
    unchanged = await env.client.post(f"/api/v1/media-operations/{other_id}/transition", json={"request_id": str(uuid4()), "expected_revision": 3, "action": "return", "note": "其他平台的原状态条件保持不变"})
    assert unchanged.status_code == 409


@pytest.mark.asyncio
async def test_owner_return_during_slow_google_post_is_promptly_blocked_without_resend(gbp_env):
    env = gbp_env; env.user = OPS
    task_id = await ready_task(env)
    env.fake.write_started = asyncio.Event(); env.fake.release_write = asyncio.Event()
    writing = asyncio.create_task(publish(env, task_id))
    try:
        await asyncio.wait_for(env.fake.write_started.wait(), timeout=2)
        env.user = OWNER
        returning = env.client.post(f"/api/v1/media-operations/{task_id}/transition", json={"request_id": str(uuid4()), "expected_revision": 3, "action": "return", "note": "发送中的任务不得退回重发"})
        result = await asyncio.wait_for(returning, timeout=0.75)
        assert result.status_code == 409
    finally:
        env.fake.release_write.set()
        posted, _ = await writing
    assert posted.status_code == 200 and posted.json()["status"] == "succeeded" and len(env.fake.writes) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["customer_invite", "google_grant", "connection"])
async def test_google_read_rechecks_access_after_network_before_returning_content(gbp_env, revocation):
    env = gbp_env; env.user = OPS
    env.fake.read_started = asyncio.Event(); env.fake.release_read = asyncio.Event()
    reading = asyncio.create_task(env.client.get(PREFIX + "/bindings/1/reviews"))
    try:
        await asyncio.wait_for(env.fake.read_started.wait(), timeout=2)
        async with env.sessions() as db:
            if revocation == "customer_invite":
                row = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id == 2)); row.invitation_status = "revoked"
            elif revocation == "google_grant":
                row = await db.scalar(select(env.Grant).where(env.Grant.employee_id == 2)); row.can_reply = row.can_publish = False
            else:
                row = await db.get(env.Connection, 1); row.active = False; row.token_encrypted = None
            await db.commit()
    finally:
        env.fake.release_read.set()
        response = await reading
    assert response.status_code in {403, 404} and "SECRET-REVIEW" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke", [False, True])
async def test_slow_reconciliation_releases_company_writer_and_rechecks_grants(gbp_env, revoke):
    env = gbp_env; env.user = OPS; env.fake.failure = "timeout_after"
    response, _ = await reply(env)
    assert response.json()["status"] == "unknown"
    identity = response.json()["id"]; env.fake.failure = None
    env.fake.read_started = asyncio.Event(); env.fake.release_read = asyncio.Event()
    reading = asyncio.create_task(env.client.post(f"{PREFIX}/actions/{identity}/reconcile", json={"confirmed": True}))
    try:
        await asyncio.wait_for(env.fake.read_started.wait(), timeout=2)
        async def unrelated_write():
            async with env.sessions() as db:
                await db.execute(text("UPDATE financial_canary SET amount='200.00' WHERE id=1"))
                if revoke:
                    grant = await db.scalar(select(env.Grant).where(env.Grant.employee_id == 2)); grant.can_reply = grant.can_publish = False
                await db.commit()
        await asyncio.wait_for(unrelated_write(), timeout=0.75)
    finally:
        env.fake.release_read.set()
        result = await reading
    if revoke: assert result.status_code in {403, 404} and "Thank you" not in result.text
    else: assert result.status_code == 200 and result.json()["status"] == "succeeded"
    assert len(env.fake.writes) == 1


@pytest.mark.asyncio
async def test_late_reconciliation_cannot_downgrade_newer_terminal_result(gbp_env):
    env = gbp_env; env.user = OPS; env.fake.post_state = "PROCESSING"
    response, _ = await publish(env, await ready_task(env))
    assert response.json()["status"] == "accepted"
    identity = response.json()["id"]
    env.fake.read_started = asyncio.Event(); env.fake.release_read = asyncio.Event()
    reading = asyncio.create_task(env.client.post(f"{PREFIX}/actions/{identity}/reconcile", json={"confirmed": True}))
    try:
        await asyncio.wait_for(env.fake.read_started.wait(), timeout=2)
        async with env.sessions() as db:
            row = await db.get(env.Action, identity)
            row.status = "succeeded"; row.provider_state = "LIVE"; row.message = "Newer confirmed result"; row.updated_at = datetime.now(timezone.utc) + timedelta(seconds=1)
            await db.commit()
    finally:
        env.fake.release_read.set()
        result = await reading
    assert result.status_code == 200 and result.json()["status"] == "succeeded" and result.json()["provider_state"] == "LIVE"
    assert len(env.fake.writes) == 1


@pytest.mark.asyncio
async def test_unknown_review_blocks_new_uuid_until_read_only_resolution(gbp_env):
    env = gbp_env; env.user = OPS; env.fake.failure = "uncertain_before"
    response, _ = await reply(env)
    assert response.json()["status"] == "unknown"
    again, _ = await reply(env)
    assert again.status_code == 409 and len(env.fake.writes) == 1


@pytest.mark.asyncio
async def test_parallel_different_uuids_cannot_publish_same_approved_task_twice(gbp_env):
    env = gbp_env; env.user = OPS
    task_id = await ready_task(env)
    responses = await asyncio.gather(*(publish(env, task_id) for _ in range(2)))
    assert all(response.status_code in {200, 409} for response, _ in responses), [response.text for response, _ in responses]
    assert sum(response.status_code == 200 for response, _ in responses) == 1
    assert len(env.fake.writes) == 1


@pytest.mark.asyncio
async def test_expired_outbound_payloads_are_scrubbed_without_caching_google_reviews(gbp_env):
    env = gbp_env; env.user = OPS
    async with env.sessions() as db:
        old = env.Action(binding_id=1, customer_id=10, kind="review_reply", request_id=str(uuid4()), fingerprint="f" * 64, actor_id=2, actor_name=OPS.name, target_name=REVIEW,
                         payload={"comment": "EXPIRED-OUTBOUND-CONTENT"}, status="succeeded", created_at=datetime.now(timezone.utc) - timedelta(days=31), updated_at=datetime.now(timezone.utc))
        db.add(old); await db.commit(); old_id = old.id
    response, _ = await reply(env)
    assert response.status_code == 200
    async with env.sessions() as db:
        assert (await db.get(env.Action, old_id)).payload is None
        raw = (await db.execute(text("SELECT payload FROM google_business_actions"))).all()
        assert "SECRET-REVIEW-ORIGINAL" not in repr(raw) and "SECRET-REVIEWER-ORIGINAL" not in repr(raw)


@pytest.mark.asyncio
async def test_real_provider_refresh_uses_dedicated_client_and_encrypts_rotated_token(gbp_env):
    env = gbp_env; requests = []
    real_http = httpx.AsyncClient
    async def handler(request):
        requests.append(request)
        if request.url == "https://oauth2.googleapis.com/token":
            body = parse_qs(request.content.decode())
            assert body["grant_type"] == ["refresh_token"]
            assert body["client_id"] == ["synthetic-client.apps.googleusercontent.com"]
            assert body["client_secret"] == ["SYNTHETIC-CLIENT-SECRET-NOT-REAL"]
            assert body["refresh_token"] == ["SYNTHETIC-REFRESH-TOKEN"]
            return httpx.Response(200, json={"access_token": "ROTATED-ACCESS-TOKEN", "refresh_token": "ROTATED-REFRESH-TOKEN", "expires_in": 3600, "scope": env.provider.SCOPE})
        assert str(request.url).startswith("https://mybusiness.googleapis.com/v4/" + LOCATION + "/reviews")
        assert request.headers["authorization"] == "Bearer ROTATED-ACCESS-TOKEN"
        return httpx.Response(200, json={"reviews": []})
    class LocalTransportClient(real_http):
        def __init__(self, *args, **kwargs):
            assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
            super().__init__(*args, **kwargs, transport=httpx.MockTransport(handler))
    env.monkeypatch.setattr(env.provider.httpx, "AsyncClient", LocalTransportClient)
    async with env.sessions() as db:
        connection = await db.get(env.Connection, 1)
        connection.token_encrypted = env.provider.encrypt({"access_token": "SYNTHETIC-EXPIRED-ACCESS", "refresh_token": "SYNTHETIC-REFRESH-TOKEN", "scope": env.provider.SCOPE, "expires_at": 0})
        assert (await env.real_client(connection).reviews(LOCATION))["reviews"] == []
        await db.commit()
        assert "ROTATED-" not in connection.token_encrypted
        assert env.provider.decrypt(connection.token_encrypted)["refresh_token"] == "ROTATED-REFRESH-TOKEN"
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_google_revoked_refresh_token_becomes_reconnect_required_without_raw_error(gbp_env):
    env = gbp_env; real_http = httpx.AsyncClient; requests = []
    async def handler(request):
        requests.append(request)
        assert str(request.url) == "https://oauth2.googleapis.com/token"
        return httpx.Response(400, json={"error": "invalid_grant", "error_description": "SECRET-PROVIDER-ACCOUNT-DESCRIPTION"})
    class LocalTransportClient(real_http):
        def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs, transport=httpx.MockTransport(handler))
    env.monkeypatch.setattr(env.provider, "GoogleClient", env.real_client)
    env.monkeypatch.setattr(env.provider.httpx, "AsyncClient", LocalTransportClient)
    async with env.sessions() as db:
        connection = await db.get(env.Connection, 1)
        connection.token_encrypted = env.provider.encrypt({"access_token": "SYNTHETIC-EXPIRED-ACCESS", "refresh_token": "SYNTHETIC-REFRESH-TOKEN", "scope": env.provider.SCOPE, "expires_at": 0})
        await db.commit()
    env.user = OPS
    response = await env.client.get(PREFIX + "/bindings/1/reviews")
    assert response.status_code == 503 and "SECRET-" not in response.text
    async with env.sessions() as db:
        connection = await db.get(env.Connection, 1)
        assert connection.needs_reconnect and connection.last_error == "reconnect_required"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_late_invalid_grant_cannot_overwrite_concurrently_refreshed_connection(gbp_env):
    env = gbp_env; real_http = httpx.AsyncClient
    started = asyncio.Event(); release = asyncio.Event()
    async def handler(request):
        assert str(request.url) == "https://oauth2.googleapis.com/token"
        started.set(); await release.wait()
        return httpx.Response(400, json={"error": "invalid_grant", "error_description": "SECRET-STALE-ERROR"})
    class LocalTransportClient(real_http):
        def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs, transport=httpx.MockTransport(handler))
    env.monkeypatch.setattr(env.provider, "GoogleClient", env.real_client)
    env.monkeypatch.setattr(env.provider.httpx, "AsyncClient", LocalTransportClient)
    async with env.sessions() as db:
        connection = await db.get(env.Connection, 1)
        connection.token_encrypted = env.provider.encrypt({"access_token": "SYNTHETIC-EXPIRED-ACCESS", "refresh_token": "SYNTHETIC-OLD-REFRESH", "scope": env.provider.SCOPE, "expires_at": 0})
        await db.commit()
    env.user = OPS
    reading = asyncio.create_task(env.client.get(PREFIX + "/bindings/1/reviews"))
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        async with env.sessions() as db:
            connection = await db.get(env.Connection, 1)
            connection.token_encrypted = env.provider.encrypt({"access_token": "SYNTHETIC-CONCURRENT-ACCESS", "refresh_token": "SYNTHETIC-CONCURRENT-REFRESH", "scope": env.provider.SCOPE, "expires_at": time.time() + 3600})
            connection.needs_reconnect = False; connection.last_error = None
            await db.commit()
    finally:
        release.set()
        response = await reading
    assert response.status_code == 503 and "SECRET-STALE-ERROR" not in response.text
    async with env.sessions() as db:
        connection = await db.get(env.Connection, 1)
        assert not connection.needs_reconnect and connection.last_error is None
        assert env.provider.decrypt(connection.token_encrypted)["refresh_token"] == "SYNTHETIC-CONCURRENT-REFRESH"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [408, 500, 503])
async def test_real_provider_uncertain_http_writes_do_not_retry_or_echo_body(gbp_env, status):
    env = gbp_env; requests = []; real_http = httpx.AsyncClient
    async def handler(request):
        requests.append(request)
        return httpx.Response(status, text="SECRET-PROVIDER-BODY-WITH-TOKENS")
    class LocalTransportClient(real_http):
        def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs, transport=httpx.MockTransport(handler))
    env.monkeypatch.setattr(env.provider.httpx, "AsyncClient", LocalTransportClient)
    with pytest.raises(env.provider.ProviderError) as info:
        await env.real_client()._raw("POST", "https://mybusiness.googleapis.com/v4/" + LOCATION + "/localPosts", body={"summary": "Synthetic"}, write=True)
    assert info.value.uncertain and "SECRET-" not in str(info.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_real_provider_does_not_follow_redirect_with_bearer_token(gbp_env):
    env = gbp_env; requests = []; real_http = httpx.AsyncClient
    async def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://attacker.example/steal"})
    class LocalTransportClient(real_http):
        def __init__(self, *args, **kwargs):
            assert kwargs["follow_redirects"] is False
            super().__init__(*args, **kwargs, transport=httpx.MockTransport(handler))
    env.monkeypatch.setattr(env.provider.httpx, "AsyncClient", LocalTransportClient)
    with pytest.raises(env.provider.ProviderError):
        await env.real_client()._raw("GET", "https://mybusiness.googleapis.com/v4/" + LOCATION + "/reviews", token="SYNTHETIC-ACCESS-TOKEN")
    assert len(requests) == 1 and requests[0].url.host == "mybusiness.googleapis.com"


def test_additive_migration_creates_only_five_empty_tables_and_preserves_existing_rows(tmp_path):
    path = Path(__file__).parents[1] / "alembic/versions/c8d3e5f6a702_google_business.py"
    spec = importlib.util.spec_from_file_location("synthetic_gbp_migration", path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    assert migration.down_revision == "b7c2d9e4a601"
    engine = create_engine("sqlite:///" + str(tmp_path / "migration.db"))
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE original_finance(id INTEGER PRIMARY KEY,amount TEXT,closed INTEGER,owner TEXT)"))
        connection.execute(text("INSERT INTO original_finance VALUES(1,'199.00',1,'original')"))
        connection.execute(text("CREATE TABLE app_settings(config_key TEXT PRIMARY KEY,value_json TEXT)"))
        connection.execute(text("INSERT INTO app_settings VALUES('role_permissions',:value)"), {"value": json.dumps({"unchanged": True})})
        objects_before = connection.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")).all()
        rows_before = connection.execute(text("SELECT * FROM original_finance")).all()
        settings_before = connection.execute(text("SELECT * FROM app_settings")).all()
        migration.op = Operations(MigrationContext.configure(connection)); migration.upgrade()
        expected = {"google_business_connections", "google_business_oauth_states", "google_business_bindings", "google_business_grants", "google_business_actions"}
        assert set(inspect(connection).get_table_names()) == {"original_finance", "app_settings"} | expected
        for name in expected: assert connection.execute(text('SELECT COUNT(*) FROM "' + name + '"')).scalar() == 0
        assert connection.execute(text("SELECT * FROM original_finance")).all() == rows_before
        assert connection.execute(text("SELECT * FROM app_settings")).all() == settings_before
        assert connection.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE tbl_name IN ('original_finance','app_settings') AND name NOT LIKE 'sqlite_%' ORDER BY type,name")).all() == objects_before
    engine.dispose()


def test_uvicorn_google_oauth_callback_log_filter_redacts_query_in_actual_access_formatter():
    from routers.google_business import GoogleOAuthAccessLogFilter
    from uvicorn.logging import AccessFormatter
    raw = "/api/v1/google-business/oauth/callback?code=SYNTHETIC-OAUTH-SECRET&state=SYNTHETIC-STATE&error_description=SYNTHETIC-ERROR"
    record = logging.LogRecord("uvicorn.access", logging.INFO, "synthetic", 1, '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:1234", "GET", raw, "1.1", 303), None)
    assert GoogleOAuthAccessLogFilter().filter(record) is True
    formatted = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False).format(record)
    assert "/api/v1/google-business/oauth/callback" in formatted
    assert "SYNTHETIC-" not in formatted and "code=" not in formatted and "state=" not in formatted and "?" not in formatted
    assert record.args == ("127.0.0.1:1234", "GET", "/api/v1/google-business/oauth/callback", "1.1", 303)
    # The sanitized record is also safe if a secondary handler uses getMessage.
    assert "SYNTHETIC-" not in record.getMessage()


@pytest.mark.parametrize("path", ["/api/v1/google-business/status?debug=1", "/api/v1/google-business/oauth/callback-extra?code=unchanged", "/api/other/callback?code=unchanged", "/customers?q=merchant"])
def test_google_callback_log_filter_preserves_unrelated_uvicorn_request_logs(path):
    from routers.google_business import GoogleOAuthAccessLogFilter
    args = ("127.0.0.1:1234", "GET", path, "1.1", 200)
    record = logging.LogRecord("uvicorn.access", logging.INFO, "synthetic", 1, '%s - "%s %s HTTP/%s" %d', args, None)
    previous = record.getMessage()
    assert GoogleOAuthAccessLogFilter().filter(record) is True
    assert record.args == args and record.getMessage() == previous


@pytest.mark.parametrize("args", [(), ("one",), ("one", "two"), ("one", "two", 42), {"path": "/api/v1/google-business/oauth/callback"}])
def test_google_callback_log_filter_is_safe_for_other_logger_argument_shapes(args):
    from routers.google_business import GoogleOAuthAccessLogFilter
    record = logging.makeLogRecord({"name": "uvicorn.access", "msg": "synthetic", "args": args})
    assert GoogleOAuthAccessLogFilter().filter(record) is True
    assert record.args == args


def test_google_callback_filter_is_installed_only_on_uvicorn_access_logger():
    from routers.google_business import GoogleOAuthAccessLogFilter
    assert sum(isinstance(item, GoogleOAuthAccessLogFilter) for item in logging.getLogger("uvicorn.access").filters) == 1
    for logger in (logging.getLogger(), logging.getLogger("uvicorn.error"), logging.getLogger("httpx")):
        assert not any(isinstance(item, GoogleOAuthAccessLogFilter) for item in logger.filters)
