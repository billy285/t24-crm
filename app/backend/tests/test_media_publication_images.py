"""Private-image workflow against local SQLite and a deterministic fake Google."""
import hashlib
import json
import struct
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4
import zlib

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import func, select

from core.database import get_db
from dependencies.auth import get_current_user
from models.customer_access_grants import CustomerAccessGrant
from models.customer_materials import Customer_materials
from models.media_publication_images import MediaPublicationImage as Image, MediaPublicationImageSelection as Selection, MediaPublicationImageDelivery as Delivery, MediaPublicationImagePolicy as Policy
from services import media_publication_images as images
from test_google_business import OWNER, OPS, OTHER, PREFIX as GBP, gbp_env

PREFIX = "/api/v1/media-publication-images"
MEDIA = "/api/v1/media-operations"


def png(width=2, height=2, *, marker=b"\x20", metadata=False):
    raw = b"".join(b"\0" + marker * (width * 3) for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return images.PNG + images._chunk(b"IHDR", header) + (images._chunk(b"tEXt", b"private\x00EXIF SECRET") if metadata else b"") + images._chunk(b"IDAT", zlib.compress(raw)) + images._chunk(b"IEND", b"")


@pytest_asyncio.fixture
async def image_env(gbp_env, tmp_path, monkeypatch):
    env = gbp_env
    root = tmp_path / "materials"
    (root / "10").mkdir(parents=True)
    source = png(metadata=True)
    (root / "10" / "source.png").write_bytes(source)
    monkeypatch.setattr(images, "MATERIALS_ROOT", root)
    async with env.sessions() as db:
        material = await db.get(Customer_materials, 1001)
        material.file_path = "10/source.png"; material.file_url = None; material.source_type = "upload"
        grant = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.customer_id == 10, CustomerAccessGrant.employee_id == 2))
        grant.scopes = {"basic": "read_only", "delivery": "read_write", "materials": "read_write"}
        await db.commit()
    from routers.media_publication_images import router
    from routers.media_publication_images import _public_times
    _public_times.clear()
    app = FastAPI(); app.include_router(router)
    async def database():
        async with env.sessions() as db: yield db
    async def actor(): return env.user
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = actor
    env.source, env.root = source, root
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://crm.example.com") as client:
        env.images = client
        yield env


async def prepare(env, **changes):
    body = {"customer_id": "10", "material_id": "1001", "source_sha256": hashlib.sha256(env.source).hexdigest(),
        "rights_basis": "client_provided", "rights_confirmed": "true", "request_id": str(uuid4()), **changes}
    return await env.images.post(PREFIX + "/prepare", data=body, files={"file": ("prepared.png", png(metadata=True), "image/png")})


async def prepared(env):
    result = await prepare(env)
    assert result.status_code == 201, result.text
    row = result.json()
    assert row["status"] == "ready"
    return row


async def enable(env):
    old = env.user; env.user = OWNER
    response = await env.images.post(PREFIX + "/delivery-policy", json={"enabled": True, "public_delivery_confirmed": True})
    assert response.status_code == 200 and response.json()["enabled"], response.text
    env.user = old


async def reviewed_task(env, image):
    old = env.user; env.user = OWNER
    response = await env.client.post(MEDIA, json={"client_request_id": str(uuid4()), "customer_id": 10,
        "title": "Confirmed image post", "platform": "google_business", "due_at": "2026-12-01T18:00:00Z", "timezone": "America/Los_Angeles",
        "assignee_id": 2, "content": "Approved final image with confirmed business details.", "material_id": 1001, "image_version_id": image["id"]})
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["image_version_id"] == image["id"] and row["publication_image"]["image_sha256"] == image["image_sha256"]
    for action in ("submit", "approve"):
        response = await env.client.post(f"{MEDIA}/{row['id']}/transition", json={"expected_revision": row["revision"], "request_id": str(uuid4()), "action": action})
        assert response.status_code == 200, response.text
        row = response.json()
    env.user = old
    return row


@pytest.mark.asyncio
async def test_private_prepare_is_canonical_preview_and_replay_is_unique(image_env):
    env = image_env; env.user = OPS
    key = str(uuid4())
    response = await prepare(env, request_id=key)
    assert response.status_code == 201, response.text
    image = response.json()
    assert image["request_id"] == key and image["can_revoke"] is False
    assert not any(word in response.text for word in ("delivery_token", "source.png", "file_path", "/delivery/"))
    preview = await env.images.get(image["preview_path"])
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/png"
    assert preview.headers["cache-control"] == "private, no-store"
    assert b"EXIF SECRET" not in preview.content
    assert hashlib.sha256(preview.content).hexdigest() == image["image_sha256"]
    replay = await prepare(env, request_id=key)
    assert replay.status_code == 201 and replay.json()["id"] == image["id"]
    lookup = await env.images.get(PREFIX + "/requests/" + key)
    assert lookup.status_code == 200 and lookup.json()["id"] == image["id"]
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Image)) == 1
        assert await db.scalar(select(func.count()).select_from(Delivery)) == 0
        assert await db.scalar(select(func.count()).select_from(Policy)) == 0


@pytest.mark.asyncio
async def test_policy_off_keeps_preparation_and_approval_but_blocks_private_dispatch(image_env):
    env = image_env
    image = await prepared(env)
    row = await reviewed_task(env, image)
    response = await env.client.get(GBP + "/bindings/1/ready-tasks")
    assert response.status_code == 200, response.text
    ready = response.json()["items"][0]
    assert "尚未启用" in ready["publish_blocked_reason"]
    assert ready["preview_image_url"] is None and ready["preview_image_path"] == image["preview_path"]
    assert ready["image_sha256"] == image["image_sha256"] and "/delivery/" not in response.text
    response = await env.client.post(GBP + "/bindings/1/posts", json={"request_id": str(uuid4()), "task_id": row["id"], "expected_revision": row["revision"], "confirmed": True})
    assert response.status_code == 422 and not env.fake.writes
    async with env.sessions() as db:
        asset = await db.get(Image, image["id"])
        token = asset.delivery_token
        assert await db.scalar(select(func.count()).select_from(Delivery)) == 0
    public = await env.images.get(PREFIX + "/delivery/" + token + ".png")
    assert public.status_code == 404 and public.content == b""


@pytest.mark.asyncio
async def test_exact_image_approval_and_dispatch_lease_are_stable_and_not_duplicated(image_env):
    env = image_env
    image = await prepared(env); row = await reviewed_task(env, image)
    await enable(env)
    for _ in range(2):
        result = await env.client.get(GBP + "/bindings/1/ready-tasks")
        assert result.status_code == 200 and result.json()["items"][0]["publish_blocked_reason"] is None
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Delivery)) == 0
    env.fake.failure = "timeout_after"
    request = {"request_id": str(uuid4()), "task_id": row["id"], "expected_revision": row["revision"], "confirmed": True}
    response = await env.client.post(GBP + "/bindings/1/posts", json=request)
    assert response.status_code == 200 and response.json()["status"] == "unknown", response.text
    replay = await env.client.post(GBP + "/bindings/1/posts", json=request)
    assert replay.status_code == 200 and replay.json()["id"] == response.json()["id"]
    assert len(env.fake.writes) == 1
    source_url = env.fake.writes[0][2]["media"][0]["sourceUrl"]
    assert "/delivery/" in source_url
    public = await env.images.get(source_url)
    assert public.status_code == 200 and hashlib.sha256(public.content).hexdigest() == image["image_sha256"]
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Delivery)) == 1
        lease = await db.scalar(select(Delivery))
        assert lease.expires_at - lease.activated_at == timedelta(days=14)
    env.fake.failure = None
    reconciled = await env.client.post(GBP + f"/actions/{response.json()['id']}/reconcile", json={"confirmed": True})
    assert reconciled.status_code == 200 and len(env.fake.writes) == 1


@pytest.mark.asyncio
async def test_invitation_material_scope_and_policy_are_separate(image_env):
    env = image_env
    image = await prepared(env)
    env.user = OTHER
    listed = await env.images.get(PREFIX, params={"customer_id": 10, "material_id": 1001})
    assert listed.status_code == 200 and listed.json()["can_prepare"] is False
    assert (await prepare(env)).status_code == 403
    assert (await env.images.get(image["preview_path"])).status_code == 200
    assert (await env.images.post(PREFIX + "/delivery-policy", json={"enabled": True, "public_delivery_confirmed": True})).status_code == 403
    assert (await env.images.post(PREFIX + f"/{image['id']}/revoke")).status_code == 403
    assert (await env.images.get(PREFIX + "/requests/" + image["request_id"])).status_code == 404
    async with env.sessions() as db:
        grant = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.employee_id == 3, CustomerAccessGrant.customer_id == 10))
        grant.scopes = {"basic": "read_only", "delivery": "read_write", "materials": "none"}
        await db.commit()
    assert (await env.images.get(image["preview_path"])).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["source_bytes", "source_visibility", "revoked", "policy_off", "connection_off", "actor_inactive"])
async def test_delivery_rechecks_current_source_policy_and_grants(image_env, mutation):
    env = image_env
    image = await prepared(env); row = await reviewed_task(env, image); await enable(env)
    response = await env.client.post(GBP + "/bindings/1/posts", json={"request_id": str(uuid4()), "task_id": row["id"], "expected_revision": row["revision"], "confirmed": True})
    assert response.status_code == 200, response.text
    url = env.fake.writes[0][2]["media"][0]["sourceUrl"]
    assert (await env.images.get(url)).status_code == 200
    async with env.sessions() as db:
        if mutation == "source_bytes": (env.root / "10" / "source.png").write_bytes(png(marker=b"\x50"))
        elif mutation == "source_visibility": (await db.get(Customer_materials, 1001)).visibility = "owner"
        elif mutation == "revoked": (await db.get(Image, image["id"])).revoked_at = images.media.now()
        elif mutation == "policy_off": (await db.get(Policy, 1)).enabled = False
        elif mutation == "connection_off": (await db.get(env.Connection, 1)).active = False
        else:
            from models.employees import Employees
            (await db.get(Employees, 1)).status = "disabled"
        await db.commit()
    denied = await env.images.get(url)
    assert denied.status_code == 404 and denied.content == b""


@pytest.mark.asyncio
async def test_task_image_change_requires_owner_reapproval_and_crosscustomer_is_blocked(image_env):
    env = image_env
    image = await prepared(env)
    env.user = OWNER
    request = {"client_request_id": str(uuid4()), "customer_id": 20, "title": "Cross customer", "platform": "google_business",
        "due_at": "2026-12-01T18:00:00Z", "timezone": "America/Los_Angeles", "content": "Confirmed", "material_id": 1001, "image_version_id": image["id"]}
    assert (await env.client.post(MEDIA, json=request)).status_code == 422
    row = await reviewed_task(env, image); await enable(env)
    async with env.sessions() as db:
        from models.media_operations import MediaOperationEvent
        approval = await db.scalar(select(MediaOperationEvent).where(MediaOperationEvent.task_id == row["id"], MediaOperationEvent.action == "approve"))
        snapshot = dict(approval.snapshot); snapshot["publication_image"] = {**snapshot["publication_image"], "image_sha256": "0" * 64}; approval.snapshot = snapshot
        await db.commit()
    response = await env.client.post(GBP + "/bindings/1/posts", json={"request_id": str(uuid4()), "task_id": row["id"], "expected_revision": row["revision"], "confirmed": True})
    assert response.status_code == 422 and not env.fake.writes
