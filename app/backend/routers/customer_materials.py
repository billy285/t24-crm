import json
import logging
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.database import get_db
from dependencies.auth import get_current_user
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from schemas.auth import UserResponse
from services.customer_materials import Customer_materialsService
from services.customers import CustomersService
from services.operation_logs import Operation_logsService
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/entities/customer_materials",
    tags=["customer_materials"],
    dependencies=[Depends(get_current_user)],
)

MATERIALS_ROOT = Path(__file__).resolve().parent.parent / "data" / "materials"
MAX_UPLOAD_SIZE = 30 * 1024 * 1024
ALLOWED_UPLOAD_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".txt",
    ".csv",
    ".mp4",
    ".mov",
}


class CustomerMaterialData(BaseModel):
    customer_id: int
    title: str
    material_type: str = "image"
    platform: Optional[str] = "general"
    source_type: Optional[str] = "external_link"
    file_name: Optional[str] = None
    file_path: Optional[str] = None
    file_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    usage_status: Optional[str] = "unused"
    approval_status: Optional[str] = "pending"
    copyright_status: Optional[str] = "owned"
    is_favorite: Optional[bool] = False
    used_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CustomerMaterialUpdateData(BaseModel):
    title: Optional[str] = None
    material_type: Optional[str] = None
    platform: Optional[str] = None
    source_type: Optional[str] = None
    file_name: Optional[str] = None
    file_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    usage_status: Optional[str] = None
    approval_status: Optional[str] = None
    copyright_status: Optional[str] = None
    is_favorite: Optional[bool] = None
    used_at: Optional[datetime] = None
    notes: Optional[str] = None
    updated_at: Optional[datetime] = None


class CustomerMaterialResponse(BaseModel):
    id: int
    user_id: Optional[str] = None
    customer_id: int
    title: str
    material_type: str
    platform: Optional[str] = None
    source_type: Optional[str] = None
    file_name: Optional[str] = None
    file_path: Optional[str] = None
    file_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    usage_status: Optional[str] = None
    approval_status: Optional[str] = None
    copyright_status: Optional[str] = None
    is_favorite: Optional[bool] = None
    used_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CustomerMaterialListResponse(BaseModel):
    items: List[CustomerMaterialResponse]
    total: int
    skip: int
    limit: int


def _parse_query(query: Optional[str]) -> Optional[dict]:
    if not query:
        return None
    try:
        parsed = json.loads(query)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid query JSON format")


async def _ensure_customer_access(customer_id: int, current_user: UserResponse, db: AsyncSession):
    customer = await CustomersService(db).get_by_id(customer_id, scope_user=current_user)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


def _safe_filename(filename: str) -> str:
    raw = Path(filename or "material").name
    stem = Path(raw).stem or "material"
    suffix = Path(raw).suffix.lower()
    safe_stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", stem).strip("._-") or "material"
    return f"{safe_stem}{suffix}"


def _material_path_from_record(file_path: Optional[str]) -> Optional[Path]:
    if not file_path:
        return None
    path = (MATERIALS_ROOT / file_path).resolve()
    try:
        path.relative_to(MATERIALS_ROOT.resolve())
    except ValueError:
        return None
    return path


async def _log_material_action(
    db: AsyncSession,
    *,
    current_user: UserResponse,
    customer_id: int,
    action_type: str,
    detail: str,
) -> None:
    try:
        await Operation_logsService(db).create(
            {
                "customer_id": customer_id,
                "action_type": action_type,
                "action_detail": detail,
                "operator_name": current_user.name or current_user.email or "系统",
                "ip_address": "",
                "created_at": datetime.utcnow(),
            },
            user_id=str(current_user.id),
        )
    except Exception as exc:  # pragma: no cover - log failure must not block business flow
        logger.warning("Failed to write customer material operation log: %s", exc)


@router.get("", response_model=CustomerMaterialListResponse)
async def query_customer_materials(
    query: str = Query(None),
    sort: str = Query("-created_at"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query_dict = _parse_query(query) or {}
    customer_id = query_dict.get("customer_id")
    if customer_id:
        await _ensure_customer_access(int(customer_id), current_user, db)
    elif current_user.role not in {"admin", "super_admin"}:
        query_dict["user_id"] = str(current_user.id)

    return await Customer_materialsService(db).get_list(
        skip=skip,
        limit=limit,
        query_dict=query_dict,
        sort=sort,
    )


@router.post("", response_model=CustomerMaterialResponse, status_code=201)
async def create_customer_material(
    data: CustomerMaterialData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_customer_access(data.customer_id, current_user, db)
    payload = data.model_dump()
    now = datetime.utcnow()
    payload["title"] = payload["title"].strip()
    if not payload["title"]:
        raise HTTPException(status_code=400, detail="素材名称不能为空")
    payload["created_at"] = payload.get("created_at") or now
    payload["updated_at"] = payload.get("updated_at") or now
    payload["source_type"] = payload.get("source_type") or "external_link"

    result = await Customer_materialsService(db).create(payload, user_id=str(current_user.id))
    await _log_material_action(
        db,
        current_user=current_user,
        customer_id=result.customer_id,
        action_type="create_material",
        detail=f"新增素材: {result.title}",
    )
    return result


@router.post("/upload", response_model=CustomerMaterialResponse, status_code=201)
async def upload_customer_material(
    customer_id: int = Form(...),
    title: str = Form(...),
    material_type: str = Form("image"),
    platform: str = Form("general"),
    usage_status: str = Form("unused"),
    approval_status: str = Form("pending"),
    copyright_status: str = Form("owned"),
    notes: Optional[str] = Form(None),
    thumbnail_url: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_customer_access(customer_id, current_user, db)

    safe_name = _safe_filename(file.filename or "material")
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail="不支持的文件类型")

    customer_dir = MATERIALS_ROOT / str(customer_id)
    customer_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:10]}_{safe_name}"
    target_path = customer_dir / stored_name
    file_size = 0

    try:
        with target_path.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > MAX_UPLOAD_SIZE:
                    output.close()
                    target_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=400, detail="文件不能超过 30MB")
                output.write(chunk)
    finally:
        await file.close()

    now = datetime.utcnow()
    payload = {
        "customer_id": customer_id,
        "title": title.strip() or safe_name,
        "material_type": material_type,
        "platform": platform,
        "source_type": "upload",
        "file_name": safe_name,
        "file_path": f"{customer_id}/{stored_name}",
        "file_url": None,
        "thumbnail_url": thumbnail_url,
        "content_type": file.content_type,
        "file_size": file_size,
        "usage_status": usage_status,
        "approval_status": approval_status,
        "copyright_status": copyright_status,
        "is_favorite": False,
        "notes": notes,
        "created_at": now,
        "updated_at": now,
    }

    result = await Customer_materialsService(db).create(payload, user_id=str(current_user.id))
    await _log_material_action(
        db,
        current_user=current_user,
        customer_id=customer_id,
        action_type="create_material",
        detail=f"上传素材: {result.title}",
    )
    return result


@router.put("/{material_id}", response_model=CustomerMaterialResponse)
async def update_customer_material(
    material_id: int,
    data: CustomerMaterialUpdateData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = Customer_materialsService(db)
    obj = await service.get_by_id(material_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Material not found")
    await _ensure_customer_access(obj.customer_id, current_user, db)

    payload = data.model_dump(exclude_unset=True)
    payload["updated_at"] = payload.get("updated_at") or datetime.utcnow()
    updated = await service.update(material_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="Material not found")

    await _log_material_action(
        db,
        current_user=current_user,
        customer_id=updated.customer_id,
        action_type="edit_material",
        detail=f"编辑素材: {updated.title}",
    )
    return updated


@router.delete("/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer_material(
    material_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = Customer_materialsService(db)
    obj = await service.get_by_id(material_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Material not found")
    await _ensure_customer_access(obj.customer_id, current_user, db)

    file_path = _material_path_from_record(obj.file_path)
    deleted = await service.delete(material_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Material not found")
    if file_path and file_path.exists():
        file_path.unlink(missing_ok=True)

    await _log_material_action(
        db,
        current_user=current_user,
        customer_id=obj.customer_id,
        action_type="delete_material",
        detail=f"删除素材: {obj.title}",
    )


@router.get("/{material_id}/download")
async def download_customer_material(
    material_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    obj = await Customer_materialsService(db).get_by_id(material_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Material not found")
    await _ensure_customer_access(obj.customer_id, current_user, db)

    file_path = _material_path_from_record(obj.file_path)
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="素材文件不存在")

    return FileResponse(
        file_path,
        media_type=obj.content_type or "application/octet-stream",
        filename=obj.file_name or file_path.name,
    )


@router.post("/{material_id}/duplicate", response_model=CustomerMaterialResponse, status_code=201)
async def duplicate_customer_material(
    material_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = Customer_materialsService(db)
    obj = await service.get_by_id(material_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Material not found")
    await _ensure_customer_access(obj.customer_id, current_user, db)

    file_path = None
    next_file_path = None
    if obj.file_path:
        file_path = _material_path_from_record(obj.file_path)
        if file_path and file_path.exists():
            next_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:10]}_{file_path.name}"
            next_path = file_path.parent / next_name
            shutil.copyfile(file_path, next_path)
            next_file_path = f"{obj.customer_id}/{next_name}"

    now = datetime.utcnow()
    payload = {
        "customer_id": obj.customer_id,
        "title": f"{obj.title} 副本",
        "material_type": obj.material_type,
        "platform": obj.platform,
        "source_type": obj.source_type,
        "file_name": obj.file_name,
        "file_path": next_file_path or obj.file_path,
        "file_url": obj.file_url,
        "thumbnail_url": obj.thumbnail_url,
        "content_type": obj.content_type,
        "file_size": obj.file_size,
        "usage_status": "unused",
        "approval_status": obj.approval_status,
        "copyright_status": obj.copyright_status,
        "is_favorite": False,
        "notes": obj.notes,
        "created_at": now,
        "updated_at": now,
    }
    duplicated = await service.create(payload, user_id=str(current_user.id))
    await _log_material_action(
        db,
        current_user=current_user,
        customer_id=obj.customer_id,
        action_type="create_material",
        detail=f"复制素材: {obj.title}",
    )
    return duplicated
