"""Evidence stays behind the same per-draft authorization as its document."""

import hashlib
import re
from datetime import datetime, timezone

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from models.finance_entry_attachments import FinanceEntryAttachment
from schemas.auth import UserResponse

MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_DRAFT_BYTES = 10 * 1024 * 1024
MAX_DRAFT_FILES = 12


def evidence_media_type(content: bytes) -> str:
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 4 and content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    raise HTTPException(status_code=422, detail="凭据仅支持 PDF、PNG、JPEG 或 WebP 文件")


def safe_evidence_filename(filename: str | None, media_type: str) -> str:
    name = re.split(r"[/\\]", str(filename or "凭据"))[-1]
    name = re.sub(r'[\x00-\x1f\x7f"<>:|?*]', "_", name).strip(" .") or "凭据"
    suffix = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[media_type]
    # The actual type controls the extension; an uploaded HTML filename is never served as HTML.
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return stem[:160] + suffix


def attachment_meta(item: FinanceEntryAttachment) -> dict:
    return {"id": item.id, "filename": item.filename, "media_type": item.media_type,
            "byte_size": item.byte_size, "sha256": item.sha256,
            "created_at": item.created_at.isoformat()}


async def has_active_attachment(db: AsyncSession, draft_id: int) -> bool:
    return bool(await db.scalar(select(FinanceEntryAttachment.id).where(
        FinanceEntryAttachment.draft_id == draft_id,
        FinanceEntryAttachment.removed_at.is_(None)).limit(1)))


async def list_attachments(db: AsyncSession, user: UserResponse, draft_id: int) -> dict:
    from services.finance_entry_drafts import authorize_draft
    draft = await authorize_draft(db, user, draft_id)
    rows = (await db.scalars(select(FinanceEntryAttachment).options(defer(FinanceEntryAttachment.content)).where(
        FinanceEntryAttachment.draft_id == draft_id,
        FinanceEntryAttachment.removed_at.is_(None)).order_by(FinanceEntryAttachment.id))).all()
    return {"items": [attachment_meta(item) for item in rows], "draft_revision": draft.revision}


async def read_attachment(db: AsyncSession, user: UserResponse, draft_id: int, attachment_id: int):
    from services.finance_entry_drafts import authorize_draft
    await authorize_draft(db, user, draft_id)
    item = await db.scalar(select(FinanceEntryAttachment).where(
        FinanceEntryAttachment.id == attachment_id,
        FinanceEntryAttachment.draft_id == draft_id,
        FinanceEntryAttachment.removed_at.is_(None)))
    if item is None:
        raise HTTPException(status_code=404, detail="凭据不存在或不可访问")
    return item


async def add_attachment(db: AsyncSession, user: UserResponse, draft_id: int,
                         expected_revision: int, file: UploadFile) -> dict:
    from services.finance_entry_drafts import append_audit, authorize_draft, claim_draft
    # Reject unauthorized requests before reading file data into application memory.
    await authorize_draft(db, user, draft_id, for_edit=True)
    content = await file.read(MAX_FILE_BYTES + 1)
    if not content or len(content) > MAX_FILE_BYTES:
        raise HTTPException(status_code=422, detail="单个凭据不能为空且不能超过 4 MB")
    media_type = evidence_media_type(content)
    digest = hashlib.sha256(content).hexdigest()
    try:
        draft = await claim_draft(db, user, draft_id, expected_revision, for_edit=True)
        rows = (await db.scalars(select(FinanceEntryAttachment).options(defer(FinanceEntryAttachment.content)).where(
            FinanceEntryAttachment.draft_id == draft_id))).all()
        same = next((item for item in rows if item.sha256 == digest and item.removed_at is None), None)
        if same is not None:
            # The revision claim is rolled back for a duplicate upload.
            metadata = attachment_meta(same)
            await db.rollback()
            current = await authorize_draft(db, user, draft_id)
            return {"item": metadata, "draft_revision": current.revision}
        if len(rows) >= MAX_DRAFT_FILES or sum(item.byte_size for item in rows) + len(content) > MAX_DRAFT_BYTES:
            raise HTTPException(status_code=422, detail="每张草稿最多保留 12 份、合计 10 MB 凭据；移除记录仍保留审计")
        item = FinanceEntryAttachment(draft_id=draft_id, uploaded_by_id=int(user.id),
            filename=safe_evidence_filename(file.filename, media_type), media_type=media_type,
            byte_size=len(content), sha256=digest, content=content, created_at=datetime.now(timezone.utc))
        db.add(item)
        await db.flush()
        await append_audit(db, user, draft, "attachment_added", reason=f"attachment:{item.id}:{digest}")
        result = {"item": attachment_meta(item), "draft_revision": draft.revision}
        await db.commit()
        return result
    except BaseException:
        await db.rollback()
        raise


async def remove_attachment(db: AsyncSession, user: UserResponse, draft_id: int,
                            attachment_id: int, expected_revision: int) -> dict:
    from services.finance_entry_drafts import append_audit, claim_draft
    try:
        draft = await claim_draft(db, user, draft_id, expected_revision, for_edit=True)
        item = await read_attachment(db, user, draft_id, attachment_id)
        item.removed_at = datetime.now(timezone.utc)
        item.removed_by_id = int(user.id)
        await append_audit(db, user, draft, "attachment_removed", reason=f"attachment:{item.id}:{item.sha256}")
        result = {"item": attachment_meta(item), "draft_revision": draft.revision}
        await db.commit()
        return result
    except BaseException:
        await db.rollback()
        raise
