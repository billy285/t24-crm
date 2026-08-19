import json
import logging
from datetime import datetime
from typing import List, Optional


from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from services.service_progresses import Service_progressesService
from services.customer_scope import ensure_customer_access
from services.service_board_access import require_service_board_access
from models.service_tasks import Service_tasks

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/entities/service_progresses",
    tags=["service_progresses"],
    dependencies=[Depends(get_current_user)],
)


# ---------- Pydantic Schemas ----------
class Service_progressesData(BaseModel):
    """Entity data schema (for create/update)"""
    customer_id: int
    customer_name: Optional[str] = None
    service_type: Optional[str] = None
    service_stage: str
    progress_percent: Optional[int] = None
    sales_person: Optional[str] = None
    ops_person: Optional[str] = None
    design_person: Optional[str] = None
    package_name: Optional[str] = None
    package_platforms: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    service_start_date: Optional[str] = None
    service_end_date: Optional[str] = None
    last_update_time: Optional[str] = None
    last_update_person: Optional[str] = None
    last_work_summary: Optional[str] = None
    issue_status: Optional[str] = None
    issue_description: Optional[str] = None
    issue_found_date: Optional[str] = None
    issue_owner: Optional[str] = None
    issue_resolved: Optional[bool] = None
    issue_resolved_date: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None


class Service_progressesUpdateData(BaseModel):
    """Update entity data (partial updates allowed)"""
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    service_type: Optional[str] = None
    service_stage: Optional[str] = None
    progress_percent: Optional[int] = None
    sales_person: Optional[str] = None
    ops_person: Optional[str] = None
    design_person: Optional[str] = None
    package_name: Optional[str] = None
    package_platforms: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    service_start_date: Optional[str] = None
    service_end_date: Optional[str] = None
    last_update_time: Optional[str] = None
    last_update_person: Optional[str] = None
    last_work_summary: Optional[str] = None
    issue_status: Optional[str] = None
    issue_description: Optional[str] = None
    issue_found_date: Optional[str] = None
    issue_owner: Optional[str] = None
    issue_resolved: Optional[bool] = None
    issue_resolved_date: Optional[str] = None
    notes: Optional[str] = None
    user_id: Optional[str] = None
    created_at: Optional[str] = None


class Service_progressesResponse(BaseModel):
    """Entity response schema"""
    id: int
    customer_id: int
    customer_name: Optional[str] = None
    service_type: Optional[str] = None
    service_stage: str
    progress_percent: Optional[int] = None
    sales_person: Optional[str] = None
    ops_person: Optional[str] = None
    design_person: Optional[str] = None
    package_name: Optional[str] = None
    package_platforms: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    service_start_date: Optional[str] = None
    service_end_date: Optional[str] = None
    last_update_time: Optional[str] = None
    last_update_person: Optional[str] = None
    last_work_summary: Optional[str] = None
    issue_status: Optional[str] = None
    issue_description: Optional[str] = None
    issue_found_date: Optional[str] = None
    issue_owner: Optional[str] = None
    issue_resolved: Optional[bool] = None
    issue_resolved_date: Optional[str] = None
    notes: Optional[str] = None
    user_id: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class Service_progressesListResponse(BaseModel):
    """List response schema"""
    items: List[Service_progressesResponse]
    total: int
    skip: int
    limit: int


class Service_progressesBatchCreateRequest(BaseModel):
    """Batch create request"""
    items: List[Service_progressesData]


class Service_progressesBatchUpdateItem(BaseModel):
    """Batch update item"""
    id: int
    updates: Service_progressesUpdateData


class Service_progressesBatchUpdateRequest(BaseModel):
    """Batch update request"""
    items: List[Service_progressesBatchUpdateItem]


class Service_progressesBatchDeleteRequest(BaseModel):
    """Batch delete request"""
    ids: List[int]


SERVER_MANAGED_PROGRESS_FIELDS = {
    "customer_name",
    "user_id",
    "created_at",
    "last_update_time",
    "last_update_person",
}


def _operator_name(current_user: UserResponse) -> str:
    for field_name in ("name", "full_name", "email"):
        value = getattr(current_user, field_name, None)
        if value:
            return str(value)
    return "系统管理员"


def _trusted_customer_name(customer) -> str:
    return str(getattr(customer, "business_name", None) or getattr(customer, "name", None) or "")


def _progress_payload(data: BaseModel) -> dict:
    payload = data.model_dump(exclude_unset=True)
    for field_name in SERVER_MANAGED_PROGRESS_FIELDS:
        payload.pop(field_name, None)
    if "customer_id" in payload and payload["customer_id"] is None:
        raise HTTPException(status_code=400, detail="服务进度必须关联客户")
    percent = payload.get("progress_percent")
    if percent is not None and not 0 <= percent <= 100:
        raise HTTPException(status_code=400, detail="服务进度必须在 0 到 100 之间")
    return payload


async def _progress_has_tasks(db: AsyncSession, progress_id: int) -> bool:
    result = await db.execute(
        select(Service_tasks.id).where(Service_tasks.service_progress_id == progress_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _prepare_progress_update(
    db: AsyncSession,
    current_user: UserResponse,
    progress,
    data: Service_progressesUpdateData,
) -> dict:
    update_dict = _progress_payload(data)
    final_customer_id = update_dict.get("customer_id", progress.customer_id)
    customer = await ensure_customer_access(db, current_user, final_customer_id, write=True)
    if int(final_customer_id) != int(progress.customer_id) and await _progress_has_tasks(db, progress.id):
        raise HTTPException(status_code=409, detail="该服务进度仍有关联任务，不能更换客户")
    update_dict["customer_name"] = _trusted_customer_name(customer)
    update_dict["last_update_time"] = datetime.utcnow().isoformat()
    update_dict["last_update_person"] = _operator_name(current_user)
    return update_dict


# ---------- Routes ----------
@router.get("", response_model=Service_progressesListResponse)
async def query_service_progressess(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Query service_progressess with filtering, sorting, and pagination"""
    await require_service_board_access(db, current_user)
    logger.debug(f"Querying service_progressess: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")
    
    service = Service_progressesService(db)
    try:
        # Parse query JSON if provided
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
        logger.debug(f"Found {result['total']} service_progressess")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying service_progressess: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/all", response_model=Service_progressesListResponse)
async def query_service_progressess_all(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Query service_progressess with filtering, sorting, and pagination without user limitation
    await require_service_board_access(db, current_user)
    logger.debug(f"Querying service_progressess: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")

    service = Service_progressesService(db)
    try:
        # Parse query JSON if provided
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
        logger.debug(f"Found {result['total']} service_progressess")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying service_progressess: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{id}", response_model=Service_progressesResponse)
async def get_service_progresses(
    id: int,
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single service_progresses by ID"""
    await require_service_board_access(db, current_user)
    logger.debug(f"Fetching service_progresses with id: {id}, fields={fields}")
    
    service = Service_progressesService(db)
    try:
        result = await service.get_by_id(id, scope_user=current_user)
        if not result:
            logger.warning(f"Service_progresses with id {id} not found")
            raise HTTPException(status_code=404, detail="Service_progresses not found")
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching service_progresses {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("", response_model=Service_progressesResponse, status_code=201)
async def create_service_progresses(
    data: Service_progressesData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new service_progresses"""
    await require_service_board_access(db, current_user, "task_create")
    customer = await ensure_customer_access(db, current_user, data.customer_id, write=True)
    create_dict = _progress_payload(data)
    now = datetime.utcnow().isoformat()
    create_dict.update({
        "customer_name": _trusted_customer_name(customer),
        "created_at": now,
        "last_update_time": now,
        "last_update_person": _operator_name(current_user),
    })
    logger.debug("Creating service progress for customer_id=%s", data.customer_id)

    service = Service_progressesService(db)
    try:
        result = await service.create(create_dict, user_id=str(current_user.id))
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create service_progresses")
        
        logger.info(f"Service_progresses created successfully with id: {result.id}")
        return result
    except ValueError as e:
        logger.error(f"Validation error creating service_progresses: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating service_progresses: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/batch", response_model=List[Service_progressesResponse], status_code=201)
async def create_service_progressess_batch(
    request: Service_progressesBatchCreateRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create multiple service_progressess in a single request"""
    await require_service_board_access(db, current_user, "task_create")
    prepared_items = []
    for item_data in request.items:
        customer = await ensure_customer_access(db, current_user, item_data.customer_id, write=True)
        create_dict = _progress_payload(item_data)
        now = datetime.utcnow().isoformat()
        create_dict.update({
            "customer_name": _trusted_customer_name(customer),
            "created_at": now,
            "last_update_time": now,
            "last_update_person": _operator_name(current_user),
        })
        prepared_items.append(create_dict)
    logger.debug(f"Batch creating {len(request.items)} service_progressess")
    
    service = Service_progressesService(db)
    results = []
    
    try:
        for create_dict in prepared_items:
            result = await service.create(create_dict, user_id=str(current_user.id))
            if result:
                results.append(result)
        
        logger.info(f"Batch created {len(results)} service_progressess successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch create: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch create failed: {str(e)}")


@router.put("/batch", response_model=List[Service_progressesResponse])
async def update_service_progressess_batch(
    request: Service_progressesBatchUpdateRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update multiple service_progressess in a single request"""
    await require_service_board_access(db, current_user, "task_edit")
    logger.debug(f"Batch updating {len(request.items)} service_progressess")
    
    service = Service_progressesService(db)
    results = []
    prepared_items = []

    item_ids = [item.id for item in request.items]
    if len(item_ids) != len(set(item_ids)):
        raise HTTPException(status_code=400, detail="批量更新不能包含重复服务进度")

    for item in request.items:
        progress = await service.get_by_id(item.id, scope_user=current_user)
        if not progress:
            raise HTTPException(status_code=404, detail="Service_progresses not found")
        update_dict = await _prepare_progress_update(db, current_user, progress, item.updates)
        prepared_items.append((item.id, update_dict))
    
    try:
        for item_id, update_dict in prepared_items:
            result = await service.update(item_id, update_dict, scope_user=current_user)
            if result:
                results.append(result)
        
        logger.info(f"Batch updated {len(results)} service_progressess successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")


@router.put("/{id}", response_model=Service_progressesResponse)
async def update_service_progresses(
    id: int,
    data: Service_progressesUpdateData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing service_progresses"""
    await require_service_board_access(db, current_user, "task_edit")
    service = Service_progressesService(db)
    try:
        progress = await service.get_by_id(id, scope_user=current_user)
        if not progress:
            raise HTTPException(status_code=404, detail="Service_progresses not found")
        update_dict = await _prepare_progress_update(db, current_user, progress, data)
        logger.debug("Updating service progress id=%s customer_id=%s", id, progress.customer_id)
        result = await service.update(id, update_dict, scope_user=current_user)
        if not result:
            logger.warning(f"Service_progresses with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Service_progresses not found")
        
        logger.info(f"Service_progresses {id} updated successfully")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error updating service_progresses {id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating service_progresses {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/batch")
async def delete_service_progressess_batch(
    request: Service_progressesBatchDeleteRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple service_progressess by their IDs"""
    await require_service_board_access(db, current_user, "task_delete")
    logger.debug(f"Batch deleting {len(request.ids)} service_progressess")
    
    service = Service_progressesService(db)
    deleted_count = 0

    if len(request.ids) != len(set(request.ids)):
        raise HTTPException(status_code=400, detail="批量删除不能包含重复服务进度")

    for item_id in request.ids:
        if not await service.get_by_id(item_id, scope_user=current_user):
            raise HTTPException(status_code=404, detail="Service_progresses not found")
        if await _progress_has_tasks(db, item_id):
            raise HTTPException(status_code=409, detail="该服务进度仍有关联任务，不能删除")
    
    try:
        for item_id in request.ids:
            success = await service.delete(item_id, scope_user=current_user)
            if success:
                deleted_count += 1
        
        logger.info(f"Batch deleted {deleted_count} service_progressess successfully")
        return {"message": f"Successfully deleted {deleted_count} service_progressess", "deleted_count": deleted_count}
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch delete: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


@router.delete("/{id}")
async def delete_service_progresses(
    id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single service_progresses by ID"""
    await require_service_board_access(db, current_user, "task_delete")
    logger.debug(f"Deleting service_progresses with id: {id}")
    
    service = Service_progressesService(db)
    try:
        progress = await service.get_by_id(id, scope_user=current_user)
        if not progress:
            raise HTTPException(status_code=404, detail="Service_progresses not found")
        if await _progress_has_tasks(db, id):
            raise HTTPException(status_code=409, detail="该服务进度仍有关联任务，不能删除")
        success = await service.delete(id, scope_user=current_user)
        if not success:
            logger.warning(f"Service_progresses with id {id} not found for deletion")
            raise HTTPException(status_code=404, detail="Service_progresses not found")
        
        logger.info(f"Service_progresses {id} deleted successfully")
        return {"message": "Service_progresses deleted successfully", "id": id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting service_progresses {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
