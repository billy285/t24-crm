"""Authenticated evidence endpoints; no public file or administrator storage access."""

from urllib.parse import quote

from core.database import get_db
from dependencies.auth import get_current_user
from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from schemas.auth import UserResponse
from services import finance_entry_attachments as evidence
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/finance-entry-drafts", tags=["finance-entry-evidence"])


@router.get("/{draft_id}/attachments")
async def list_evidence(draft_id: int, response: Response, db: AsyncSession = Depends(get_db),
                        current_user: UserResponse = Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    return await evidence.list_attachments(db, current_user, draft_id)


@router.post("/{draft_id}/attachments")
async def upload_evidence(draft_id: int, response: Response, expected_revision: int = Form(..., ge=1),
                          file: UploadFile = File(...), db: AsyncSession = Depends(get_db),
                          current_user: UserResponse = Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return await evidence.add_attachment(db, current_user, draft_id, expected_revision, file)
    finally:
        await file.close()


@router.get("/{draft_id}/attachments/{attachment_id}")
async def download_evidence(draft_id: int, attachment_id: int, db: AsyncSession = Depends(get_db),
                            current_user: UserResponse = Depends(get_current_user)):
    item = await evidence.read_attachment(db, current_user, draft_id, attachment_id)
    return Response(content=item.content, media_type=item.media_type, headers={
        "Cache-Control": "private, no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Content-Disposition": f"attachment; filename=\"evidence-{item.id}\"; filename*=UTF-8''{quote(item.filename)}",
    })


@router.delete("/{draft_id}/attachments/{attachment_id}")
async def remove_evidence(draft_id: int, attachment_id: int, response: Response,
                          expected_revision: int = Query(..., ge=1), db: AsyncSession = Depends(get_db),
                          current_user: UserResponse = Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    return await evidence.remove_attachment(db, current_user, draft_id, attachment_id, expected_revision)
