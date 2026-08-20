import json
import logging
from datetime import datetime
from typing import List, Optional

from core.database import get_db
from dependencies.auth import get_current_user
from fastapi import APIRouter, Depends, HTTPException, Query, status
from models.customer_materials import Customer_materials
from pydantic import BaseModel
from schemas.auth import UserResponse
from services.customer_menu_items import Customer_menu_itemsService
from services.customers import CustomersService
from services.customer_scope import ensure_customer_access as ensure_scoped_customer_access
from services.operation_logs import Operation_logsService
from services.role_permissions import normalized_role, require_any_page_permission, require_button_permission
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/entities/customer_menu_items",
    tags=["customer_menu_items"],
    dependencies=[Depends(get_current_user)],
)
CUSTOMER_WORKSPACE_PAGES = {"/customers", "/service-board"}


async def _require_item_read(current_user: UserResponse, db: AsyncSession) -> None:
    await require_any_page_permission(db, current_user, CUSTOMER_WORKSPACE_PAGES)


async def _require_item_write(
    current_user: UserResponse,
    db: AsyncSession,
    permission: str,
    *,
    admin_override: bool = False,
) -> None:
    await _require_item_read(current_user, db)
    await require_button_permission(db, current_user, permission, admin_override=admin_override)


class CustomerMenuItemData(BaseModel):
    customer_id: int
    name: str
    item_type: Optional[str] = "dish"
    category: Optional[str] = None
    price: Optional[str] = None
    selling_points: Optional[str] = None
    suitable_platforms: Optional[str] = None
    is_featured: Optional[bool] = False
    status: Optional[str] = "active"
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CustomerMenuItemUpdateData(BaseModel):
    name: Optional[str] = None
    item_type: Optional[str] = None
    category: Optional[str] = None
    price: Optional[str] = None
    selling_points: Optional[str] = None
    suitable_platforms: Optional[str] = None
    is_featured: Optional[bool] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    updated_at: Optional[datetime] = None


class CustomerMenuItemResponse(BaseModel):
    id: int
    user_id: Optional[str] = None
    customer_id: int
    name: str
    item_type: Optional[str] = None
    category: Optional[str] = None
    price: Optional[str] = None
    selling_points: Optional[str] = None
    suitable_platforms: Optional[str] = None
    is_featured: Optional[bool] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CustomerMenuItemListResponse(BaseModel):
    items: List[CustomerMenuItemResponse]
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


async def _ensure_customer_access(customer_id: int, current_user: UserResponse, db: AsyncSession, *, write: bool = False):
    return await ensure_scoped_customer_access(db, current_user, customer_id, write=write)


def _clean_item_payload(payload: dict) -> dict:
    if "name" in payload and payload["name"] is not None:
        payload["name"] = payload["name"].strip()
        if not payload["name"]:
            raise HTTPException(status_code=400, detail="项目名称不能为空")
    if "suitable_platforms" in payload and isinstance(payload["suitable_platforms"], str):
        payload["suitable_platforms"] = payload["suitable_platforms"].strip()
    return payload


async def _log_item_action(
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
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to write customer menu item operation log: %s", exc)


@router.get("", response_model=CustomerMenuItemListResponse)
async def query_customer_menu_items(
    query: Optional[str] = Query(None),
    sort: Optional[str] = Query("-updated_at"),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_item_read(current_user, db)
    query_dict = _parse_query(query)
    customer_id = query_dict.get("customer_id") if query_dict else None
    if customer_id:
        await _ensure_customer_access(int(customer_id), current_user, db)
    elif normalized_role(current_user) not in {"admin", "super_admin"}:
        raise HTTPException(status_code=400, detail="customer_id query is required")
    return await Customer_menu_itemsService(db).get_list(skip=skip, limit=limit, query_dict=query_dict, sort=sort)


@router.post("", response_model=CustomerMenuItemResponse, status_code=201)
async def create_customer_menu_item(
    data: CustomerMenuItemData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_item_write(current_user, db, "task_create")
    await _ensure_customer_access(data.customer_id, current_user, db, write=True)
    now = datetime.utcnow()
    payload = _clean_item_payload(data.model_dump())
    payload["created_at"] = payload.get("created_at") or now
    payload["updated_at"] = payload.get("updated_at") or now
    payload["status"] = payload.get("status") or "active"
    payload["item_type"] = payload.get("item_type") or "dish"

    result = await Customer_menu_itemsService(db).create(payload, user_id=str(current_user.id))
    await _log_item_action(
        db,
        current_user=current_user,
        customer_id=result.customer_id,
        action_type="create_menu_item",
        detail=f"新增菜单/服务项目: {result.name}",
    )
    return result


@router.put("/{item_id}", response_model=CustomerMenuItemResponse)
async def update_customer_menu_item(
    item_id: int,
    data: CustomerMenuItemUpdateData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_item_write(current_user, db, "task_edit")
    service = Customer_menu_itemsService(db)
    obj = await service.get_by_id(item_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Menu item not found")
    await _ensure_customer_access(obj.customer_id, current_user, db, write=True)

    payload = _clean_item_payload(data.model_dump(exclude_unset=True))
    payload["updated_at"] = payload.get("updated_at") or datetime.utcnow()
    updated = await service.update(item_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="Menu item not found")

    await _log_item_action(
        db,
        current_user=current_user,
        customer_id=updated.customer_id,
        action_type="edit_menu_item",
        detail=f"编辑菜单/服务项目: {updated.name}",
    )
    return updated


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer_menu_item(
    item_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_item_write(current_user, db, "task_delete", admin_override=True)
    service = Customer_menu_itemsService(db)
    obj = await service.get_by_id(item_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Menu item not found")
    await _ensure_customer_access(obj.customer_id, current_user, db, write=True)

    await db.execute(
        update(Customer_materials)
        .where(Customer_materials.customer_id == obj.customer_id)
        .where(Customer_materials.linked_item_id == obj.id)
        .values(linked_item_id=None, linked_item_snapshot=obj.name, updated_at=datetime.utcnow())
    )
    deleted = await service.delete(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Menu item not found")

    await _log_item_action(
        db,
        current_user=current_user,
        customer_id=obj.customer_id,
        action_type="delete_menu_item",
        detail=f"删除菜单/服务项目: {obj.name}",
    )
