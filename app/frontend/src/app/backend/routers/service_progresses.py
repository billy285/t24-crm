import json
import logging
from typing import List, Optional


from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from services.service_progresses import Service_progressesService

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/service_progresses", tags=["service_progresses"])


# ---------- Pydantic Schemas ----------
class Service_progressesData(BaseModel):
    """Entity data schema (for create/update)"""
    customer_id: int
    service_type: str = None
    service_stage: str
    progress_percent: int = None
    sales_person: str = None
    ops_person: str = None
    design_person: str = None
    service_start_date: str = None
    service_end_date: str = None
    last_update_time: str = None
    last_update_person: str = None
    last_work_summary: str = None
    issue_status: str = None
    issue_description: str = None
    issue_found_date: str = None
    issue_owner: str = None
    issue_resolved: bool = None
    issue_resolved_date: str = None
    notes: str = None
    user_id: str
    created_at: str = None


class Service_progressesUpdateData(BaseModel):
    """Update entity data (partial updates allowed)"""
    customer_id: Optional[int] = None
    service_type: Optional[str] = None
    service_stage: Optional[str] = None
    progress_percent: Optional[int] = None
    sales_person: Optional[str] = None
    ops_person: Optional[str] = None
    design_person: Optional[str] = None
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
    service_type: Optional[str] = None
    service_stage: str
    progress_percent: Optional[int] = None
    sales_person: Optional[str] = None
    ops_person: Optional[str] = None
    design_person: Optional[str] = None
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
    user_id: str
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


# ---------- Routes ----------
@router.get("", response_model=Service_progressesListResponse)
async def query_service_progressess(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    """Query service_progressess with filtering, sorting, and pagination"""
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
    db: AsyncSession = Depends(get_db),
):
    # Query service_progressess with filtering, sorting, and pagination without user limitation
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
            sort=sort
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
    db: AsyncSession = Depends(get_db),
):
    """Get a single service_progresses by ID"""
    logger.debug(f"Fetching service_progresses with id: {id}, fields={fields}")
    
    service = Service_progressesService(db)
    try:
        result = await service.get_by_id(id)
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
    db: AsyncSession = Depends(get_db),
):
    """Create a new service_progresses"""
    logger.debug(f"Creating new service_progresses with data: {data}")
    
    service = Service_progressesService(db)
    try:
        result = await service.create(data.model_dump())
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
    db: AsyncSession = Depends(get_db),
):
    """Create multiple service_progressess in a single request"""
    logger.debug(f"Batch creating {len(request.items)} service_progressess")
    
    service = Service_progressesService(db)
    results = []
    
    try:
        for item_data in request.items:
            result = await service.create(item_data.model_dump())
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
    db: AsyncSession = Depends(get_db),
):
    """Update multiple service_progressess in a single request"""
    logger.debug(f"Batch updating {len(request.items)} service_progressess")
    
    service = Service_progressesService(db)
    results = []
    
    try:
        for item in request.items:
            # Only include non-None values for partial updates
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            result = await service.update(item.id, update_dict)
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
    db: AsyncSession = Depends(get_db),
):
    """Update an existing service_progresses"""
    logger.debug(f"Updating service_progresses {id} with data: {data}")

    service = Service_progressesService(db)
    try:
        # Only include non-None values for partial updates
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        result = await service.update(id, update_dict)
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
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple service_progressess by their IDs"""
    logger.debug(f"Batch deleting {len(request.ids)} service_progressess")
    
    service = Service_progressesService(db)
    deleted_count = 0
    
    try:
        for item_id in request.ids:
            success = await service.delete(item_id)
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
    db: AsyncSession = Depends(get_db),
):
    """Delete a single service_progresses by ID"""
    logger.debug(f"Deleting service_progresses with id: {id}")
    
    service = Service_progressesService(db)
    try:
        success = await service.delete(id)
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