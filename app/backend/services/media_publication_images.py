"""Private, immutable PNG publication versions with dispatch-only delivery.

The browser prepares pixels; that is not proof they match the source. The
source hash and the final PNG hash are separate facts shown for owner review.
No URL is fetched, no original upload is published and preparation grants no
anonymous access. The owner delivery policy is absent/OFF until explicit opt-in.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat
import struct
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4
import zlib
import weakref

from fastapi import HTTPException
from sqlalchemy import select

from models.employees import Employees
from models.customer_materials import Customer_materials
from models.media_publication_images import MediaPublicationImage as Image, MediaPublicationImageSelection as Selection, MediaPublicationImageDelivery as Delivery, MediaPublicationImagePolicy as Policy
from services import media_operations as media
from services.role_permissions import normalized_role
from services.schema_readiness import require_tables, tables_available

TABLES = {"media_publication_images", "media_publication_image_selections", "media_publication_image_deliveries", "media_publication_image_policies"}
MATERIALS_ROOT = Path(__file__).resolve().parent.parent / "data" / "materials"
MAX_SOURCE_BYTES = 30 * 1024 * 1024
MAX_PNG_BYTES = 8 * 1024 * 1024
MAX_DIMENSION = 2048
PNG = b"\x89PNG\r\n\x1a\n"
IDENTITY = re.compile(r"[a-f0-9]{32}")
SHA = re.compile(r"[a-f0-9]{64}")
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
NOTICE = "仅在已审核帖子提交时开放发布副本，每次提交的免登录投递期为14天；同一版本再次提交会延长可读取期。持有地址者在有效期内也能读取，原始私有文件不会公开。"
_prepare_slots = weakref.WeakKeyDictionary()
_processing_work = set()
_SCHEMA_KEY = "media_publication_image_tables_available"


async def _available(db):
    if _SCHEMA_KEY not in db.info: db.info[_SCHEMA_KEY] = await tables_available(db, TABLES)
    return db.info[_SCHEMA_KEY]


def _processing_slot():
    loop = asyncio.get_running_loop()
    slot = _prepare_slots.get(loop)
    if slot is None:
        slot = asyncio.Semaphore(2); _prepare_slots[loop] = slot
    return slot


def _prepare_pixels(material, body, source_sha256):
    source, signature = _source_bytes(material)
    if hashlib.sha256(source).hexdigest() != source_sha256:
        raise HTTPException(409, "原文件已变化，请重新读取文件后准备图片")
    del source
    canonical, width, height = canonical_png(body)
    return signature, canonical, width, height


async def _bounded_processing(material, body, source_sha256):
    # Cancellation of the HTTP waiter cannot stop a Python worker thread. Keep
    # its exact slot and a strong task reference until the worker really ends.
    slot = _processing_slot()
    await slot.acquire()
    try:
        frozen = SimpleNamespace(customer_id=material.customer_id, file_path=material.file_path)
        work = asyncio.create_task(asyncio.to_thread(_prepare_pixels, frozen, body, source_sha256))
    except BaseException:
        slot.release(); raise
    _processing_work.add(work)
    def complete(task):
        _processing_work.discard(task)
        try: task.exception()
        except asyncio.CancelledError: pass
        slot.release()
    work.add_done_callback(complete)
    return await asyncio.shield(work)


def _fail(message="图片资料无效，请重新准备发布图片"):
    raise HTTPException(422, message)


def _chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)


def canonical_png(body):
    """Bounded PNG8 RGB/RGBA parser and fresh metadata-free server encoder."""
    if not isinstance(body, bytes) or not 45 <= len(body) <= MAX_PNG_BYTES or not body.startswith(PNG):
        _fail("仅接受不超过8MB的静态 PNG 发布副本")
    position, count, header, parts, phase = 8, 0, None, [], "header"
    while position < len(body):
        count += 1
        if count > 512 or position + 12 > len(body): _fail()
        length = struct.unpack(">I", body[position:position + 4])[0]
        kind = body[position + 4:position + 8]
        if not re.fullmatch(rb"[A-Za-z]{4}", kind) or kind[2] & 32 or length > MAX_PNG_BYTES or position + 12 + length > len(body): _fail()
        value = body[position + 8:position + 8 + length]
        check = struct.unpack(">I", body[position + 8 + length:position + 12 + length])[0]
        if check != zlib.crc32(kind + value) & 0xffffffff: _fail("PNG 校验失败，请重新准备图片")
        position += 12 + length
        if kind in {b"acTL", b"fcTL", b"fdAT"}: _fail("动态 PNG 不能作为此发布副本")
        if kind == b"IHDR":
            if phase != "header" or header is not None or count != 1 or length != 13: _fail()
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", value)
            if not (1 <= width <= MAX_DIMENSION and 1 <= height <= MAX_DIMENSION and depth == 8 and color in {2, 6} and compression == filtering == interlace == 0):
                _fail("发布副本需为最长边2048以内的8位 RGB/RGBA静态 PNG")
            header, phase = value, "before_data"
        elif kind == b"IDAT":
            if header is None or phase not in {"before_data", "data"}: _fail()
            parts.append(value); phase = "data"
        elif kind == b"IEND":
            if phase not in {"data", "after_data"} or not parts or length or position != len(body): _fail()
            phase = "end"; break
        else:
            if header is None or kind[0] & 32 == 0: _fail("不支持该 PNG 数据结构")
            if phase == "data": phase = "after_data"
            # Ignore all ancillary metadata after verifying its bounded CRC.
    if phase != "end" or header is None: _fail()
    channels = 3 if color == 2 else 4
    stride = width * channels + 1
    expected = height * stride
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(b"".join(parts), expected + 1)
    except zlib.error:
        _fail("PNG 像素数据无效，请重新准备图片")
    if len(raw) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        _fail("PNG 像素大小或压缩数据不匹配")
    if any(raw[offset] > 4 for offset in range(0, expected, stride)): _fail("PNG 行过滤数据无效")
    result = PNG + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")
    if len(result) > MAX_PNG_BYTES: _fail("处理后的 PNG 超过8MB，请缩小图片")
    return result, width, height


def source_fingerprint(material):
    return media._hash({"id": material.id, "customer_id": material.customer_id, "visibility": material.visibility,
        "file_path": material.file_path, "file_url": material.file_url, "content_type": material.content_type,
        "updated_at": media._iso(material.updated_at)})


def _stat(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)


def _open_directory(path):
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def _read_regular(directory, name, maximum, *, metadata_only=False):
    if not name or name in {".", ".."} or "/" in name or "\\" in name or any(ord(c) < 32 for c in name): _fail()
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= maximum: _fail()
        if metadata_only: return None, _stat(before)
        with os.fdopen(fd, "rb", closefd=False) as stream: body = stream.read(maximum + 1)
        if len(body) != before.st_size or _stat(before) != _stat(os.fstat(fd)): _fail("文件正在变化，请重新读取")
        return body, _stat(before)
    finally:
        os.close(fd)


def _source_file(material, *, metadata_only=False):
    path = str(material.file_path or "")
    if not path or len(path) > 1024 or "\\" in path or any(ord(c) < 32 for c in path): _fail("仅可为该客户的私有上传图片准备发布副本")
    parts = path.split("/")
    if len(parts) != 2 or parts[0] != str(material.customer_id) or parts[1] in {"", ".", ".."}: _fail()
    root = customer = None
    try:
        root = _open_directory(MATERIALS_ROOT)
        customer = os.open(parts[0], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        return _read_regular(customer, parts[1], MAX_SOURCE_BYTES, metadata_only=metadata_only)
    except OSError:
        _fail("原始上传文件不可读取，请重新上传后准备图片")
    finally:
        if customer is not None: os.close(customer)
        if root is not None: os.close(root)


def _source_bytes(material):
    return _source_file(material)


def _source_stat(material):
    return _source_file(material, metadata_only=True)[1]


def _write_image(key, body):
    if not IDENTITY.fullmatch(key): _fail()
    root = images = fd = None
    try:
        root = _open_directory(MATERIALS_ROOT)
        try:
            os.mkdir(".publication-images", mode=0o700, dir_fd=root)
            os.fsync(root)
        except FileExistsError: pass
        images = os.open(".publication-images", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        fd = os.open(key + ".png", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=images)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(body); stream.flush(); os.fsync(fd)
        os.fsync(images)
        return _stat(os.fstat(fd))
    except OSError:
        raise HTTPException(503, "图片副本暂未保存，请保留本次请求编号并核对结果")
    finally:
        if fd is not None: os.close(fd)
        if images is not None: os.close(images)
        if root is not None: os.close(root)


def _image_file(row, *, metadata_only=False):
    if not IDENTITY.fullmatch(str(row.file_key or "")): _fail()
    root = images = None
    try:
        root = _open_directory(MATERIALS_ROOT)
        images = os.open(".publication-images", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        body, signature = _read_regular(images, row.file_key + ".png", MAX_PNG_BYTES, metadata_only=metadata_only)
        if metadata_only: return signature
        if len(body) != row.byte_size or hashlib.sha256(body).hexdigest() != row.image_sha256: _fail("发布副本校验失败，请重新准备并审核")
        return body
    except OSError:
        _fail("发布副本不可读取，请重新准备并审核")
    finally:
        if images is not None: os.close(images)
        if root is not None: os.close(root)


def _image_bytes(row):
    return _image_file(row)


def _image_stat(row):
    return _image_file(row, metadata_only=True)


async def _context(db, user):
    ctx = await media.context(db, user)
    row = await db.get(Employees, ctx.identity, populate_existing=True)
    if not row or row.status not in {"active", "probation"} or normalized_role(SimpleNamespace(role=row.role)) != normalized_role(user):
        raise HTTPException(403, "当前员工身份已失效，请重新登录")
    await require_tables(db, TABLES)
    db.info[_SCHEMA_KEY] = True
    return ctx


async def _material(db, ctx, customer_id, material_id, *, write=False):
    customer, permissions = await media._customer(db, ctx, customer_id, write=write)
    material = await media._material(db, ctx, customer, material_id, proof=True)
    if write and (not ctx.can_edit or not permissions["modules"]["materials"]["write"]):
        raise HTTPException(403, "此客户尚未开放素材编辑与运营协作")
    if not material or not material.file_path: _fail("请先上传该客户的私有图片，再准备发布副本")
    return material, permissions


async def _valid_image(db, ctx, row, *, customer_id=None, material_id=None, verify_bytes=False):
    if not row or customer_id is not None and row.customer_id != customer_id or material_id is not None and row.material_id != material_id:
        raise HTTPException(422, "图片版本与客户或素材不匹配")
    material, _ = await _material(db, ctx, row.customer_id, row.material_id)
    if row.revoked_at is not None: raise HTTPException(422, "这份发布图片已撤销，请重新选择")
    if source_fingerprint(material) != row.source_fingerprint: raise HTTPException(422, "原素材已发生变化，请重新准备图片并审核")
    if verify_bytes:
        # Immutable private files are hashed at creation and whenever bytes are
        # served. Short transaction fences use descriptor metadata including
        # inode and nanosecond ctime; application APIs cannot rewrite a source.
        if tuple(row.source_file_stat or ()) != await asyncio.to_thread(_source_stat, material):
            raise HTTPException(422, "原文件内容已发生变化，请重新准备图片并审核")
        if tuple(row.image_file_stat or ()) != await asyncio.to_thread(_image_stat, row):
            raise HTTPException(422, "发布副本已发生变化，请重新准备图片并审核")
    return material


def image_data(row, ctx, material=None):
    state = "revoked" if row.revoked_at else "source_changed" if material is None or source_fingerprint(material) != row.source_fingerprint else "ready"
    return {"id": row.id, "customer_id": row.customer_id, "material_id": row.material_id, "request_id": row.request_id,
        "source_sha256": row.source_sha256, "image_sha256": row.image_sha256, "width": row.width, "height": row.height,
        "byte_size": row.byte_size, "rights_basis": row.rights_basis, "created_at": media._iso(row.created_at),
        "revoked_at": media._iso(row.revoked_at), "status": state,
        "preview_path": "/api/v1/media-publication-images/" + row.id + "/preview", "can_revoke": bool(ctx.owner and not row.revoked_at)}


async def _owner_for_customer(db, ctx, customer_id=None):
    if customer_id is None:
        return ctx.identity if ctx.owner else None
    await media._customer(db, ctx, customer_id)
    from models.google_business import GoogleBusinessBinding as Binding, GoogleBusinessConnection as Connection
    query = select(Connection.owner_id).join(Binding, Binding.connection_id == Connection.id).where(Binding.customer_id == customer_id, Binding.active.is_(True), Connection.active.is_(True))
    values = list((await db.execute(query)).scalars())
    if len(set(values)) != 1: return ctx.identity if ctx.owner and not values else None
    return values[0]


async def delivery_policy(db, user, customer_id=None):
    ctx = await _context(db, user)
    owner_id = await _owner_for_customer(db, ctx, customer_id)
    row = await db.get(Policy, owner_id, populate_existing=True) if owner_id is not None else None
    return {"enabled": bool(row and row.enabled), "can_manage": bool(ctx.owner and owner_id == ctx.identity), "notice": NOTICE,
        "activated_at": media._iso(row.activated_at) if row else None}


async def set_delivery_policy(db, user, *, enabled, public_delivery_confirmed):
    ctx = await _context(db, user)
    if not ctx.owner: raise HTTPException(403, "仅老板可以启用图片发布投递")
    if type(enabled) is not bool or type(public_delivery_confirmed) is not bool or enabled and not public_delivery_confirmed:
        raise HTTPException(422, "请确认发布副本的免登录读取范围后再启用")
    async with media._write(db):
        row = await db.get(Policy, ctx.identity, populate_existing=True, with_for_update=True)
        if row is None:
            row = Policy(owner_id=ctx.identity, enabled=enabled, activated_at=media.now() if enabled else None, updated_at=media.now()); db.add(row)
        else:
            if enabled and not row.enabled: row.activated_at = media.now()
            row.enabled = enabled; row.updated_at = media.now()
    return await delivery_policy(db, user)


async def list_images(db, user, *, customer_id, material_id):
    ctx = await _context(db, user)
    material, permissions = await _material(db, ctx, customer_id, material_id)
    rows = list((await db.execute(select(Image).where(Image.customer_id == customer_id, Image.material_id == material_id).order_by(Image.created_at.desc(), Image.id).limit(50))).scalars())
    policy = await delivery_policy(db, user, customer_id)
    return {"items": [image_data(row, ctx, material) for row in rows], "delivery_available": policy["enabled"],
        "can_prepare": bool(ctx.can_edit and permissions["modules"]["delivery"]["write"] and permissions["modules"]["materials"]["write"])}


async def prepare(db, user, *, customer_id, material_id, source_sha256, rights_basis, rights_confirmed, request_id, body):
    ctx = await _context(db, user)
    request_id = media._key(request_id)
    if not SHA.fullmatch(str(source_sha256 or "")) or rights_basis not in {"owned", "client_provided", "licensed"} or rights_confirmed is not True:
        _fail("请核对原文件校验码并确认图片使用权")
    material, _ = await _material(db, ctx, customer_id, material_id, write=True)
    # Bounded decoding, hashing and encoding happen before the SQL write lock.
    source_stat, canonical, width, height = await _bounded_processing(material, body, source_sha256)
    source_reference = source_fingerprint(material)
    image_hash = hashlib.sha256(canonical).hexdigest()
    fingerprint = media._hash({"customer_id": customer_id, "material_id": material_id, "source_sha256": source_sha256,
        "source_fingerprint": source_reference, "image_sha256": image_hash, "rights_basis": rights_basis})
    # A GET-only replay is resolved before touching storage. Concurrent fresh
    # attempts may leave a private unreferenced file; they never create a lease.
    previous = await db.scalar(select(Image).where(Image.prepared_by_id == ctx.identity, Image.request_id == request_id))
    if previous:
        if previous.request_fingerprint != fingerprint: raise HTTPException(409, "本次请求编号已用于不同图片，请先核对原结果")
        return image_data(previous, ctx, material)
    identity = uuid4().hex
    image_stat = await asyncio.to_thread(_write_image, identity, canonical)
    async with media._write(db):
        material, _ = await _material(db, ctx, customer_id, material_id, write=True)
        if source_fingerprint(material) != source_reference: raise HTTPException(409, "原素材已更新，请重新准备")
        existing = await db.scalar(select(Image).where(Image.prepared_by_id == ctx.identity, Image.request_id == request_id))
        if existing:
            if existing.request_fingerprint != fingerprint: raise HTTPException(409, "本次请求编号已用于不同图片，请先核对原结果")
            return image_data(existing, ctx, material)
        # A fresh descriptor check detects an in-place replacement after hashing.
        if await asyncio.to_thread(_source_stat, material) != source_stat: raise HTTPException(409, "原文件正在变化，请重新准备")
        row = Image(id=identity, customer_id=customer_id, material_id=material_id, prepared_by_id=ctx.identity,
            request_id=request_id, request_fingerprint=fingerprint, source_sha256=source_sha256, source_fingerprint=source_reference,
            source_file_stat=list(source_stat), image_file_stat=list(image_stat),
            image_sha256=image_hash, width=width, height=height, byte_size=len(canonical), rights_basis=rights_basis,
            file_key=identity, delivery_token=secrets.token_urlsafe(32), created_at=media.now())
        db.add(row); await db.flush()
        result = image_data(row, ctx, material)
    return result


async def request_image(db, user, request_id):
    ctx = await _context(db, user); request_id = media._key(request_id)
    row = await db.scalar(select(Image).where(Image.prepared_by_id == ctx.identity, Image.request_id == request_id))
    if row is None: raise HTTPException(404, "尚未查到本次图片请求，请保留原请求编号稍后再查")
    material, _ = await _material(db, ctx, row.customer_id, row.material_id)
    return image_data(row, ctx, material)


async def preview(db, user, image_id):
    ctx = await _context(db, user)
    row = await db.get(Image, image_id) if IDENTITY.fullmatch(image_id) else None
    await _valid_image(db, ctx, row, verify_bytes=True)
    frozen = SimpleNamespace(file_key=row.file_key, byte_size=row.byte_size, image_sha256=row.image_sha256)
    # Do not carry a DB read snapshot or row lock across a slow disk read.
    await db.rollback()
    body = await asyncio.to_thread(_image_bytes, frozen)
    ctx = await _context(db, user)
    fresh = await db.get(Image, image_id, populate_existing=True)
    await _valid_image(db, ctx, fresh, verify_bytes=True)
    if fresh.image_sha256 != frozen.image_sha256 or fresh.file_key != frozen.file_key or fresh.byte_size != len(body):
        raise HTTPException(409, "发布图片已变化，请重新读取")
    return body


async def revoke(db, user, image_id):
    ctx = await _context(db, user)
    if not ctx.owner: raise HTTPException(403, "仅老板可以撤销发布图片")
    async with media._write(db):
        row = await db.get(Image, image_id, populate_existing=True, with_for_update=True) if IDENTITY.fullmatch(image_id) else None
        if row is None: raise HTTPException(404, "图片版本不存在")
        await media._customer(db, ctx, row.customer_id)
        try: material, _ = await _material(db, ctx, row.customer_id, row.material_id)
        except HTTPException: material = None
        if not row.revoked_at: row.revoked_at = media.now()
        result = image_data(row, ctx, material)
    return result


async def selection_for_task(db, task):
    if not await _available(db): return None
    selection = await db.get(Selection, task.id, populate_existing=True)
    return await db.get(Image, selection.image_id, populate_existing=True) if selection else None


async def save_selection(db, ctx, task, image_version_id):
    if image_version_id is not None:
        await require_tables(db, TABLES)
        db.info[_SCHEMA_KEY] = True
        if not isinstance(image_version_id, str) or not IDENTITY.fullmatch(image_version_id): _fail("请选择有效的发布图片版本")
        if task.platform != "google_business" or task.material_id is None: _fail("发布图片版本仅适用于已关联素材的 Google 任务")
        row = await db.get(Image, image_version_id, populate_existing=True)
        await _valid_image(db, ctx, row, customer_id=task.customer_id, material_id=task.material_id, verify_bytes=True)
    elif not await _available(db): return
    selection = await db.get(Selection, task.id, populate_existing=True)
    if image_version_id is None:
        if selection: await db.delete(selection)
    elif selection: selection.image_id = image_version_id
    else: db.add(Selection(task_id=task.id, image_id=image_version_id))
    await db.flush()


async def task_image_data(db, ctx, task, permissions):
    return (await task_images_data(db, ctx, [task], {task.customer_id: permissions}))[task.id]


async def task_images_data(db, ctx, tasks, permissions):
    """Batch read DTOs; no per-task table inspection or permission queries."""
    output = {task.id: None for task in tasks}
    allowed = {task.id: task for task in tasks if permissions[task.customer_id]["modules"]["materials"]["read"]}
    if not allowed or not await _available(db): return output
    rows = list((await db.execute(select(Selection.task_id, Image).join(Image, Image.id == Selection.image_id)
        .where(Selection.task_id.in_(list(allowed))).execution_options(populate_existing=True))).all())
    material_ids = {image.material_id for _, image in rows}
    materials = {row.id: row for row in (await db.execute(select(Customer_materials).where(Customer_materials.id.in_(material_ids),
        Customer_materials.visibility == "team").execution_options(populate_existing=True))).scalars()} if material_ids else {}
    for task_id, image in rows:
        task = allowed[task_id]; material = materials.get(image.material_id)
        if (material is not None and image.customer_id == task.customer_id == material.customer_id and
                image.material_id == task.material_id): output[task_id] = image_data(image, ctx, material)
    return output


async def approval_snapshot(db, ctx, task):
    row = await selection_for_task(db, task)
    if row is None: return None
    await _valid_image(db, ctx, row, customer_id=task.customer_id, material_id=task.material_id, verify_bytes=True)
    return {"id": row.id, "source_sha256": row.source_sha256, "source_fingerprint": row.source_fingerprint,
        "image_sha256": row.image_sha256, "width": row.width, "height": row.height, "byte_size": row.byte_size,
        "rights_basis": row.rights_basis}


def delivery_url(row):
    from services import google_business_provider as provider
    settings = provider.require_config()
    return settings["PUBLIC_URL"] + "/api/v1/media-publication-images/delivery/" + row.delivery_token + ".png"


async def approved_image(db, ctx, binding, task, approval):
    row = await selection_for_task(db, task)
    if row is None:
        if approval.get("publication_image") is not None: _fail("已审核的发布图片版本不再匹配，请重新审核")
        return None
    expected = await approval_snapshot(db, ctx, task)
    if approval.get("publication_image") != expected: _fail("最终发布图片尚未经过当前版本审核，请退回并重新审核")
    from models.google_business import GoogleBusinessConnection as Connection
    connection = await db.get(Connection, binding.connection_id, populate_existing=True)
    policy = await db.get(Policy, connection.owner_id, populate_existing=True) if connection else None
    if not policy or not policy.enabled: raise HTTPException(422, "老板尚未启用图片发布投递；可先准备和审核图片，启用后再发布")
    return row


async def activate_delivery(db, ctx, binding, task, approval, action):
    row = await approved_image(db, ctx, binding, task, approval)
    if row is None: return
    if action.dispatch_started_at is None or action.kind != "post_publish" or action.task_id != task.id or action.actor_id != ctx.identity:
        raise HTTPException(409, "图片投递必须对应已登记的本次发布请求")
    media_items = (action.payload or {}).get("media")
    if media_items != [{"mediaFormat": "PHOTO", "sourceUrl": delivery_url(row)}]: raise HTTPException(409, "图片投递请求与审核版本不匹配")
    old = await db.get(Delivery, action.id, populate_existing=True)
    if old:
        if old.image_id != row.id: raise HTTPException(409, "原图片投递记录不匹配")
        return
    db.add(Delivery(action_id=action.id, image_id=row.id, activated_at=action.dispatch_started_at,
        expires_at=action.dispatch_started_at + timedelta(days=14)))
    await db.flush()


async def _delivery_image(db, token):
    """Read-only, current authorization for an explicit dispatch lease."""
    denial = HTTPException(404, "图片不存在或投递已失效")
    try:
        if not isinstance(token, str) or not TOKEN.fullmatch(token) or not await _available(db): raise denial
        row = await db.scalar(select(Image).where(Image.delivery_token == token))
        if row is None or row.revoked_at: raise denial
        from models.google_business import GoogleBusinessAction as Action
        grants = list((await db.execute(select(Delivery, Action).join(Action, Action.id == Delivery.action_id).where(
            Delivery.image_id == row.id, Delivery.expires_at > media.now(), Action.kind == "post_publish",
            Action.dispatch_started_at.is_not(None), Action.status.in_(("pending", "unknown", "accepted", "succeeded")))
            .order_by(Delivery.activated_at.desc()).limit(20))).all())
        from services import google_business as google
        for grant, action in grants:
            try:
                employee = await db.get(Employees, action.actor_id, populate_existing=True)
                if not employee: continue
                user = SimpleNamespace(id=str(employee.id), role=employee.role, name=employee.name)
                ctx = await google.context(db, user)
                binding, connection, _ = await google._binding(db, ctx, action.binding_id, action="publish")
                policy = await db.get(Policy, connection.owner_id, populate_existing=True)
                if (not policy or not policy.enabled or policy.activated_at is None or binding.customer_id != row.customer_id or
                        google.aware(grant.activated_at) < google.aware(policy.activated_at)): continue
                task, _, task_permissions = await media._get_task(db, ctx, action.task_id)
                if not ctx.can_edit or not task_permissions["modules"]["delivery"]["write"]: continue
                if task.status not in {"ready", "completed"} or task.customer_id != row.customer_id or task.material_id != row.material_id: continue
                selected = await selection_for_task(db, task)
                if not selected or selected.id != row.id: continue
                if (action.payload or {}).get("media") != [{"mediaFormat": "PHOTO", "sourceUrl": delivery_url(row)}]: continue
                await _valid_image(db, ctx, row, verify_bytes=True)
                return row
            except HTTPException:
                continue
        raise denial
    except HTTPException:
        raise denial


async def public_delivery(db, token):
    """Uniform denial and a fresh post-I/O grant check before returning bytes."""
    denial = HTTPException(404, "图片不存在或投递已失效")
    try:
        row = await _delivery_image(db, token)
        frozen = SimpleNamespace(file_key=row.file_key, byte_size=row.byte_size, image_sha256=row.image_sha256, id=row.id)
        await db.rollback()
        body = await asyncio.to_thread(_image_bytes, frozen)
        fresh = await _delivery_image(db, token)
        if (fresh.id, fresh.file_key, fresh.image_sha256, fresh.byte_size) != (frozen.id, frozen.file_key, frozen.image_sha256, len(body)):
            raise denial
        return body
    except HTTPException:
        raise denial


async def submitted_image_data(db, ctx, action):
    """Historical identity comes only from the immutable dispatch lease."""
    if action.kind != "post_publish" or not await _available(db): return {}
    from services import google_business as google
    if action.created_at is None or google.aware(action.created_at) < google.now() - timedelta(days=30): return {}
    lease = await db.get(Delivery, action.id)
    row = await db.get(Image, lease.image_id) if lease else None
    if row is None or row.customer_id != action.customer_id: return {}
    try:
        material, _ = await _material(db, ctx, row.customer_id, row.material_id)
    except HTTPException:
        return {}
    # A later source change never rewrites what was submitted. It only removes
    # the current private preview while retaining authorized immutable hashes.
    state = "revoked" if row.revoked_at else "source_changed" if source_fingerprint(material) != row.source_fingerprint else "ready"
    if state == "ready":
        try:
            await _valid_image(db, ctx, row, verify_bytes=True)
        except HTTPException:
            state = "source_changed"
    return {"submitted_image_version_id": row.id, "submitted_image_sha256": row.image_sha256,
        "submitted_image_status": state,
        "submitted_publication_image": {**image_data(row, ctx, material), "status": state},
        "submitted_image_preview_path": "/api/v1/media-publication-images/" + row.id + "/preview" if state == "ready" else None}
