import json
import logging
from typing import List, Optional

from datetime import datetime, date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from services.customer_callbacks import Customer_callbacksService

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/customer_callbacks", tags=["customer_callbacks"])


# ---------- Pydantic Schemas ----------
class Customer_callbacksData(BaseModel):
    """Entity data schema (for create/update)"""
    customer_id: int
    employee_id: Optional[int] = None
    employee_name: Optional[str] = None
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
    db: AsyncSession = Depends(get_db),
):
    """Query customer_callbacks with filtering, sorting, and pagination"""
    logger.debug(f"Querying customer_callbacks: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")

    service = Customer_callbacksService(db)
    try:
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
    db: AsyncSession = Depends(get_db),
):
    """Query customer_callbacks without user limitation"""
    logger.debug(f"Querying all customer_callbacks: query={query}, sort={sort}, skip={skip}, limit={limit}")

    service = Customer_callbacksService(db)
    try:
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
    db: AsyncSession = Depends(get_db),
):
    """Get a single customer_callback by ID"""
    logger.debug(f"Fetching customer_callback with id: {id}, fields={fields}")

    service = Customer_callbacksService(db)
    try:
        result = await service.get_by_id(id)
        if not result:
            logger.warning(f"Customer_callback with id {id} not found")
            raise HTTPException(status_code=404, detail="Customer_callback not found")

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching customer_callback {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("", response_model=Customer_callbacksResponse, status_code=201)
async def create_customer_callback(
    data: Customer_callbacksData,
    db: AsyncSession = Depends(get_db),
):
    """Create a new customer_callback"""
    logger.debug(f"Creating new customer_callback with data: {data}")

    service = Customer_callbacksService(db)
    try:
        result = await service.create(data.model_dump())
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create customer_callback")

        logger.info(f"Customer_callback created successfully with id: {result.id}")
        return result
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
):
    """Create multiple customer_callbacks in a single request"""
    logger.debug(f"Batch creating {len(request.items)} customer_callbacks")

    service = Customer_callbacksService(db)
    results = []

    try:
        for item_data in request.items:
            result = await service.create(item_data.model_dump())
            if result:
                results.append(result)

        logger.info(f"Batch created {len(results)} customer_callbacks successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch create: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch create failed: {str(e)}")


@router.put("/batch", response_model=List[Customer_callbacksResponse])
async def update_customer_callbacks_batch(
    request: Customer_callbacksBatchUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update multiple customer_callbacks in a single request"""
    logger.debug(f"Batch updating {len(request.items)} customer_callbacks")

    service = Customer_callbacksService(db)
    results = []

    try:
        for item in request.items:
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            result = await service.update(item.id, update_dict)
            if result:
                results.append(result)

        logger.info(f"Batch updated {len(results)} customer_callbacks successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")


@router.put("/{id}", response_model=Customer_callbacksResponse)
async def update_customer_callback(
    id: int,
    data: Customer_callbacksUpdateData,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing customer_callback"""
    logger.debug(f"Updating customer_callback {id} with data: {data}")

    service = Customer_callbacksService(db)
    try:
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        result = await service.update(id, update_dict)
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
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple customer_callbacks by their IDs"""
    logger.debug(f"Batch deleting {len(request.ids)} customer_callbacks")

    service = Customer_callbacksService(db)
    deleted_count = 0

    try:
        for item_id in request.ids:
            success = await service.delete(item_id)
            if success:
                deleted_count += 1

        logger.info(f"Batch deleted {deleted_count} customer_callbacks successfully")
        return {"message": f"Successfully deleted {deleted_count} customer_callbacks", "deleted_count": deleted_count}
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch delete: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


@router.delete("/{id}")
async def delete_customer_callback(
    id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a single customer_callback by ID"""
    logger.debug(f"Deleting customer_callback with id: {id}")

    service = Customer_callbacksService(db)
    try:
        success = await service.delete(id)
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