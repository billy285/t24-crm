import json
import logging
from typing import List, Optional

from datetime import datetime, date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from services.follow_ups import Follow_upsService

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/follow_ups", tags=["follow_ups"])


# ---------- Pydantic Schemas ----------
class Follow_upsData(BaseModel):
    """Entity data schema (for create/update)"""
    customer_id: int
    employee_id: Optional[int] = None
    employee_name: Optional[str] = None
    contact_method: Optional[str] = None
    content: str
    customer_needs: Optional[str] = None
    customer_pain_points: Optional[str] = None
    has_quoted: Optional[bool] = None
    quote_plan: Optional[str] = None
    close_probability: Optional[int] = None
    stage: Optional[str] = None
    next_follow_date: Optional[datetime] = None
    created_at: Optional[datetime] = None


class Follow_upsUpdateData(BaseModel):
    """Update entity data (partial updates allowed)"""
    customer_id: Optional[int] = None
    employee_id: Optional[int] = None
    employee_name: Optional[str] = None
    contact_method: Optional[str] = None
    content: Optional[str] = None
    customer_needs: Optional[str] = None
    customer_pain_points: Optional[str] = None
    has_quoted: Optional[bool] = None
    quote_plan: Optional[str] = None
    close_probability: Optional[int] = None
    stage: Optional[str] = None
    next_follow_date: Optional[datetime] = None
    created_at: Optional[datetime] = None


class Follow_upsResponse(BaseModel):
    """Entity response schema"""
    id: int
    customer_id: int
    employee_id: Optional[int] = None
    employee_name: Optional[str] = None
    contact_method: Optional[str] = None
    content: str
    customer_needs: Optional[str] = None
    customer_pain_points: Optional[str] = None
    has_quoted: Optional[bool] = None
    quote_plan: Optional[str] = None
    close_probability: Optional[int] = None
    stage: Optional[str] = None
    next_follow_date: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class Follow_upsListResponse(BaseModel):
    """List response schema"""
    items: List[Follow_upsResponse]
    total: int
    skip: int
    limit: int


class Follow_upsBatchCreateRequest(BaseModel):
    """Batch create request"""
    items: List[Follow_upsData]


class Follow_upsBatchUpdateItem(BaseModel):
    """Batch update item"""
    id: int
    updates: Follow_upsUpdateData


class Follow_upsBatchUpdateRequest(BaseModel):
    """Batch update request"""
    items: List[Follow_upsBatchUpdateItem]


class Follow_upsBatchDeleteRequest(BaseModel):
    """Batch delete request"""
    ids: List[int]


# ---------- Routes ----------
@router.get("", response_model=Follow_upsListResponse)
async def query_follow_upss(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    """Query follow_upss with filtering, sorting, and pagination"""
    logger.debug(f"Querying follow_upss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")
    
    service = Follow_upsService(db)
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
        logger.debug(f"Found {result['total']} follow_upss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying follow_upss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/all", response_model=Follow_upsListResponse)
async def query_follow_upss_all(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    # Query follow_upss with filtering, sorting, and pagination without user limitation
    logger.debug(f"Querying follow_upss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")

    service = Follow_upsService(db)
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
        logger.debug(f"Found {result['total']} follow_upss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying follow_upss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{id}", response_model=Follow_upsResponse)
async def get_follow_ups(
    id: int,
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    """Get a single follow_ups by ID"""
    logger.debug(f"Fetching follow_ups with id: {id}, fields={fields}")
    
    service = Follow_upsService(db)
    try:
        result = await service.get_by_id(id)
        if not result:
            logger.warning(f"Follow_ups with id {id} not found")
            raise HTTPException(status_code=404, detail="Follow_ups not found")
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching follow_ups {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("", response_model=Follow_upsResponse, status_code=201)
async def create_follow_ups(
    data: Follow_upsData,
    db: AsyncSession = Depends(get_db),
):
    """Create a new follow_ups"""
    logger.debug(f"Creating new follow_ups with data: {data}")
    
    service = Follow_upsService(db)
    try:
        result = await service.create(data.model_dump())
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create follow_ups")
        
        logger.info(f"Follow_ups created successfully with id: {result.id}")
        return result
    except ValueError as e:
        logger.error(f"Validation error creating follow_ups: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating follow_ups: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/batch", response_model=List[Follow_upsResponse], status_code=201)
async def create_follow_upss_batch(
    request: Follow_upsBatchCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create multiple follow_upss in a single request"""
    logger.debug(f"Batch creating {len(request.items)} follow_upss")
    
    service = Follow_upsService(db)
    results = []
    
    try:
        for item_data in request.items:
            result = await service.create(item_data.model_dump())
            if result:
                results.append(result)
        
        logger.info(f"Batch created {len(results)} follow_upss successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch create: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch create failed: {str(e)}")


@router.put("/batch", response_model=List[Follow_upsResponse])
async def update_follow_upss_batch(
    request: Follow_upsBatchUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update multiple follow_upss in a single request"""
    logger.debug(f"Batch updating {len(request.items)} follow_upss")
    
    service = Follow_upsService(db)
    results = []
    
    try:
        for item in request.items:
            # Only include non-None values for partial updates
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            result = await service.update(item.id, update_dict)
            if result:
                results.append(result)
        
        logger.info(f"Batch updated {len(results)} follow_upss successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")


@router.put("/{id}", response_model=Follow_upsResponse)
async def update_follow_ups(
    id: int,
    data: Follow_upsUpdateData,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing follow_ups"""
    logger.debug(f"Updating follow_ups {id} with data: {data}")

    service = Follow_upsService(db)
    try:
        # Only include non-None values for partial updates
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        result = await service.update(id, update_dict)
        if not result:
            logger.warning(f"Follow_ups with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Follow_ups not found")
        
        logger.info(f"Follow_ups {id} updated successfully")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error updating follow_ups {id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating follow_ups {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/batch")
async def delete_follow_upss_batch(
    request: Follow_upsBatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple follow_upss by their IDs"""
    logger.debug(f"Batch deleting {len(request.ids)} follow_upss")
    
    service = Follow_upsService(db)
    deleted_count = 0
    
    try:
        for item_id in request.ids:
            success = await service.delete(item_id)
            if success:
                deleted_count += 1
        
        logger.info(f"Batch deleted {deleted_count} follow_upss successfully")
        return {"message": f"Successfully deleted {deleted_count} follow_upss", "deleted_count": deleted_count}
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch delete: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


@router.delete("/{id}")
async def delete_follow_ups(
    id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a single follow_ups by ID"""
    logger.debug(f"Deleting follow_ups with id: {id}")
    
    service = Follow_upsService(db)
    try:
        success = await service.delete(id)
        if not success:
            logger.warning(f"Follow_ups with id {id} not found for deletion")
            raise HTTPException(status_code=404, detail="Follow_ups not found")
        
        logger.info(f"Follow_ups {id} deleted successfully")
        return {"message": "Follow_ups deleted successfully", "id": id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting follow_ups {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")