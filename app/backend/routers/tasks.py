import json
import logging
from typing import List, Optional

from datetime import datetime, date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from services.tasks import TasksService

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/tasks", tags=["tasks"])


# ---------- Pydantic Schemas ----------
class TasksData(BaseModel):
    """Entity data schema (for create/update)"""
    title: str
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    assignee_id: Optional[int] = None
    assignee_name: Optional[str] = None
    collaborator_names: Optional[str] = None
    task_type: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[datetime] = None
    notes: Optional[str] = None
    attachment_link: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TasksUpdateData(BaseModel):
    """Update entity data (partial updates allowed)"""
    title: Optional[str] = None
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    assignee_id: Optional[int] = None
    assignee_name: Optional[str] = None
    collaborator_names: Optional[str] = None
    task_type: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[datetime] = None
    notes: Optional[str] = None
    attachment_link: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TasksResponse(BaseModel):
    """Entity response schema"""
    id: int
    title: str
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    assignee_id: Optional[int] = None
    assignee_name: Optional[str] = None
    collaborator_names: Optional[str] = None
    task_type: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[datetime] = None
    notes: Optional[str] = None
    attachment_link: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TasksListResponse(BaseModel):
    """List response schema"""
    items: List[TasksResponse]
    total: int
    skip: int
    limit: int


class TasksBatchCreateRequest(BaseModel):
    """Batch create request"""
    items: List[TasksData]


class TasksBatchUpdateItem(BaseModel):
    """Batch update item"""
    id: int
    updates: TasksUpdateData


class TasksBatchUpdateRequest(BaseModel):
    """Batch update request"""
    items: List[TasksBatchUpdateItem]


class TasksBatchDeleteRequest(BaseModel):
    """Batch delete request"""
    ids: List[int]


# ---------- Routes ----------
@router.get("", response_model=TasksListResponse)
async def query_taskss(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    """Query taskss with filtering, sorting, and pagination"""
    logger.debug(f"Querying taskss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")
    
    service = TasksService(db)
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
        logger.debug(f"Found {result['total']} taskss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying taskss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/all", response_model=TasksListResponse)
async def query_taskss_all(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    # Query taskss with filtering, sorting, and pagination without user limitation
    logger.debug(f"Querying taskss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")

    service = TasksService(db)
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
        logger.debug(f"Found {result['total']} taskss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying taskss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{id}", response_model=TasksResponse)
async def get_tasks(
    id: int,
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    """Get a single tasks by ID"""
    logger.debug(f"Fetching tasks with id: {id}, fields={fields}")
    
    service = TasksService(db)
    try:
        result = await service.get_by_id(id)
        if not result:
            logger.warning(f"Tasks with id {id} not found")
            raise HTTPException(status_code=404, detail="Tasks not found")
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching tasks {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("", response_model=TasksResponse, status_code=201)
async def create_tasks(
    data: TasksData,
    db: AsyncSession = Depends(get_db),
):
    """Create a new tasks"""
    logger.debug(f"Creating new tasks with data: {data}")
    
    service = TasksService(db)
    try:
        result = await service.create(data.model_dump())
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create tasks")
        
        logger.info(f"Tasks created successfully with id: {result.id}")
        return result
    except ValueError as e:
        logger.error(f"Validation error creating tasks: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating tasks: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/batch", response_model=List[TasksResponse], status_code=201)
async def create_taskss_batch(
    request: TasksBatchCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create multiple taskss in a single request"""
    logger.debug(f"Batch creating {len(request.items)} taskss")
    
    service = TasksService(db)
    results = []
    
    try:
        for item_data in request.items:
            result = await service.create(item_data.model_dump())
            if result:
                results.append(result)
        
        logger.info(f"Batch created {len(results)} taskss successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch create: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch create failed: {str(e)}")


@router.put("/batch", response_model=List[TasksResponse])
async def update_taskss_batch(
    request: TasksBatchUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update multiple taskss in a single request"""
    logger.debug(f"Batch updating {len(request.items)} taskss")
    
    service = TasksService(db)
    results = []
    
    try:
        for item in request.items:
            # Only include non-None values for partial updates
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            result = await service.update(item.id, update_dict)
            if result:
                results.append(result)
        
        logger.info(f"Batch updated {len(results)} taskss successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")


@router.put("/{id}", response_model=TasksResponse)
async def update_tasks(
    id: int,
    data: TasksUpdateData,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing tasks"""
    logger.debug(f"Updating tasks {id} with data: {data}")

    service = TasksService(db)
    try:
        # Only include non-None values for partial updates
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        result = await service.update(id, update_dict)
        if not result:
            logger.warning(f"Tasks with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Tasks not found")
        
        logger.info(f"Tasks {id} updated successfully")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error updating tasks {id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating tasks {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/batch")
async def delete_taskss_batch(
    request: TasksBatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple taskss by their IDs"""
    logger.debug(f"Batch deleting {len(request.ids)} taskss")
    
    service = TasksService(db)
    deleted_count = 0
    
    try:
        for item_id in request.ids:
            success = await service.delete(item_id)
            if success:
                deleted_count += 1
        
        logger.info(f"Batch deleted {deleted_count} taskss successfully")
        return {"message": f"Successfully deleted {deleted_count} taskss", "deleted_count": deleted_count}
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch delete: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


@router.delete("/{id}")
async def delete_tasks(
    id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a single tasks by ID"""
    logger.debug(f"Deleting tasks with id: {id}")
    
    service = TasksService(db)
    try:
        success = await service.delete(id)
        if not success:
            logger.warning(f"Tasks with id {id} not found for deletion")
            raise HTTPException(status_code=404, detail="Tasks not found")
        
        logger.info(f"Tasks {id} deleted successfully")
        return {"message": "Tasks deleted successfully", "id": id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting tasks {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")