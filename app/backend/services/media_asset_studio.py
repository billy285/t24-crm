"""Owner-only private real-photo jobs, never a publisher or monthly mutator."""
from __future__ import annotations
import asyncio
import base64
import contextlib
from datetime import timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
from uuid import uuid4, uuid5, NAMESPACE_URL

from fastapi import HTTPException
from sqlalchemy import func, select
from models.customer_materials import Customer_materials as Material
from models.customer_menu_items import Customer_menu_items as MenuItem
from models.customer_record_audits import CustomerRecordAudit
from models.employees import Employees
from models.media_asset_studio import MediaAssetProfile as Profile, MediaAssetJob as Job, MediaAssetRequest as Request
from models.media_publication_images import MediaPublicationImage as Image
from services import media_operations as media, media_publication_images as images
from services.role_permissions import normalized_role
from services.schema_readiness import require_tables, tables_available

TABLES = {"media_asset_profiles", "media_asset_jobs", "media_asset_requests"}
PREFIX = "/api/v1/media-asset-studio"
RENDERER = Path(__file__).with_name("media_asset_renderer.py")
MAX_OUTPUT = 24 * 1024 * 1024
LEASE_SECONDS = 120
_runtime = None
_runtime_lock = None
_worker = None


def _utc(value): return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


async def context(db, user, customer_id=None, *, write=False):
    # Reject employees before any SQL. No new role, invitation or implicit grant.
    if normalized_role(user) != "super_admin": raise HTTPException(403, "素材制作目前仅老板可使用")
    ctx = await images._context(db, user)
    if not ctx.owner: raise HTTPException(403, "素材制作目前仅老板可使用")
    await require_tables(db, TABLES)
    if customer_id is None: return ctx, None
    customer, permissions = await media._customer(db, ctx, customer_id, write=write)
    if not permissions["modules"]["materials"]["read"] or write and not permissions["modules"]["materials"]["write"]:
        raise HTTPException(403, "客户素材权限尚未开放")
    if write and customer.status != "closed": raise HTTPException(409, "仅合作中的客户可制作或采用新素材，历史结果仍可查看")
    return ctx, customer


def capabilities(customer):
    engine = _runtime or {"image":False, "video":False, "message":"正在检查本地制作引擎，请稍后刷新"}
    active = customer.status == "closed"
    return {"can_edit":active, "can_create":active and engine["image"], "can_adopt":active,
        "poster":engine["image"], "collage":engine["image"], "enhance":engine["image"], "video":engine["video"],
        "video_reason":None if engine["video"] else engine.get("message") or "本地短视频引擎尚未通过验收", "engine_message":engine.get("message")}


def _default(customer):
    return {"revision":0, "preset":"editorial", "brand_name":str(customer.business_name or "")[:60] or "商家",
        "primary_color":"#1F2937", "accent_color":"#F59E0B", "footer":""}


def _contrast(profile):
    background = {"warm":"#F6F3EC", "clean":"#F8FAFC", "editorial":"#FFFFFF"}[profile["preset"]]
    def luminance(value):
        rgb = [int(value[i:i+2], 16)/255 for i in (1,3,5)]
        rgb = [v/12.92 if v <= 0.04045 else ((v+0.055)/1.055)**2.4 for v in rgb]
        return sum(v*w for v,w in zip(rgb, (0.2126,0.7152,0.0722)))
    a,b = sorted((luminance(profile["primary_color"]), luminance(background)))
    if (b+0.05)/(a+0.05) < 4.5: raise HTTPException(422, "文字颜色太浅，请选择深色，确保海报文字清晰可读")


async def _profile(db, ctx, customer):
    row = await db.get(Profile, (ctx.identity, customer.id), populate_existing=True)
    return {"revision":row.revision, **row.settings} if row else _default(customer)


def _source_data(row, material, *, suggested_title):
    return {"material_id":material.id, "title":material.title, "suggested_title":suggested_title, "linked_item_id":material.linked_item_id,
        "image_id":row.id, "image_sha256":row.image_sha256, "width":row.width, "height":row.height, "byte_size":row.byte_size,
        "preview_path":"/api/v1/media-publication-images/"+row.id+"/preview", "rights_basis":row.rights_basis}


async def _source(db, ctx, customer, identity, *, verify=False):
    row = await db.get(Image, identity, populate_existing=True) if images.IDENTITY.fullmatch(str(identity)) else None
    material = await images._valid_image(db, ctx, row, customer_id=customer.id, verify_bytes=verify)
    if row.rights_basis not in {"owned", "client_provided", "licensed"}: raise HTTPException(409, "原图使用权依据不可用")
    menu = await db.get(MenuItem, material.linked_item_id, populate_existing=True) if material.linked_item_id else None
    menu_name = menu.name if menu and menu.customer_id == customer.id and menu.status == "active" else None
    proof = {"id":row.id, "material_id":material.id, "image_sha256":row.image_sha256,
        "source_sha256":row.source_sha256, "source_fingerprint":row.source_fingerprint,
        "source_file_stat":row.source_file_stat, "image_file_stat":row.image_file_stat, "rights_basis":row.rights_basis,
        "linked_item_id":material.linked_item_id, "linked_item_snapshot":material.linked_item_snapshot,
        "title":material.title, "copyright_status":material.copyright_status, "menu_name":menu_name}
    return row, material, proof


async def _fresh_sources(db, ctx, customer, snapshot, *, verify=False):
    if customer.status != "closed": raise HTTPException(409, "客户已停止合作，不能继续制作或采用")
    if await _profile(db, ctx, customer) != snapshot["profile"]: raise HTTPException(409, "品牌模板已更新，请按新模板重新制作")
    result = []
    for saved in snapshot["proofs"]:
        row, material, proof = await _source(db, ctx, customer, saved["id"], verify=verify)
        if proof != saved: raise HTTPException(409, "原素材或固定版本已变化，请重新选择制作")
        result.append(row)
    return result


async def _job(db, ctx, identity, *, lock=False):
    if not images.IDENTITY.fullmatch(str(identity)): raise HTTPException(404, "制作任务不存在")
    query = select(Job).where(Job.id == identity, Job.owner_id == ctx.identity).execution_options(populate_existing=True)
    if lock: query = query.with_for_update()
    row = await db.scalar(query)
    if row is None: raise HTTPException(404, "制作任务不存在")
    customer, _ = await media._customer(db, ctx, row.customer_id)
    return row, customer


async def job_data(db, ctx, row, customer):
    stale = False
    try: await _fresh_sources(db, ctx, customer, row.snapshot, verify=True)
    except HTTPException: stale = True
    output = None
    if row.output:
        output = {k:row.output[k] for k in ("mime_type", "sha256", "byte_size", "width", "height", "duration_seconds")}
        output.update(preview_path=PREFIX+"/jobs/"+row.id+"/preview", download_path=PREFIX+"/jobs/"+row.id+"/download")
    return {"id":row.id, "customer_id":row.customer_id, "request_id":row.request_id, "revision":row.revision, "kind":row.kind,
        "status":row.status, "profile_revision":row.snapshot["profile"]["revision"], "recipe":row.snapshot["recipe"], "sources":row.snapshot["sources"],
        "created_at":media._iso(row.created_at), "updated_at":media._iso(row.updated_at), "error_code":row.error_code,
        "message":row.message, "source_stale":stale, "output":output, "adoption":row.adoption,
        "can_retry":not stale and row.status in {"failed", "unknown"}, "can_adopt":not stale and row.status == "succeeded"}


async def studio(db, user, customer_id):
    ctx, customer = await context(db, user, customer_id)
    profile = await _profile(db, ctx, customer)
    versions = list((await db.scalars(select(Image).where(Image.customer_id == customer.id, Image.revoked_at.is_(None))
        .order_by(Image.created_at.desc(), Image.id).limit(200))).all())
    sources = []
    for version in versions:
        try:
            _, material, proof = await _source(db, ctx, customer, version.id, verify=True)
            suggestion = proof["menu_name"] if proof["menu_name"] and len(proof["menu_name"]) <= 80 else profile["brand_name"]
            sources.append(_source_data(version, material, suggested_title=suggestion))
        except HTTPException: continue
    jobs = list((await db.scalars(select(Job).where(Job.owner_id == ctx.identity, Job.customer_id == customer.id)
        .order_by(Job.created_at.desc(), Job.id).limit(50))).all())
    suggestions = []
    if await tables_available(db, {"media_monthly_runs", "media_monthly_items"}):
        from models.media_monthly import MediaMonthlyRun, MediaMonthlyItem
        titles = list((await db.scalars(select(MediaMonthlyItem.title).join(MediaMonthlyRun, MediaMonthlyItem.run_id == MediaMonthlyRun.id)
            .where(MediaMonthlyRun.owner_id == ctx.identity, MediaMonthlyRun.customer_id == customer.id, MediaMonthlyRun.status == "generated")
            .order_by(MediaMonthlyRun.created_at.desc(), MediaMonthlyItem.slot_id).limit(24))).all())
        suggestions = [{"title":title, "subtitle":"", "source_label":"现有内容草稿，采用前请核对"} for title in dict.fromkeys(titles) if 0 < len(title) <= 80][:12]
    return {"customer_id":customer.id, "customer_name":customer.business_name, "cooperation_active":customer.status == "closed",
        "read_only_reason":None if customer.status == "closed" else "客户已停止合作，仅可查看制作历史",
        "capabilities":capabilities(customer), "profile":profile, "sources":sources, "copy_suggestions":suggestions,
        "jobs":[await job_data(db, ctx, row, customer) for row in jobs]}


async def get_job(db, user, identity):
    ctx, _ = await context(db, user); row, customer = await _job(db, ctx, identity)
    return await job_data(db, ctx, row, customer)


async def _receipt(db, ctx, request_id, *, kind=None, fingerprint=None):
    row = await db.scalar(select(Request).where(Request.owner_id == ctx.identity, Request.request_id == request_id))
    if row and (kind is not None and row.kind != kind or fingerprint is not None and row.fingerprint != fingerprint):
        raise HTTPException(409, "该请求编号已用于其他内容，请先查看原结果")
    return row


async def _result(db, ctx, row):
    customer, _ = await media._customer(db, ctx, row.customer_id)
    job = None
    if row.result.get("job_id"):
        current, customer = await _job(db, ctx, row.result["job_id"])
        job = await job_data(db, ctx, current, customer)
    return {"kind":row.kind, "request_id":row.request_id, "customer_id":row.customer_id, "job":job,
        "profile":await _profile(db, ctx, customer) if row.kind == "profile" else None}


async def request_result(db, user, request_id):
    ctx, _ = await context(db, user); row = await _receipt(db, ctx, media._key(request_id))
    if row is None: raise HTTPException(404, "未找到该请求，任务未登记时可使用原编号重试")
    return await _result(db, ctx, row)


def _record(db, ctx, customer_id, request_id, kind, fingerprint, job_id=None):
    row = Request(owner_id=ctx.identity, customer_id=customer_id, request_id=request_id, kind=kind, fingerprint=fingerprint,
        result={"job_id":job_id}, created_at=media.now()); db.add(row); return row


def _text(value):
    if any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value): raise HTTPException(422, "品牌与文案不支持控制字符或换行，请使用普通文字")
    return value.strip()


async def save_profile(db, user, customer_id, value):
    ctx, customer = await context(db, user, customer_id, write=True)
    data = value.model_dump(); request_id = media._key(data.pop("request_id")); fp = media._hash({"customer_id":customer_id, **data})
    async with media._write(db):
        ctx, customer = await context(db, user, customer_id, write=True)
        prior = await _receipt(db, ctx, request_id, kind="profile", fingerprint=fp)
        if prior: return await _result(db, ctx, prior)
        current = await _profile(db, ctx, customer)
        if current["revision"] != data.pop("expected_revision"): raise HTTPException(409, "品牌模板版本已变化，请刷新核对")
        data["brand_name"] = _text(data["brand_name"]); data["footer"] = _text(data["footer"])
        if not data["brand_name"]: raise HTTPException(422, "请输入真实商家名称")
        data["primary_color"] = data["primary_color"].upper(); data["accent_color"] = data["accent_color"].upper()
        _contrast(data)
        row = await db.get(Profile, (ctx.identity, customer_id), populate_existing=True)
        if row is None: row = Profile(owner_id=ctx.identity, customer_id=customer_id); db.add(row)
        row.revision = current["revision"]+1; row.settings = data; row.updated_at = media.now()
        receipt = _record(db, ctx, customer_id, request_id, "profile", fp); await db.flush()
        return await _result(db, ctx, receipt)


async def create_job(db, user, customer_id, value):
    ctx, customer = await context(db, user, customer_id, write=True)
    data = value.model_dump(); request_id = media._key(data.pop("request_id")); fp = media._hash({"customer_id":customer_id, **data})
    async with media._write(db):
        ctx, customer = await context(db, user, customer_id, write=True)
        prior = await _receipt(db, ctx, request_id, kind="create", fingerprint=fp)
        if prior: return await _result(db, ctx, prior)
        cap = capabilities(customer)
        if not cap[data["kind"]]: raise HTTPException(503, cap["video_reason"] or "本地制作引擎尚未通过验收，请稍后刷新")
        n = len(data["image_ids"])
        if not ((data["kind"] in {"poster", "enhance"} and n == 1) or (data["kind"] == "collage" and 2 <= n <= 4) or (data["kind"] == "video" and 2 <= n <= 6)):
            raise HTTPException(422, "单图海报或修图选1张，拼图选2—4张，短视频选2—6张")
        if (data["kind"] == "enhance") != (data["format"] == "original"):
            raise HTTPException(422, "基础修图请保留原尺寸；海报、拼图和短片请选择版式")
        if await db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(["queued", "processing"]))) >= 20:
            raise HTTPException(429, "制作队列已满，请等待已有任务完成")
        profile = await _profile(db, ctx, customer)
        if profile["revision"] != data["profile_revision"]: raise HTTPException(409, "品牌模板已更新，请刷新后选择")
        _contrast(profile)
        data["title"] = _text(data["title"]); data["subtitle"] = _text(data["subtitle"])
        proofs = []; descriptors = []
        for identity in data["image_ids"]:
            image, material, proof = await _source(db, ctx, customer, identity, verify=True)
            suggestion = proof["menu_name"] if proof["menu_name"] and len(proof["menu_name"]) <= 80 else profile["brand_name"]
            proofs.append(proof); descriptors.append(_source_data(image, material, suggested_title=suggestion))
        row = Job(id=uuid4().hex, owner_id=ctx.identity, customer_id=customer_id, request_id=request_id, fingerprint=fp,
            revision=1, kind=data["kind"], status="queued", snapshot={"profile":profile, "recipe":data, "proofs":proofs, "sources":descriptors},
            attempt=0, message="已加入私有制作队列，不会发布", created_at=media.now(), updated_at=media.now())
        db.add(row); receipt = _record(db, ctx, customer_id, request_id, "create", fp, row.id); await db.flush()
        return await _result(db, ctx, receipt)


async def retry(db, user, identity, value):
    ctx, _ = await context(db, user); data = value.model_dump(); request_id = media._key(data["request_id"])
    fp = media._hash({"job_id":identity, **data})
    async with media._write(db):
        prior = await _receipt(db, ctx, request_id, kind="retry", fingerprint=fp)
        if prior: return await _result(db, ctx, prior)
        row, customer = await _job(db, ctx, identity, lock=True)
        await context(db, user, customer.id, write=True)
        if row.revision != data["expected_revision"] or row.status not in {"failed", "unknown"}: raise HTTPException(409, "任务状态已变化，请核对原结果")
        await _fresh_sources(db, ctx, customer, row.snapshot, verify=True)
        row.status = "queued"; row.revision += 1; row.lease_token = None; row.lease_at = None; row.output = None; row.error_code = None
        row.message = "已明确重新加入私有制作队列，原图不会改变"; row.updated_at = media.now()
        receipt = _record(db, ctx, row.customer_id, request_id, "retry", fp, row.id); await db.flush()
        return await _result(db, ctx, receipt)


def _artifact_write(key, suffix, body):
    if not images.IDENTITY.fullmatch(key) or suffix not in {"png", "mp4"} or not 0 < len(body) <= MAX_OUTPUT: raise HTTPException(422, "制作副本无效")
    root = directory = fd = None
    try:
        root = images._open_directory(images.MATERIALS_ROOT)
        try: os.mkdir(".asset-studio", mode=0o700, dir_fd=root); os.fsync(root)
        except FileExistsError: pass
        directory = os.open(".asset-studio", os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW, dir_fd=root)
        fd = os.open(key+"."+suffix, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600, dir_fd=directory)
        with os.fdopen(fd, "wb", closefd=False) as stream: stream.write(body); stream.flush(); os.fsync(fd)
        os.fsync(directory); return list(images._stat(os.fstat(fd)))
    except OSError: raise HTTPException(503, "制作副本保存结果待确认，请查看原任务")
    finally:
        if fd is not None: os.close(fd)
        if directory is not None: os.close(directory)
        if root is not None: os.close(root)


def _artifact_read(output):
    key, suffix = output["file_key"], "png" if output["mime_type"] == "image/png" else "mp4"
    if not images.IDENTITY.fullmatch(key): raise HTTPException(422, "制作副本无效")
    root = directory = None
    try:
        root = images._open_directory(images.MATERIALS_ROOT); directory = os.open(".asset-studio", os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW, dir_fd=root)
        body, signature = images._read_regular(directory, key+"."+suffix, MAX_OUTPUT)
        if list(signature) != output["file_stat"] or len(body) != output["byte_size"] or hashlib.sha256(body).hexdigest() != output["sha256"]:
            raise HTTPException(409, "制作副本已变化，请勿采用")
        return body
    except OSError: raise HTTPException(404, "制作副本不可读取，请核对原任务")
    finally:
        if directory is not None: os.close(directory)
        if root is not None: os.close(root)


async def preview(db, user, identity):
    ctx, _ = await context(db, user); row, _ = await _job(db, ctx, identity)
    if not row.output or row.status not in {"succeeded", "adopted"}: raise HTTPException(409, "制作结果尚不可读取")
    output = dict(row.output); revision = row.revision
    await db.rollback(); body = await asyncio.to_thread(_artifact_read, output)
    ctx, _ = await context(db, user); fresh, _ = await _job(db, ctx, identity)
    if fresh.revision != revision or fresh.output != output: raise HTTPException(409, "任务已变化，请重新读取")
    return body, output["mime_type"]


def _material_write(customer_id, key, suffix, body):
    if type(customer_id) is not int or customer_id < 1 or not images.IDENTITY.fullmatch(key) or suffix not in {"png", "mp4"}:
        raise HTTPException(422, "衍生素材无效")
    root = directory = fd = None
    name = "studio-"+key+"."+suffix
    try:
        root = images._open_directory(images.MATERIALS_ROOT)
        try: os.mkdir(str(customer_id), mode=0o700, dir_fd=root); os.fsync(root)
        except FileExistsError: pass
        directory = os.open(str(customer_id), os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW, dir_fd=root)
        fd = os.open(name, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600, dir_fd=directory)
        with os.fdopen(fd, "wb", closefd=False) as stream: stream.write(body); stream.flush(); os.fsync(fd)
        os.fsync(directory); return str(customer_id)+"/"+name, images._stat(os.fstat(fd))
    except OSError: raise HTTPException(503, "新素材保存结果待确认，请保留原请求编号")
    finally:
        if fd is not None: os.close(fd)
        if directory is not None: os.close(directory)
        if root is not None: os.close(root)


async def adopt(db, user, identity, value):
    ctx, _ = await context(db, user); data = value.model_dump(); request_id = media._key(data["request_id"])
    fp = media._hash({"job_id":identity, **data})
    prior = await _receipt(db, ctx, request_id, kind="adopt", fingerprint=fp)
    if prior: return await _result(db, ctx, prior)
    row, customer = await _job(db, ctx, identity)
    await context(db, user, customer.id, write=True)
    if row.revision != data["expected_revision"] or row.status != "succeeded" or not row.output or row.output["sha256"] != data["output_sha256"]:
        raise HTTPException(409, "制作结果或版本已变化，请重新查看后采用")
    await _fresh_sources(db, ctx, customer, row.snapshot, verify=True)
    frozen_output, frozen_snapshot, frozen_revision = dict(row.output), dict(row.snapshot), row.revision
    cid = customer.id
    await db.rollback()
    # Files are immutable new names and remain private even if the SQL unit is
    # rolled back. Never delete or reuse an unknown orphan from an earlier try.
    body = await asyncio.to_thread(_artifact_read, frozen_output)
    key = uuid4().hex; mime = frozen_output["mime_type"]; suffix = "png" if mime == "image/png" else "mp4"
    path, source_stat = await asyncio.to_thread(_material_write, cid, key, suffix, body)
    image_identity = uuid4().hex if suffix == "png" else None
    image_stat = await asyncio.to_thread(images._write_image, image_identity, body) if image_identity else None
    async with media._write(db):
        ctx, customer = await context(db, user, cid, write=True)
        prior = await _receipt(db, ctx, request_id, kind="adopt", fingerprint=fp)
        if prior: return await _result(db, ctx, prior)
        row, _ = await _job(db, ctx, identity, lock=True)
        if row.revision != frozen_revision or row.status != "succeeded" or row.output != frozen_output or row.snapshot != frozen_snapshot:
            raise HTTPException(409, "制作任务已变化，请先查看原结果")
        await _fresh_sources(db, ctx, customer, row.snapshot, verify=True)
        links = {x["linked_item_id"] for x in row.snapshot["proofs"]}
        linked = next(iter(links)) if len(links) == 1 else None
        rights = {x["rights_basis"] for x in row.snapshot["proofs"]}
        basis = "licensed" if "licensed" in rights else "client_provided" if "client_provided" in rights else "owned"
        stamp = media.now(); title = _text(data["title"])
        if not title: raise HTTPException(422, "请输入新素材标题")
        material = Material(user_id=str(ctx.identity), customer_id=cid, title=title, material_type="image" if image_identity else "video",
            visibility="team", platform="general", source_type="upload", file_name=title+"."+suffix,
            file_path=path, content_type=mime, file_size=len(body), linked_item_id=linked,
            linked_item_snapshot=row.snapshot["proofs"][0]["linked_item_snapshot"] if linked is not None else None,
            usage_status="unused", approval_status="pending", copyright_status=basis, is_favorite=False,
            notes="真实素材衍生；来源制作任务 "+row.id+"；源固定图片 "+",".join(x["id"] for x in row.snapshot["proofs"]),
            created_at=stamp, updated_at=stamp)
        db.add(material); await db.flush()
        fixed = None
        if image_identity:
            fixed_request = str(uuid5(NAMESPACE_URL, "t24-asset-studio-adopt:"+str(ctx.identity)+":"+row.id))
            source_fp = images.source_fingerprint(material)
            image_fp = media._hash({"customer_id":cid, "material_id":material.id, "source_sha256":frozen_output["sha256"],
                "source_fingerprint":source_fp, "image_sha256":frozen_output["sha256"], "rights_basis":basis})
            fixed = await images.prepare_locked(db, ctx, customer_id=cid, material_id=material.id, request_id=fixed_request,
                identity=image_identity, source_reference=source_fp, source_stat=source_stat, source_sha256=frozen_output["sha256"],
                canonical=body, width=frozen_output["width"], height=frozen_output["height"], image_hash=frozen_output["sha256"],
                image_stat=image_stat, fingerprint=image_fp, rights_basis=basis)
        # Same transaction as the new native material and native image. An
        # audit failure rolls everything back, never silently auto-approves it.
        db.add(CustomerRecordAudit(customer_id=cid, module="materials", entity_type="customer_materials", entity_id=material.id,
            actor_id=str(ctx.identity), actor_name=str(getattr(user, "name", "") or getattr(user, "email", "") or ctx.identity),
            action="create", before={}, after={"title":material.title, "material_type":material.material_type, "approval_status":"pending",
                "source_job_id":row.id, "output_sha256":frozen_output["sha256"], "source_image_ids":[p["id"] for p in row.snapshot["proofs"]]}))
        row.adoption = {"material_id":material.id, "image_id":fixed["id"] if fixed else None, "preview_path":fixed["preview_path"] if fixed else None}
        row.status = "adopted"; row.revision += 1; row.updated_at = stamp; row.message = "已另存为待确认的新素材，原图与月计划保持不变"
        receipt = _record(db, ctx, cid, request_id, "adopt", fp, row.id); await db.flush()
        return await _result(db, ctx, receipt)


async def _process_in_directory(spec=None, *, probe=False, work_directory):
    env = {"PATH":"/usr/bin:/bin", "LANG":"C.UTF-8", "OMP_NUM_THREADS":"1", "OPENBLAS_NUM_THREADS":"1", "MKL_NUM_THREADS":"1", "TMPDIR":work_directory}
    args = [sys.executable, "-I", "-B", str(RENDERER)] + (["--probe"] if probe else [])
    process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=env, start_new_session=True)
    async def exchange():
        payload = b"" if probe else json.dumps(spec, ensure_ascii=False, separators=(",", ":")).encode()
        if len(payload) > 72*1024*1024: raise HTTPException(413, "源图片总量过大")
        async def send():
            try: process.stdin.write(payload); await process.stdin.drain()
            finally: process.stdin.close()
        async def read(reader, maximum):
            chunks = []; total = 0
            while True:
                chunk = await reader.read(min(65536, maximum-total+1))
                if not chunk: return b"".join(chunks)
                total += len(chunk)
                if total > maximum: raise HTTPException(503, "制作输出超过安全范围")
                chunks.append(chunk)
        tasks = [asyncio.create_task(send()), asyncio.create_task(read(process.stdout, MAX_OUTPUT+2048)), asyncio.create_task(read(process.stderr, 1024))]
        try:
            _, output, errors = await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done(): task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        code = await process.wait()
        if code != 0:
            value = errors.decode("ascii", errors="ignore").strip()
            raise HTTPException(422, value if re.fullmatch("[A-Z_]{1,40}", value) else "LOCAL_RENDER_FAILED")
        return output
    try: return await asyncio.wait_for(exchange(), timeout=5 if probe else 35)
    finally:
        # Kill the session even if the renderer itself exited first: a CPU
        # limit could have killed it while its FFmpeg child was still alive.
        import signal
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        if process.returncode is None: await process.wait()


async def _process(spec=None, *, probe=False):
    # SIGKILL/CPU limits cannot run cleanup code in the child. The trusted
    # parent owns its complete private temporary tree and removes it only
    # after the renderer session has exited or has been killed and waited.
    with tempfile.TemporaryDirectory(prefix="t24-asset-process-", dir="/tmp") as directory:
        return await _process_in_directory(spec, probe=probe, work_directory=directory)


async def probe_runtime():
    global _runtime, _runtime_lock
    if _runtime_lock is None: _runtime_lock = asyncio.Lock()
    async with _runtime_lock:
        if _runtime is not None: return _runtime
        try:
            value = json.loads(await _process(probe=True))
            if set(value) != {"image", "video"} or type(value["image"]) is not bool or type(value["video"]) is not bool: raise ValueError()
            _runtime = {**value, "message":None if value["video"] else "本地短视频引擎尚未通过验收"}
        except Exception: _runtime = {"image":False, "video":False, "message":"本地图片制作引擎或授权字体不可用，请联系管理员"}
        return _runtime


def sessions_factory():
    from core.database import db_manager
    return db_manager.async_session_maker


async def run_tick(*, sessions=None):
    engine = await probe_runtime()
    if not engine["image"]: return {"stage":"engine_unavailable", "processed":0}
    sessions = sessions or sessions_factory()
    if sessions is None: return {"stage":"database_unavailable", "processed":0}
    async with sessions() as db:
        if not await tables_available(db, TABLES): return {"stage":"schema_not_ready", "processed":0}
        pending = await db.scalar(select(Job.id).where(Job.status.in_(["queued", "processing"])).limit(1))
        if pending is None: return {"stage":"idle", "processed":0}
        # Release the read snapshot before the short atomic claim. An empty
        # queue never takes SQLite's writer lock during the three-second poll.
        await db.rollback()
        async with media._write(db):
            stamp = media.now()
            processing = list((await db.scalars(select(Job).where(Job.status == "processing").with_for_update())).all())
            for row in processing:
                if row.lease_at is not None and _utc(row.lease_at) < stamp-timedelta(seconds=LEASE_SECONDS):
                    row.status = "unknown"; row.revision += 1; row.updated_at = stamp; row.message = "上次本地制作结果待确认，请先查看原任务，必要时明确重试"
                    row.error_code = "INTERRUPTED"; row.lease_token = None
                else: return {"stage":"busy", "processed":0}
            row = await db.scalar(select(Job).where(Job.status == "queued").order_by(Job.created_at, Job.id).limit(1).with_for_update())
            if row is None: return {"stage":"idle", "processed":0}
            token = uuid4().hex; row.status = "processing"; row.revision += 1; row.attempt += 1; row.lease_token = token
            row.lease_at = stamp; row.updated_at = stamp; row.message = "正在使用已选真实照片制作私有预览"
            identity, owner_id, customer_id, claimed_revision, snapshot = row.id, row.owner_id, row.customer_id, row.revision, dict(row.snapshot)
        # There is no SQL transaction or content lock across CPU/subprocess I/O.
        try:
            employee = await db.get(Employees, owner_id, populate_existing=True)
            user = SimpleNamespace(id=str(owner_id), role=employee.role, name=employee.name) if employee else None
            if user is None: raise HTTPException(403, "OWNER_INACTIVE")
            ctx, customer = await context(db, user, customer_id, write=True)
            sources = await _fresh_sources(db, ctx, customer, snapshot, verify=True)
            frozen = [SimpleNamespace(file_key=x.file_key, byte_size=x.byte_size, image_sha256=x.image_sha256, width=x.width, height=x.height) for x in sources]
            await db.rollback()
            bodies = [await asyncio.to_thread(images._image_bytes, x) for x in frozen]
            rendered = await _process({"recipe":snapshot["recipe"], "profile":snapshot["profile"], "images":[base64.b64encode(x).decode() for x in bodies]})
            header, body = rendered.split(b"\n", 1); metadata = json.loads(header)
            from services.media_asset_renderer import SIZES
            width, height = ((frozen[0].width, frozen[0].height) if snapshot["recipe"]["kind"] == "enhance"
                else SIZES[snapshot["recipe"]["format"]])
            mime = "video/mp4" if snapshot["recipe"]["kind"] == "video" else "image/png"
            if set(metadata) != {"mime_type", "width", "height", "duration_seconds"} or metadata["mime_type"] != mime or (metadata["width"], metadata["height"]) != (width, height):
                raise HTTPException(422, "INVALID_RENDER_OUTPUT")
            if mime == "image/png":
                body, w, h = await asyncio.to_thread(images.canonical_png, body)
                if (w, h) != (width, height) or metadata["duration_seconds"] is not None: raise HTTPException(422, "INVALID_RENDER_OUTPUT")
            elif not (len(body) <= MAX_OUTPUT and body[4:8] == b"ftyp" and metadata["duration_seconds"] == len(bodies)*3):
                raise HTTPException(422, "INVALID_RENDER_OUTPUT")
            key = uuid4().hex; signature = await asyncio.to_thread(_artifact_write, key, "png" if mime == "image/png" else "mp4", body)
            output = {**metadata, "sha256":hashlib.sha256(body).hexdigest(), "byte_size":len(body), "file_key":key, "file_stat":signature}
            async with media._write(db):
                ctx, customer = await context(db, user, customer_id, write=True)
                current, _ = await _job(db, ctx, identity, lock=True)
                if current.status != "processing" or current.lease_token != token or current.revision != claimed_revision or current.snapshot != snapshot:
                    return {"stage":"superseded", "processed":1}
                await _fresh_sources(db, ctx, customer, snapshot, verify=True)
                current.output = output; current.status = "succeeded"; current.revision += 1; current.lease_token = None
                current.updated_at = media.now(); current.error_code = None; current.message = "私有制作完成，请检查真实内容；采用不会发布"
            return {"stage":"succeeded", "processed":1, "job_id":identity}
        except asyncio.CancelledError: raise
        except Exception as error:
            await db.rollback()
            async with media._write(db):
                current = await db.get(Job, identity, populate_existing=True)
                if current and current.status == "processing" and current.lease_token == token and current.revision == claimed_revision:
                    detail = str(error.detail) if isinstance(error, HTTPException) else "LOCAL_RENDER_FAILED"
                    code = detail if re.fullmatch("[A-Z_]{1,40}", detail) else "SOURCE_OR_ACCESS_CHANGED"
                    current.status = "failed"; current.revision += 1; current.lease_token = None; current.error_code = code; current.updated_at = media.now()
                    current.message = "文字过长或字体不支持，请缩短文案后新建任务" if code in {"TEXT_DOES_NOT_FIT", "UNSUPPORTED_GLYPH"} else "本地制作未完成，请核对素材、合作状态与制作引擎后再重试"
            return {"stage":"failed", "processed":1, "job_id":identity}


async def _loop():
    while True:
        try: await run_tick()
        except asyncio.CancelledError: raise
        except Exception: pass  # No private pixels, copy, DB or provider data in logs.
        await asyncio.sleep(3)


def start_worker():
    global _worker
    if any(os.getenv(k, "").lower() in {"test", "testing"} for k in ("APP_ENV", "ENVIRONMENT", "ENV")):
        return None
    if os.getenv("T24_MEDIA_ASSET_WORKER_ENABLED", "true").lower() != "true": return None
    if _worker is None or _worker.done(): _worker = asyncio.create_task(_loop())
    return _worker


async def stop_worker(task):
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError): await task
