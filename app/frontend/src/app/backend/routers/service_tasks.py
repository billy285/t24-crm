import json
import logging
from typing import List, Optional


from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from services.service_tasks import Service_tasksService

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/service_tasks", tags=["service_tasks"])


# ---------- Pydantic Schemas ----------
class Service_tasksData(BaseModel):
    """Entity data schema (for create/update)"""
    service_progress_id: int = None
    customer_id: int
    task_name: str
    task_type: str = None
    assignee_name: str = None
    priority: str = None
    status: str
    due_date: str = None
    completed_date: str = None
    notes: str = None
    user_id: str
    created_at: str = None


class Service_tasksUpdateData(BaseModel):
    """Update entity data (partial updates allowed)"""
    service_progress_id: Optional[int] = None
    customer_id: Optional[int] = None
    task_name: Optional[str] = None
    task_type: Optional[str] = None
    assignee_name: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[str] = None
    completed_date: Optional[str] = None
    notes: Optional[str] = None
    user_id: Optional[str] = None
    created_at: Optional[str] = None


class Service_tasksResponse(BaseModel):
    """Entity response schema"""
    id: int
    service_progress_id: Optional[int] = None
    customer_id: int
    task_name: str
    task_type: Optional[str] = None
    assignee_name: Optional[str] = None
    priority: Optional[str] = None
    status: str
    due_date: Optional[str] = None
    completed_date: Optional[str] = None
    notes: Optional[str] = None
    user_id: str
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class Service_tasksListResponse(BaseModel):
    """List response schema"""
    items: List[Service_tasksResponse]
    total: int
    skip: int
    limit: int


class Service_tasksBatchCreateRequest(BaseModel):
    """Batch create request"""
    items: List[Service_tasksData]


class Service_tasksBatchUpdateItem(BaseModel):
    """Batch update item"""
    id: int
    updates: Service_tasksUpdateData


class Service_tasksBatchUpdateRequest(BaseModel):
    """Batch update request"""
    items: List[Service_tasksBatchUpdateItem]


class Service_tasksBatchDeleteRequest(BaseModel):
    """Batch delete request"""
    ids: List[int]


# ---------- Routes ----------
@router.get("", response_model=Service_tasksListResponse)
async def query_service_taskss(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    """Query service_taskss with filtering, sorting, and pagination"""
    logger.debug(f"Querying service_taskss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")
    
    service = Service_tasksService(db)
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
        )
        logger.debug(f"Found {result['total']} service_taskss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying service_taskss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/all", response_model=Service_tasksListResponse)
async def query_service_taskss_all(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    # Query service_taskss with filtering, sorting, and pagination without user limitation
    logger.debug(f"Querying service_taskss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")

    service = Service_tasksService(db)
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
            sort=sort
        )
        logger.debug(f"Found {result['total']} service_taskss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying service_taskss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{id}", response_model=Service_tasksResponse)
async def get_service_tasks(
    id: int,
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    """Get a single service_tasks by ID"""
    logger.debug(f"Fetching service_tasks with id: {id}, fields={fields}")
    
    service = Service_tasksService(db)
    try:
        result = await service.get_by_id(id)
        if not result:
            logger.warning(f"Service_tasks with id {id} not found")
            raise HTTPException(status_code=404, detail="Service_tasks not found")
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching service_tasks {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("", response_model=Service_tasksResponse, status_code=201)
async def create_service_tasks(
    data: Service_tasksData,
    db: AsyncSession = Depends(get_db),
):
    """Create a new service_tasks"""
    logger.debug(f"Creating new service_tasks with data: {data}")
    
    service = Service_tasksService(db)
    try:
        result = await service.create(data.model_dump())
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create service_tasks")
        
        logger.info(f"Service_tasks created successfully with id: {result.id}")
        return result
    except ValueError as e:
        logger.error(f"Validation error creating service_tasks: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating service_tasks: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/batch", response_model=List[Service_tasksResponse], status_code=201)
async def create_service_taskss_batch(
    request: Service_tasksBatchCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create multiple service_taskss in a single request"""
    logger.debug(f"Batch creating {len(request.items)} service_taskss")
    
    service = Service_tasksService(db)
    results = []
    
    try:
        for item_data in request.items:
            result = await service.create(item_data.model_dump())
            if result:
                results.append(result)
        
        logger.info(f"Batch created {len(results)} service_taskss successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch create: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch create failed: {str(e)}")


@router.put("/batch", response_model=List[Service_tasksResponse])
async def update_service_taskss_batch(
    request: Service_tasksBatchUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update multiple service_taskss in a single request"""
    logger.debug(f"Batch updating {len(request.items)} service_taskss")
    
    service = Service_tasksService(db)
    results = []
    
    try:
        for item in request.items:
            # Only include non-None values for partial updates
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            result = await service.update(item.id, update_dict)
            if result:
                results.append(result)
        
        logger.info(f"Batch updated {len(results)} service_taskss successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")


@router.put("/{id}", response_model=Service_tasksResponse)
async def update_service_tasks(
    id: int,
    data: Service_tasksUpdateData,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing service_tasks"""
    logger.debug(f"Updating service_tasks {id} with data: {data}")

    service = Service_tasksService(db)
    try:
        # Only include non-None values for partial updates
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        result = await service.update(id, update_dict)
        if not result:
            logger.warning(f"Service_tasks with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Service_tasks not found")
        
        logger.info(f"Service_tasks {id} updated successfully")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error updating service_tasks {id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating service_tasks {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/batch")
async def delete_service_taskss_batch(
    request: Service_tasksBatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple service_taskss by their IDs"""
    logger.debug(f"Batch deleting {len(request.ids)} service_taskss")
    
    service = Service_tasksService(db)
    deleted_count = 0
    
    try:
        for item_id in request.ids:
            success = await service.delete(item_id)
            if success:
                deleted_count += 1
        
        logger.info(f"Batch deleted {deleted_count} service_taskss successfully")
        return {"message": f"Successfully deleted {deleted_count} service_taskss", "deleted_count": deleted_count}
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch delete: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


@router.delete("/{id}")
async def delete_service_tasks(
    id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a single service_tasks by ID"""
    logger.debug(f"Deleting service_tasks with id: {id}")
    
    service = Service_tasksService(db)
    try:
        success = await service.delete(id)
        if not success:
            logger.warning(f"Service_tasks with id {id} not found for deletion")
            raise HTTPException(status_code=404, detail="Service_tasks not found")
        
        logger.info(f"Service_tasks {id} deleted successfully")
        return {"message": "Service_tasks deleted successfully", "id": id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting service_tasks {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")