"""Independent PNG and immutable-file attacks; local synthetic bytes only."""
import hashlib
import os
from pathlib import Path
import struct
from types import SimpleNamespace
import zlib
import asyncio
import importlib.util
import threading
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from fastapi import HTTPException
import pytest

from services import media_publication_images as images
from sqlalchemy import select, text, func
from sqlalchemy import create_engine, inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations
from models.customer_access_grants import CustomerAccessGrant
from models.customer_materials import Customer_materials
from models.employees import Employees
from models.media_publication_images import MediaPublicationImage as Image, MediaPublicationImageDelivery as Delivery, MediaPublicationImagePolicy as Policy
from models.media_publication_images import MediaPublicationImageSelection as Selection
from models.google_business import GoogleBusinessSchedule as Schedule
from test_google_business import OWNER, OPS, OTHER, actors, gbp_env
from test_media_publication_images import image_env, prepared, prepare, reviewed_task, enable, PREFIX, GBP


def chunk(kind, value):
    return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xffffffff)


def header(width=2, height=2, depth=8, color=6, compression=0, filtering=0, interlace=0):
    return struct.pack(">IIBBBBB", width, height, depth, color, compression, filtering, interlace)


def pixels(width=2, height=2, color=6, filters=None):
    channels = 4 if color == 6 else 3
    return b"".join(bytes([(filters or [0] * height)[row]]) + bytes((row + column) % 256 for column in range(width * channels)) for row in range(height))


def png(*, width=2, height=2, color=6, raw=None, ancillary=(), compressed=None, level=6, **fields):
    data = zlib.compress(pixels(width, height, color) if raw is None else raw, level) if compressed is None else compressed
    return images.PNG + chunk(b"IHDR", header(width, height, color=color, **fields)) + b"".join(chunk(k, v) for k, v in ancillary) + chunk(b"IDAT", data) + chunk(b"IEND", b"")


def chunks(body):
    assert body.startswith(images.PNG)
    result = []; position = 8
    while position < len(body):
        size = struct.unpack(">I", body[position:position + 4])[0]
        name = body[position + 4:position + 8]; value = body[position + 8:position + 8 + size]
        assert zlib.crc32(name + value) & 0xffffffff == struct.unpack(">I", body[position + 8 + size:position + 12 + size])[0]
        result.append((name, value)); position += 12 + size
    assert position == len(body)
    return result


@pytest.mark.parametrize("color", [2, 6])
def test_server_canonical_png_strips_metadata_and_reencodes_equivalent_pixels(color):
    raw = pixels(color=color)
    private = ((b"eXIf", b"PRIVATE-GPS-DEVICE-CANARY"), (b"iTXt", b"PRIVATE-NOTES-CANARY"),
        (b"zTXt", b"notes\0\0" + zlib.compress(b"PRIVATE-COMPRESSED-CANARY")))
    first, width, height = images.canonical_png(png(color=color, ancillary=private, level=0))
    second, _, _ = images.canonical_png(png(color=color, level=9))
    assert (width, height) == (2, 2) and first == second
    values = chunks(first)
    assert [name for name, _ in values] == [b"IHDR", b"IDAT", b"IEND"]
    assert zlib.decompress(values[1][1]) == raw
    assert b"PRIVATE-" not in first


@pytest.mark.parametrize("filter_byte", range(5))
def test_valid_png_row_filter_numbers_are_accepted(filter_byte):
    raw = pixels(filters=[filter_byte, filter_byte])
    result, _, _ = images.canonical_png(png(raw=raw))
    assert zlib.decompress(chunks(result)[1][1]) == raw


@pytest.mark.parametrize("fields", [{"width": 0}, {"height": 0}, {"width": 2049}, {"height": 2049},
    {"width": 2**31}, {"depth": 16}, {"color": 0}, {"color": 3}, {"color": 4},
    {"interlace": 1}, {"compression": 1}, {"filtering": 1}])
def test_unsupported_or_unbounded_ihdr_is_rejected_before_decode(fields):
    body = images.PNG + chunk(b"IHDR", header(**fields)) + chunk(b"IDAT", zlib.compress(b"\0")) + chunk(b"IEND", b"")
    with pytest.raises(HTTPException) as error: images.canonical_png(body)
    assert error.value.status_code == 422


def adversarial_pngs():
    valid = png(); h = chunk(b"IHDR", header()); data = chunk(b"IDAT", zlib.compress(pixels())); end = chunk(b"IEND", b"")
    yield valid[1:]
    yield valid[:-1]
    yield valid + b"<script>PRIVATE-CANARY</script>"
    yield images.PNG + h + h + data + end
    yield images.PNG + data + h + end
    yield images.PNG + h + end + data
    yield images.PNG + h + chunk(b"ABCD", b"unknown critical") + data + end
    yield images.PNG + chunk(b"IHDR", header()[:-1]) + data + end
    broken = bytearray(valid); broken[-1] ^= 1; yield bytes(broken)
    compressed = zlib.compress(pixels()); mid = len(compressed) // 2
    yield images.PNG + h + chunk(b"IDAT", compressed[:mid]) + chunk(b"tEXt", b"breaks IDAT contiguity") + chunk(b"IDAT", compressed[mid:]) + end
    for name in (b"acTL", b"fcTL", b"fdAT"):
        yield images.PNG + h + chunk(name, b"ANIMATION") + data + end
    yield images.PNG + h + b"\xff\xff\xff\xffIDAT" + b"x" * 20 + end
    yield images.PNG + h + chunk(b"ID\0T", b"not a PNG name") + end


@pytest.mark.parametrize("body", list(adversarial_pngs()))
def test_chunk_crc_order_animation_and_trailing_polyglots_fail_closed(body):
    with pytest.raises(HTTPException) as error: images.canonical_png(body)
    assert error.value.status_code == 422


@pytest.mark.parametrize("compressed", [
    zlib.compress(pixels())[:-1], zlib.compress(pixels()) + b"PRIVATE-TRAILING-CANARY",
    zlib.compress(pixels()) + zlib.compress(pixels()),
    zlib.compress(pixels()[:-1]), zlib.compress(pixels() + b"\0"),
    zlib.compress(b"\0" * 1_000_000), b"not zlib", b"",
])
def test_zlib_exact_length_single_stream_eof_and_bomb_bounds(compressed):
    with pytest.raises(HTTPException) as error: images.canonical_png(png(compressed=compressed))
    assert error.value.status_code == 422


def test_invalid_scanline_filter_and_excess_chunk_count_rejected():
    bad = bytes([5]) + pixels()[1:]
    for body in (png(raw=bad), png(ancillary=[(b"tEXt", b"")] * 513), b"x" * (images.MAX_PNG_BYTES + 1)):
        with pytest.raises(HTTPException) as error: images.canonical_png(body)
        assert error.value.status_code == 422


def test_contiguous_idat_rechunking_has_same_canonical_identity():
    data = zlib.compress(pixels()); split = len(data) // 2
    body = images.PNG + chunk(b"IHDR", header()) + chunk(b"IDAT", data[:split]) + chunk(b"IDAT", data[split:]) + chunk(b"IEND", b"")
    assert images.canonical_png(body)[0] == images.canonical_png(png())[0]


@pytest.fixture
def private_source(tmp_path, monkeypatch):
    root = tmp_path / "materials"; customer = root / "10"; customer.mkdir(parents=True)
    path = customer / "original.png"; path.write_bytes(b"PRIVATE-ORIGINAL-BYTES-NOT-PUBLIC")
    monkeypatch.setattr(images, "MATERIALS_ROOT", root)
    material = SimpleNamespace(customer_id=10, file_path="10/original.png")
    return SimpleNamespace(root=root, customer=customer, path=path, material=material)


@pytest.mark.parametrize("path", ["20/original.png", "10/../original.png", "../10/original.png", "/10/original.png", "10//original.png", "10/sub/original.png", "10/..", "10/.", "10/original.png\0", "10\\original.png"])
def test_original_file_paths_cannot_escape_or_cross_customers(private_source, path):
    source = private_source; source.material.file_path = path
    with pytest.raises(HTTPException): images._source_bytes(source.material)


@pytest.mark.parametrize("kind", ["root_symlink", "customer_symlink", "file_symlink", "hardlink", "fifo", "directory", "oversize"])
def test_original_reader_denies_links_special_files_and_oversize(private_source, tmp_path, monkeypatch, kind):
    source = private_source
    if kind == "root_symlink":
        link = tmp_path / "linked-root"; link.symlink_to(source.root, target_is_directory=True); monkeypatch.setattr(images, "MATERIALS_ROOT", link)
    elif kind == "customer_symlink":
        source.customer.rename(source.root / "private-other"); source.customer.symlink_to(source.root / "private-other", target_is_directory=True)
    elif kind == "file_symlink":
        target = source.customer / "private-other.png"; source.path.rename(target); source.path.symlink_to(target)
    elif kind == "hardlink": os.link(source.path, source.customer / "alias.png")
    elif kind == "fifo": source.path.unlink(); os.mkfifo(source.path)
    elif kind == "directory": source.path.unlink(); source.path.mkdir()
    else:
        with source.path.open("wb") as stream: stream.truncate(images.MAX_SOURCE_BYTES + 1)
    with pytest.raises(HTTPException) as error: images._source_bytes(source.material)
    assert "PRIVATE-" not in str(error.value.detail)


def test_original_in_place_change_during_read_is_not_accepted(private_source, monkeypatch):
    source = private_source; original = images.os.fdopen
    class ChangedReader:
        def __init__(self, inner): self.inner = inner
        def __enter__(self): self.inner.__enter__(); return self
        def __exit__(self, *args): return self.inner.__exit__(*args)
        def read(self, *args):
            result = self.inner.read(*args)
            source.path.write_bytes(b"X" * len(result))
            return result
    monkeypatch.setattr(images.os, "fdopen", lambda *args, **kwargs: ChangedReader(original(*args, **kwargs)))
    with pytest.raises(HTTPException): images._source_bytes(source.material)


def test_immutable_private_version_denies_byte_or_metadata_substitution(private_source):
    body = images.canonical_png(png())[0]; key = "a" * 32
    images._write_image(key, body)
    row = SimpleNamespace(file_key=key, byte_size=len(body), image_sha256=hashlib.sha256(body).hexdigest())
    assert images._image_bytes(row) == body
    with pytest.raises(HTTPException): images._write_image(key, body)
    stored = private_source.root / ".publication-images" / (key + ".png")
    stored.write_bytes(body[:-1] + bytes([body[-1] ^ 1]))
    with pytest.raises(HTTPException): images._image_bytes(row)


@pytest.mark.parametrize("field,value", [("file_key", "../PRIVATE"), ("byte_size", 1), ("image_sha256", "0" * 64)])
def test_immutable_reader_does_not_trust_record_identifiers_or_hashes(private_source, field, value):
    body = images.canonical_png(png())[0]; key = "b" * 32; images._write_image(key, body)
    row = SimpleNamespace(file_key=key, byte_size=len(body), image_sha256=hashlib.sha256(body).hexdigest()); setattr(row, field, value)
    with pytest.raises(HTTPException): images._image_bytes(row)


def test_invalid_png_reserved_type_bit_is_not_silently_stripped():
    with pytest.raises(HTTPException): images.canonical_png(png(ancillary=[(b"abca", b"invalid reserved lowercase bit")]))


async def dispatch(env, image):
    row = await reviewed_task(env, image); await enable(env)
    response = await env.client.post(GBP + "/bindings/1/posts", json={"request_id": str(uuid4()), "task_id": row["id"], "expected_revision": row["revision"], "confirmed": True})
    assert response.status_code == 200, response.text
    return row, response.json(), env.fake.writes[-1][2]["media"][0]["sourceUrl"]


async def snapshot(env):
    async with env.sessions() as db:
        return {name: [tuple(row) for row in (await db.execute(text('SELECT * FROM "' + name + '" ORDER BY 1'))).all()]
            for name in ("financial_canary", "customers", "employees", "customer_access_grants", "app_settings")}


@pytest.mark.asyncio
async def test_independent_prepare_http_replay_hash_conflict_and_protected_rows(image_env):
    env = image_env; env.user = OPS
    before = await snapshot(env); key = str(uuid4())
    first = await prepare(env, request_id=key)
    assert first.status_code == 201, first.text
    conflict = await prepare(env, request_id=key, rights_basis="licensed")
    assert conflict.status_code == 409
    replay = await prepare(env, request_id=key)
    assert replay.status_code == 201 and replay.json()["id"] == first.json()["id"]
    assert await snapshot(env) == before
    assert not any(value in first.text for value in ("delivery_token", "file_path", "source.png", "SYNTHETIC-ACCESS", "financial_canary"))
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Image)) == 1
        assert await db.scalar(select(func.count()).select_from(Delivery)) == 0


@pytest.mark.asyncio
async def test_concurrent_same_uuid_has_one_image_and_never_mints_a_lease(image_env):
    env = image_env; key = str(uuid4())
    replies = await asyncio.gather(prepare(env, request_id=key), prepare(env, request_id=key))
    assert all(row.status_code in (201, 409) for row in replies)
    successful = [row.json() for row in replies if row.status_code == 201]
    assert successful and len({row["id"] for row in successful}) == 1
    lookup = await env.images.get(PREFIX + "/requests/" + key)
    assert lookup.status_code == 200 and lookup.json()["id"] == successful[0]["id"]
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Image)) == 1
        assert await db.scalar(select(func.count()).select_from(Delivery)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["finance", "sales", "design", "sales_partner"])
async def test_unrelated_roles_cannot_read_prepare_policy_or_lookup_private_images(image_env, role):
    env = image_env; image = await prepared(env)
    env.user = next(user for user in actors() if user.role == role)
    replies = [await env.images.get(PREFIX, params={"customer_id": 10, "material_id": 1001}),
        await prepare(env), await env.images.get(image["preview_path"]),
        await env.images.get(PREFIX + "/requests/" + image["request_id"]),
        await env.images.get(PREFIX + "/delivery-policy", params={"customer_id": 10})]
    assert all(row.status_code == 403 for row in replies)
    assert not any("delivery_token" in row.text or image["image_sha256"] in row.text for row in replies)


@pytest.mark.asyncio
async def test_same_customer_invitation_does_not_grant_another_customer_or_owner_only_material(image_env):
    env = image_env; env.user = OPS
    assert (await env.images.get(PREFIX, params={"customer_id": 20, "material_id": 1001})).status_code == 404
    assert (await prepare(env, customer_id="20")).status_code == 404
    private = await prepare(env, material_id="1002")
    assert private.status_code in (403, 404, 422) and "SECRET-PRIVATE" not in private.text
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Image)) == 0


@pytest.mark.asyncio
async def test_get_head_share_lease_expiry_uniform_denial_and_never_read_original(image_env, monkeypatch):
    env = image_env; image = await prepared(env)
    row, action, url = await dispatch(env, image)
    def never_source(*args, **kwargs): raise AssertionError("PUBLIC_HTTP_MUST_NOT_READ_PRIVATE_ORIGINAL")
    monkeypatch.setattr(images, "_source_bytes", never_source)
    first = await env.images.get(url); head = await env.images.head(url)
    assert first.status_code == head.status_code == 200 and head.content == b""
    assert head.headers["content-length"] == str(len(first.content)) == str(image["byte_size"])
    for value in (first, head):
        assert value.headers["cache-control"] == "private, no-store"
        assert value.headers["x-content-type-options"] == "nosniff" and value.headers["referrer-policy"] == "no-referrer"
    async with env.sessions() as db:
        lease = await db.get(Delivery, action["id"])
        lease.expires_at = images.media.now() - timedelta(seconds=1); await db.commit()
    for path in (url, PREFIX + "/delivery/" + "X" * 43 + ".png", PREFIX + "/delivery/invalid.png"):
        denied = await env.images.get(path)
        assert denied.status_code == 404 and denied.content == b"" and "no-store" in denied.headers["cache-control"]


@pytest.mark.asyncio
async def test_owner_policy_disable_and_reenable_never_revives_an_old_delivery(image_env):
    env = image_env; image = await prepared(env)
    _, _, url = await dispatch(env, image)
    assert (await env.images.get(url)).status_code == 200
    off = await env.images.post(PREFIX + "/delivery-policy", json={"enabled": False, "public_delivery_confirmed": True})
    assert off.status_code == 200 and (await env.images.get(url)).status_code == 404
    await enable(env)
    assert (await env.images.get(url)).status_code == 404
    assert len(env.fake.writes) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["_source_bytes", "canonical_png", "_write_image"])
async def test_slow_prepare_io_does_not_lock_unrelated_finance_writer(image_env, monkeypatch, phase):
    env = image_env; started = threading.Event(); release = threading.Event(); original = getattr(images, phase)
    def slow(*args, **kwargs):
        started.set()
        if not release.wait(4): raise AssertionError("SYNTHETIC_THREAD_NOT_RELEASED")
        return original(*args, **kwargs)
    monkeypatch.setattr(images, phase, slow)
    pending = asyncio.create_task(prepare(env))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        async def write_finance():
            async with env.sessions() as db:
                await db.execute(text("UPDATE financial_canary SET amount='200.00' WHERE id=1")); await db.commit()
        await asyncio.wait_for(write_finance(), .8)
    finally:
        release.set()
        response = await pending
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_revocation_after_full_source_read_blocks_prepare_commit(image_env, monkeypatch):
    env = image_env; env.user = OPS; started = threading.Event(); release = threading.Event(); original = images._source_bytes
    def slow(material):
        result = original(material); started.set()
        if not release.wait(4): raise AssertionError("SYNTHETIC_THREAD_NOT_RELEASED")
        return result
    monkeypatch.setattr(images, "_source_bytes", slow)
    pending = asyncio.create_task(prepare(env))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        async with env.sessions() as db:
            grant = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.customer_id == 10, CustomerAccessGrant.employee_id == 2))
            grant.scopes = {"basic": "read_only", "delivery": "read_only", "materials": "read_only"}; await db.commit()
    finally:
        release.set(); response = await pending
    assert response.status_code in (403, 404)
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Image)) == 0
        assert await db.scalar(select(func.count()).select_from(Delivery)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["private_preview", "public_delivery"])
async def test_slow_read_rechecks_current_revocation_before_exposing_image_bytes(image_env, monkeypatch, mode):
    env = image_env; image = await prepared(env)
    if mode == "public_delivery": _, _, path = await dispatch(env, image)
    else: env.user = OPS; path = image["preview_path"]
    started = threading.Event(); release = threading.Event(); original = images._image_bytes
    def slow(row):
        result = original(row); started.set()
        if not release.wait(4): raise AssertionError("SYNTHETIC_THREAD_NOT_RELEASED")
        return result
    monkeypatch.setattr(images, "_image_bytes", slow)
    pending = asyncio.create_task(env.images.get(path))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        async with env.sessions() as db:
            if mode == "public_delivery": (await db.get(Policy, 1)).enabled = False
            else:
                grant = await db.scalar(select(CustomerAccessGrant).where(CustomerAccessGrant.customer_id == 10, CustomerAccessGrant.employee_id == 2))
                grant.scopes = {"basic": "read_only", "delivery": "read_only", "materials": "none"}
            await db.execute(text("UPDATE financial_canary SET amount='250.00' WHERE id=1")); await db.commit()
    finally:
        release.set(); response = await pending
    assert response.status_code in (403, 404) and response.content != png()
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["selection_deleted", "different_version_same_pixels", "rights", "image_hash", "source_bytes_mtime_restored"])
async def test_exact_approved_image_cannot_be_replaced_without_owner_reapproval(image_env, mutation):
    env = image_env; image = await prepared(env); task = await reviewed_task(env, image); await enable(env)
    another = await prepared(env) if mutation == "different_version_same_pixels" else None
    async with env.sessions() as db:
        if mutation == "selection_deleted": await db.delete(await db.get(Selection, task["id"]))
        elif mutation == "different_version_same_pixels":
            assert image["image_sha256"] == another["image_sha256"]
            (await db.get(Selection, task["id"])).image_id = another["id"]
        elif mutation == "rights": (await db.get(Image, image["id"])).rights_basis = "licensed"
        elif mutation == "image_hash": (await db.get(Image, image["id"])).image_sha256 = "a" * 64
        else:
            path = env.root / "10" / "source.png"; old = path.stat(); body = path.read_bytes()
            path.write_bytes(body[:-1] + bytes([body[-1] ^ 1])); os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
        await db.commit()
    response = await env.client.post(GBP + "/bindings/1/posts", json={"request_id": str(uuid4()), "task_id": task["id"], "expected_revision": task["revision"], "confirmed": True})
    assert response.status_code in (409, 422) and not env.fake.writes
    async with env.sessions() as db: assert await db.scalar(select(func.count()).select_from(Delivery)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["none", "selection_deleted", "image_revoked", "policy_disabled"])
async def test_scheduler_uses_frozen_image_and_unknown_dispatch_never_retries(image_env, monkeypatch, mutation):
    from services import google_business as google, google_business_scheduler as worker
    env = image_env; clock = [datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)]
    monkeypatch.setattr(google, "now", lambda: clock[0]); monkeypatch.setattr(images.media, "now", lambda: clock[0])
    cutoff = "2026-10-30T19:42:04Z"
    monkeypatch.setenv("T24_GBP_SCHEDULER_ENABLED", "true"); monkeypatch.setenv("T24_GBP_SCHEDULER_ACTIVATION_FROM", cutoff)
    async with env.sessions() as db:
        (await db.get(env.Binding, 1)).primary_operator_id = 2; await db.commit()
    image = await prepared(env); task = await reviewed_task(env, image); await enable(env)
    response = await env.client.post(GBP + "/bindings/1/schedules", json={"request_id": str(uuid4()), "task_id": task["id"], "expected_revision": task["revision"], "planned_at": (clock[0] + timedelta(minutes=2)).isoformat(), "timezone": "America/Los_Angeles", "confirmed": True})
    assert response.status_code in (200, 201), response.text
    schedule = response.json()
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Delivery)) == 0
        if mutation == "selection_deleted": await db.delete(await db.get(Selection, task["id"]))
        elif mutation == "image_revoked": (await db.get(Image, image["id"])).revoked_at = clock[0]
        elif mutation == "policy_disabled": (await db.get(Policy, 1)).enabled = False
        await db.commit()
    clock[0] += timedelta(minutes=3); env.fake.failure = "timeout_after"
    await worker.run_tick(sessions=env.sessions, clock=lambda: clock[0])
    await worker.run_tick(sessions=env.sessions, clock=lambda: clock[0] + timedelta(seconds=30))
    async with env.sessions() as db:
        state = await db.get(Schedule, schedule["id"])
        leases = await db.scalar(select(func.count()).select_from(Delivery))
        if mutation == "none":
            assert state.status == "unknown" and leases == 1 and len(env.fake.writes) == 1
            assert env.fake.writes[0][2]["media"][0]["sourceUrl"].endswith(".png")
        else:
            assert state.status == "blocked" and leases == 0 and not env.fake.writes
    assert worker.enabled() and os.environ["T24_GBP_SCHEDULER_ACTIVATION_FROM"] == cutoff


@pytest.mark.asyncio
async def test_public_burst_limit_bounds_valid_or_invalid_token_read_cost(image_env):
    env = image_env
    paths = [PREFIX + "/delivery/" + "X" * 43 + ".png"] * 9
    replies = [await env.images.get(path) for path in paths]
    assert [response.status_code for response in replies[:8]] == [404] * 8
    assert replies[-1].status_code == 429 and replies[-1].headers["retry-after"] == "2"


def test_access_log_redaction_is_image_route_only():
    import logging
    from routers.media_publication_images import ImageAccessLogFilter
    image = logging.LogRecord("uvicorn.access", 20, "test", 1, "%s %s %s %s %s", ("client", "GET", PREFIX + "/delivery/" + "secret" * 8 + ".png?x=1", "1.1", 200), None)
    unrelated = logging.LogRecord("uvicorn.access", 20, "test", 1, "%s %s %s %s %s", ("client", "GET", "/api/v1/customers?customer_id=10", "1.1", 200), None)
    original = unrelated.args
    assert ImageAccessLogFilter().filter(image) and "secret" not in image.getMessage()
    assert ImageAccessLogFilter().filter(unrelated) and unrelated.args == original


@pytest.mark.asyncio
async def test_cancelled_prepare_retains_processing_slot_until_background_decode_finishes(image_env, monkeypatch):
    env = image_env; entered = threading.Event(); third = threading.Event(); release = threading.Event(); lock = threading.Lock()
    original = images.canonical_png; count = [0]
    def slow(body):
        with lock:
            count[0] += 1
            if count[0] >= 2: entered.set()
            if count[0] >= 3: third.set()
        if not release.wait(4): raise AssertionError("SYNTHETIC_THREAD_NOT_RELEASED")
        return original(body)
    monkeypatch.setattr(images, "canonical_png", slow)
    requests = [asyncio.create_task(prepare(env)) for _ in range(2)]
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        for request in requests: request.cancel()
        requests.append(asyncio.create_task(prepare(env)))
        assert not await asyncio.to_thread(third.wait, .25), "Cancelled decoders must not release their CPU/memory slots before ending"
    finally:
        release.set(); await asyncio.gather(*requests, return_exceptions=True)


def test_both_real_additive_migrations_preserve_finance_acl_google_rows_and_sequence(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "image-planning-migration.db"))
    preserved = {"original_finance", "customer_access_grants", "private_canary", "media_operation_tasks", "google_business_actions", "alembic_version"}
    expected = {"media_publication_image_policies", "media_publication_images", "media_publication_image_selections", "media_publication_image_deliveries", "media_content_plans", "media_content_plan_tasks"}
    with engine.begin() as db:
        db.exec_driver_sql("PRAGMA foreign_keys=ON")
        db.exec_driver_sql("PRAGMA user_version=42"); db.exec_driver_sql("PRAGMA application_id=20261031")
        db.exec_driver_sql("CREATE TABLE original_finance(id INTEGER PRIMARY KEY AUTOINCREMENT,amount TEXT,closing_state TEXT,commission_owner TEXT)")
        db.exec_driver_sql("INSERT INTO original_finance VALUES(1,'199.00','closed','owner')")
        db.exec_driver_sql("INSERT INTO original_finance VALUES(901,'0','retained-sequence','owner')"); db.exec_driver_sql("DELETE FROM original_finance WHERE id=901")
        db.exec_driver_sql("CREATE TABLE customer_access_grants(id INTEGER PRIMARY KEY,scopes TEXT,finance_access TEXT)")
        db.exec_driver_sql("INSERT INTO customer_access_grants VALUES(1,'{\"delivery\":\"read_only\"}','none')")
        db.exec_driver_sql("CREATE TABLE private_canary(id INTEGER PRIMARY KEY,body TEXT)")
        db.exec_driver_sql("INSERT INTO private_canary VALUES(1,'PRIVATE-UNCHANGED-CANARY')")
        db.exec_driver_sql("CREATE TABLE media_operation_tasks(id INTEGER PRIMARY KEY,content TEXT,status TEXT)")
        db.exec_driver_sql("INSERT INTO media_operation_tasks VALUES(1,'Old reviewed text','ready')")
        db.exec_driver_sql("CREATE TABLE google_business_actions(id INTEGER PRIMARY KEY,task_id INTEGER,payload TEXT,status TEXT)")
        db.exec_driver_sql("INSERT INTO google_business_actions VALUES(1,1,'{\"summary\":\"Old payload\"}','unknown')")
        db.exec_driver_sql("CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY)")
        db.exec_driver_sql("INSERT INTO alembic_version VALUES('eaf5a7b8c914')")
        rows_before = {name: db.exec_driver_sql('SELECT * FROM "' + name + '" ORDER BY 1').all() for name in preserved}
        schema_sql = "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE tbl_name IN ('original_finance','customer_access_grants','private_canary','media_operation_tasks','google_business_actions','alembic_version') ORDER BY type,name"
        schema_before = db.exec_driver_sql(schema_sql).all()
        sequence_before = db.exec_driver_sql("SELECT * FROM sqlite_sequence ORDER BY name").all()
        pragma_before = [db.exec_driver_sql("PRAGMA " + name).scalar() for name in ("user_version", "application_id")]
        previous = "eaf5a7b8c914"
        for filename in ("fbc6b8c9d025_media_publication_images.py", "acd7c9d0e136_media_content_plans.py"):
            path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / filename
            spec = importlib.util.spec_from_file_location("synthetic_" + filename[:-3], path); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            assert module.down_revision == previous; previous = module.revision
            module.op = Operations(MigrationContext.configure(db)); module.upgrade()
        assert previous == "acd7c9d0e136"
        assert set(inspect(db).get_table_names()) == preserved | expected
        for name in preserved: assert db.exec_driver_sql('SELECT * FROM "' + name + '" ORDER BY 1').all() == rows_before[name]
        assert db.exec_driver_sql(schema_sql).all() == schema_before
        assert db.exec_driver_sql("SELECT * FROM sqlite_sequence ORDER BY name").all() == sequence_before
        assert [db.exec_driver_sql("PRAGMA " + name).scalar() for name in ("user_version", "application_id")] == pragma_before
        assert all(db.exec_driver_sql('SELECT COUNT(*) FROM "' + name + '"').scalar() == 0 for name in expected)
        assert db.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        for table in ("media_publication_image_selections", "media_publication_image_deliveries", "media_content_plan_tasks"):
            assert all(row[6] == "RESTRICT" for row in db.exec_driver_sql('PRAGMA foreign_key_list("' + table + '")').all())
    engine.dispose()
