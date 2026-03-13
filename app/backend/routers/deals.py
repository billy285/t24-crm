import json
import logging
from typing import List, Optional

from datetime import datetime, date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from services.deals import DealsService

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/deals", tags=["deals"])


# ---------- Pydantic Schemas ----------
class DealsData(BaseModel):
    """Entity data schema (for create/update)"""
    customer_id: int
    customer_name: Optional[str] = None
    sales_employee_id: Optional[int] = None
    sales_name: Optional[str] = None
    product_type: str
    package_name: Optional[str] = None
    billing_cycle: Optional[str] = None
    deal_amount: float
    is_paid: Optional[bool] = None
    service_start_date: Optional[datetime] = None
    service_end_date: Optional[datetime] = None
    needs_group: Optional[bool] = None
    is_handed_over: Optional[bool] = None
    is_transferred_ops: Optional[bool] = None
    notes: Optional[str] = None
    deal_date: Optional[datetime] = None
    created_at: Optional[datetime] = None


class DealsUpdateData(BaseModel):
    """Update entity data (partial updates allowed)"""
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    sales_employee_id: Optional[int] = None
    sales_name: Optional[str] = None
    product_type: Optional[str] = None
    package_name: Optional[str] = None
    billing_cycle: Optional[str] = None
    deal_amount: Optional[float] = None
    is_paid: Optional[bool] = None
    service_start_date: Optional[datetime] = None
    service_end_date: Optional[datetime] = None
    needs_group: Optional[bool] = None
    is_handed_over: Optional[bool] = None
    is_transferred_ops: Optional[bool] = None
    notes: Optional[str] = None
    deal_date: Optional[datetime] = None
    created_at: Optional[datetime] = None


class DealsResponse(BaseModel):
    """Entity response schema"""
    id: int
    customer_id: int
    customer_name: Optional[str] = None
    sales_employee_id: Optional[int] = None
    sales_name: Optional[str] = None
    product_type: str
    package_name: Optional[str] = None
    billing_cycle: Optional[str] = None
    deal_amount: float
    is_paid: Optional[bool] = None
    service_start_date: Optional[datetime] = None
    service_end_date: Optional[datetime] = None
    needs_group: Optional[bool] = None
    is_handed_over: Optional[bool] = None
    is_transferred_ops: Optional[bool] = None
    notes: Optional[str] = None
    deal_date: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DealsListResponse(BaseModel):
    """List response schema"""
    items: List[DealsResponse]
    total: int
    skip: int
    limit: int


class DealsBatchCreateRequest(BaseModel):
    """Batch create request"""
    items: List[DealsData]


class DealsBatchUpdateItem(BaseModel):
    """Batch update item"""
    id: int
    updates: DealsUpdateData


class DealsBatchUpdateRequest(BaseModel):
    """Batch update request"""
    items: List[DealsBatchUpdateItem]


class DealsBatchDeleteRequest(BaseModel):
    """Batch delete request"""
    ids: List[int]


# ---------- Routes ----------
@router.get("", response_model=DealsListResponse)
async def query_dealss(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    """Query dealss with filtering, sorting, and pagination"""
    logger.debug(f"Querying dealss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")
    
    service = DealsService(db)
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
        logger.debug(f"Found {result['total']} dealss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying dealss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/all", response_model=DealsListResponse)
async def query_dealss_all(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    # Query dealss with filtering, sorting, and pagination without user limitation
    logger.debug(f"Querying dealss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")

    service = DealsService(db)
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
        logger.debug(f"Found {result['total']} dealss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying dealss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{id}", response_model=DealsResponse)
async def get_deals(
    id: int,
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    """Get a single deals by ID"""
    logger.debug(f"Fetching deals with id: {id}, fields={fields}")
    
    service = DealsService(db)
    try:
        result = await service.get_by_id(id)
        if not result:
            logger.warning(f"Deals with id {id} not found")
            raise HTTPException(status_code=404, detail="Deals not found")
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching deals {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("", response_model=DealsResponse, status_code=201)
async def create_deals(
    data: DealsData,
    db: AsyncSession = Depends(get_db),
):
    """Create a new deals"""
    logger.debug(f"Creating new deals with data: {data}")
    
    service = DealsService(db)
    try:
        result = await service.create(data.model_dump())
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create deals")
        
        logger.info(f"Deals created successfully with id: {result.id}")
        return result
    except ValueError as e:
        logger.error(f"Validation error creating deals: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating deals: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/batch", response_model=List[DealsResponse], status_code=201)
async def create_dealss_batch(
    request: DealsBatchCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create multiple dealss in a single request"""
    logger.debug(f"Batch creating {len(request.items)} dealss")
    
    service = DealsService(db)
    results = []
    
    try:
        for item_data in request.items:
            result = await service.create(item_data.model_dump())
            if result:
                results.append(result)
        
        logger.info(f"Batch created {len(results)} dealss successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch create: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch create failed: {str(e)}")


@router.put("/batch", response_model=List[DealsResponse])
async def update_dealss_batch(
    request: DealsBatchUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update multiple dealss in a single request"""
    logger.debug(f"Batch updating {len(request.items)} dealss")
    
    service = DealsService(db)
    results = []
    
    try:
        for item in request.items:
            # Only include non-None values for partial updates
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            result = await service.update(item.id, update_dict)
            if result:
                results.append(result)
        
        logger.info(f"Batch updated {len(results)} dealss successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")


@router.put("/{id}", response_model=DealsResponse)
async def update_deals(
    id: int,
    data: DealsUpdateData,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing deals"""
    logger.debug(f"Updating deals {id} with data: {data}")

    service = DealsService(db)
    try:
        # Only include non-None values for partial updates
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        result = await service.update(id, update_dict)
        if not result:
            logger.warning(f"Deals with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Deals not found")
        
        logger.info(f"Deals {id} updated successfully")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error updating deals {id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating deals {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/batch")
async def delete_dealss_batch(
    request: DealsBatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple dealss by their IDs"""
    logger.debug(f"Batch deleting {len(request.ids)} dealss")
    
    service = DealsService(db)
    deleted_count = 0
    
    try:
        for item_id in request.ids:
            success = await service.delete(item_id)
            if success:
                deleted_count += 1
        
        logger.info(f"Batch deleted {deleted_count} dealss successfully")
        return {"message": f"Successfully deleted {deleted_count} dealss", "deleted_count": deleted_count}
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch delete: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


@router.delete("/{id}")
async def delete_deals(
    id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a single deals by ID"""
    logger.debug(f"Deleting deals with id: {id}")
    
    service = DealsService(db)
    try:
        success = await service.delete(id)
        if not success:
            logger.warning(f"Deals with id {id} not found for deletion")
            raise HTTPException(status_code=404, detail="Deals not found")
        
        logger.info(f"Deals {id} deleted successfully")
        return {"message": "Deals deleted successfully", "id": id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting deals {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")