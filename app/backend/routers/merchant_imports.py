from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from models.merchant_import_batches import MerchantImportBatch
from schemas.auth import UserResponse
from services.merchant_imports import (
    MAX_FILE_BYTES, batch_response, batch_scope, confirm_import, error_csv,
    get_batch, preview_import, revert_import,
)

router = APIRouter(prefix="/api/v1/merchant-imports", tags=["merchant-imports"])


@router.post("/preview")
async def preview(file: UploadFile = File(...), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    batch_scope(user)
    content = await file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(400, "文件超过 10MB，请拆分后上传")
    return await preview_import(db, user, file.filename or "", content)


@router.get("")
async def list_batches(limit: int = Query(10, ge=1, le=50), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    scope = batch_scope(user)
    query = select(MerchantImportBatch)
    if scope is not None:
        query = query.where(scope)
    batches = (await db.execute(query.order_by(MerchantImportBatch.created_at.desc(), MerchantImportBatch.id.desc()).limit(limit))).scalars().all()
    return {"items": [{key: value for key, value in batch_response(batch).items() if key != "rows"} for batch in batches]}


@router.get("/{batch_id}")
async def detail(batch_id: str, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return batch_response(await get_batch(db, user, batch_id))


@router.post("/{batch_id}/confirm")
async def confirm(batch_id: str, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await confirm_import(db, user, batch_id)


@router.post("/{batch_id}/revert")
async def revert(batch_id: str, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await revert_import(db, user, batch_id)


@router.get("/{batch_id}/errors.csv")
async def download_errors(batch_id: str, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    batch = await get_batch(db, user, batch_id)
    return Response(error_csv(batch), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="merchant-import-{batch.id}-issues.csv"'})
