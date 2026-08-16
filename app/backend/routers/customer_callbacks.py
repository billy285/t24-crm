import json
import logging
from typing import List, Optional

from datetime import datetime, date, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from services.customer_callbacks import Customer_callbacksService
from services.customer_scope import ensure_callback_customer_access
from services.role_permissions import normalized_role, require_button_permission

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/customer_callbacks", tags=["customer_callbacks"], dependencies=[Depends(get_current_user)])
CALLBACK_ROLES = {"admin", "super_admin", "ops", "sales", "sales_manager"}
CALLBACK_SERVER_OWNED_AUDIT_FIELDS = {
    "created_by_employee_id",
    "created_by_employee_name",
    "created_at",
    "updated_at",
    "completed_by_employee_id",
    "completed_by_employee_name",
    "completed_at",
}


def _require_callback_role(current_user: UserResponse) -> None:
    if normalized_role(current_user) not in CALLBACK_ROLES:
        raise HTTPException(status_code=403, detail="Customer callback access required")


async def _require_callback_mutation(
    db: AsyncSession,
    current_user: UserResponse,
    permission: str,
) -> None:
    _require_callback_role(current_user)
    await require_button_permission(db, current_user, permission, admin_override=True)


async def _get_scoped_callback(
    service: Customer_callbacksService,
    callback_id: int,
    current_user: UserResponse,
):
    callback = await service.get_by_id(callback_id, scope_user=current_user)
    if not callback:
        raise HTTPException(status_code=404, detail="Customer_callback not found")
    return callback


def _employee_identity(current_user: UserResponse) -> tuple[Optional[int], str]:
    try:
        employee_id = int(current_user.id)
    except (TypeError, ValueError):
        employee_id = None
    return employee_id, current_user.name or current_user.email or ""


def _apply_completion_audit(data: dict, current_user: UserResponse, *, creating: bool = False) -> dict:
    employee_id, employee_name = _employee_identity(current_user)
    # Creation/completion identities and timestamps are authoritative server
    # metadata. Strip every client-supplied value before deriving them from the
    # authenticated user and the requested business status.
    audited = {
        key: value
        for key, value in data.items()
        if key not in CALLBACK_SERVER_OWNED_AUDIT_FIELDS
    }
    now = datetime.now(timezone.utc)
    if creating:
        audited["created_by_employee_id"] = employee_id
        audited["created_by_employee_name"] = employee_name
        audited["created_at"] = now
    audited["updated_at"] = now

    if audited.get("status") == "completed":
        audited["completed_by_employee_id"] = employee_id
        audited["completed_by_employee_name"] = employee_name
        audited["completed_at"] = now
    elif "status" in audited:
        audited["completed_by_employee_id"] = None
        audited["completed_by_employee_name"] = None
        audited["completed_at"] = None
    else:
        audited.pop("completed_by_employee_id", None)
        audited.pop("completed_by_employee_name", None)
        audited.pop("completed_at", None)
    return audited


# ---------- Pydantic Schemas ----------
class Customer_callbacksData(BaseModel):
    """Entity data schema (for create/update)"""
    customer_id: int
    employee_id: Optional[int] = None
    employee_name: Optional[str] = None
    created_by_employee_id: Optional[int] = None
    created_by_employee_name: Optional[str] = None
    completed_by_employee_id: Optional[int] = None
    completed_by_employee_name: Optional[str] = None
    completed_at: Optional[datetime] = None
    callback_date: datetime
    callback_type: Optional[str] = None
    status: Optional[str] = None
    content: Optional[str] = None
    result: Optional[str] = None
    next_callback_date: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Customer_callbacksUpdateData(BaseModel):
    """Update entity data (partial updates allowed)"""
    customer_id: Optional[int] = None
    employee_id: Optional[int] = None
    employee_name: Optional[str] = None
    created_by_employee_id: Optional[int] = None
    created_by_employee_name: Optional[str] = None
    completed_by_employee_id: Optional[int] = None
    completed_by_employee_name: Optional[str] = None
    completed_at: Optional[datetime] = None
    callback_date: Optional[datetime] = None
    callback_type: Optional[str] = None
    status: Optional[str] = None
    content: Optional[str] = None
    result: Optional[str] = None
    next_callback_date: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Customer_callbacksResponse(BaseModel):
    """Entity response schema"""
    id: int
    customer_id: int
    employee_id: Optional[int] = None
    employee_name: Optional[str] = None
    created_by_employee_id: Optional[int] = None
    created_by_employee_name: Optional[str] = None
    completed_by_employee_id: Optional[int] = None
    completed_by_employee_name: Optional[str] = None
    completed_at: Optional[datetime] = None
    callback_date: Optional[datetime] = None
    callback_type: Optional[str] = None
    status: Optional[str] = None
    content: Optional[str] = None
    result: Optional[str] = None
    next_callback_date: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class Customer_callbacksListResponse(BaseModel):
    """List response schema"""
    items: List[Customer_callbacksResponse]
    total: int
    skip: int
    limit: int


class Customer_callbacksBatchCreateRequest(BaseModel):
    """Batch create request"""
    items: List[Customer_callbacksData]


class Customer_callbacksBatchUpdateItem(BaseModel):
    """Batch update item"""
    id: int
    updates: Customer_callbacksUpdateData


class Customer_callbacksBatchUpdateRequest(BaseModel):
    """Batch update request"""
    items: List[Customer_callbacksBatchUpdateItem]


class Customer_callbacksBatchDeleteRequest(BaseModel):
    """Batch delete request"""
    ids: List[int]


# ---------- Routes ----------
@router.get("", response_model=Customer_callbacksListResponse)
async def query_customer_callbacks(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Query customer_callbacks with filtering, sorting, and pagination"""
    logger.debug(f"Querying customer_callbacks: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")

    service = Customer_callbacksService(db)
    try:
        _require_callback_role(current_user)
        query_dict = None
        if query:
            try:
                query_dict = json.loads(query)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid query JSON format")

        result = await service.get_list(
            skip=skip,
            limit=limit,
            query_dict=query_dict,
            sort=sort,
            scope_user=current_user,
        )
        logger.debug(f"Found {result['total']} customer_callbacks")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying customer_callbacks: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/all", response_model=Customer_callbacksListResponse)
async def query_customer_callbacks_all(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Query customer_callbacks without user limitation"""
    logger.debug(f"Querying all customer_callbacks: query={query}, sort={sort}, skip={skip}, limit={limit}")

    service = Customer_callbacksService(db)
    try:
        _require_callback_role(current_user)
        query_dict = None
        if query:
            try:
                query_dict = json.loads(query)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid query JSON format")

        result = await service.get_list(
            skip=skip,
            limit=limit,
            query_dict=query_dict,
            sort=sort,
            scope_user=current_user,
        )
        logger.debug(f"Found {result['total']} customer_callbacks")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying customer_callbacks: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{id}", response_model=Customer_callbacksResponse)
async def get_customer_callback(
    id: int,
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single customer_callback by ID"""
    logger.debug(f"Fetching customer_callback with id: {id}, fields={fields}")

    service = Customer_callbacksService(db)
    try:
        _require_callback_role(current_user)
        return await _get_scoped_callback(service, id, current_user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching customer_callback {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("", response_model=Customer_callbacksResponse, status_code=201)
async def create_customer_callback(
    data: Customer_callbacksData,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """Create a new customer_callback"""
    logger.debug(f"Creating new customer_callback with data: {data}")

    service = Customer_callbacksService(db)
    try:
        await _require_callback_mutation(db, current_user, "follow_up_create")
        await ensure_callback_customer_access(db, current_user, data.customer_id)
        result = await service.create(_apply_completion_audit(data.model_dump(), current_user, creating=True))
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create customer_callback")

        logger.info(f"Customer_callback created successfully with id: {result.id}")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error creating customer_callback: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating customer_callback: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/batch", response_model=List[Customer_callbacksResponse], status_code=201)
async def create_customer_callbacks_batch(
    request: Customer_callbacksBatchCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """Create multiple customer_callbacks in a single request"""
    logger.debug(f"Batch creating {len(request.items)} customer_callbacks")

    service = Customer_callbacksService(db)
    results = []

    try:
        await _require_callback_mutation(db, current_user, "follow_up_create")
        for item_data in request.items:
            await ensure_callback_customer_access(db, current_user, item_data.customer_id)
        for item_data in request.items:
            result = await service.create(_apply_completion_audit(item_data.model_dump(), current_user, creating=True))
            if result:
                results.append(result)

        logger.info(f"Batch created {len(results)} customer_callbacks successfully")
        return results
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch create: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch create failed: {str(e)}")


@router.put("/batch", response_model=List[Customer_callbacksResponse])
async def update_customer_callbacks_batch(
    request: Customer_callbacksBatchUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """Update multiple customer_callbacks in a single request"""
    logger.debug(f"Batch updating {len(request.items)} customer_callbacks")

    service = Customer_callbacksService(db)
    results = []

    try:
        await _require_callback_mutation(db, current_user, "follow_up_edit")
        for item in request.items:
            await _get_scoped_callback(service, item.id, current_user)
            if item.updates.customer_id is not None:
                await ensure_callback_customer_access(db, current_user, item.updates.customer_id)
        for item in request.items:
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            update_dict = _apply_completion_audit(update_dict, current_user)
            result = await service.update(item.id, update_dict, scope_user=current_user)
            if result:
                results.append(result)

        logger.info(f"Batch updated {len(results)} customer_callbacks successfully")
        return results
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")


@router.put("/{id}", response_model=Customer_callbacksResponse)
async def update_customer_callback(
    id: int,
    data: Customer_callbacksUpdateData,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """Update an existing customer_callback"""
    logger.debug(f"Updating customer_callback {id} with data: {data}")

    service = Customer_callbacksService(db)
    try:
        await _require_callback_mutation(db, current_user, "follow_up_edit")
        await _get_scoped_callback(service, id, current_user)
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        if update_dict.get("customer_id") is not None:
            await ensure_callback_customer_access(db, current_user, update_dict["customer_id"])
        update_dict = _apply_completion_audit(update_dict, current_user)
        result = await service.update(id, update_dict, scope_user=current_user)
        if not result:
            logger.warning(f"Customer_callback with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Customer_callback not found")

        logger.info(f"Customer_callback {id} updated successfully")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error updating customer_callback {id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating customer_callback {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/batch")
async def delete_customer_callbacks_batch(
    request: Customer_callbacksBatchDeleteRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple customer_callbacks by their IDs"""
    logger.debug(f"Batch deleting {len(request.ids)} customer_callbacks")

    service = Customer_callbacksService(db)
    deleted_count = 0

    try:
        await _require_callback_mutation(db, current_user, "follow_up_delete")
        for item_id in request.ids:
            await _get_scoped_callback(service, item_id, current_user)
        for item_id in request.ids:
            success = await service.delete(item_id, scope_user=current_user)
            if success:
                deleted_count += 1

        logger.info(f"Batch deleted {deleted_count} customer_callbacks successfully")
        return {"message": f"Successfully deleted {deleted_count} customer_callbacks", "deleted_count": deleted_count}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch delete: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


@router.delete("/{id}")
async def delete_customer_callback(
    id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single customer_callback by ID"""
    logger.debug(f"Deleting customer_callback with id: {id}")

    service = Customer_callbacksService(db)
    try:
        await _require_callback_mutation(db, current_user, "follow_up_delete")
        await _get_scoped_callback(service, id, current_user)
        success = await service.delete(id, scope_user=current_user)
        if not success:
            logger.warning(f"Customer_callback with id {id} not found for deletion")
            raise HTTPException(status_code=404, detail="Customer_callback not found")

        logger.info(f"Customer_callback {id} deleted successfully")
        return {"message": "Customer_callback deleted successfully", "id": id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting customer_callback {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
