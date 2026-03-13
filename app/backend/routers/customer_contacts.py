import json
import logging
from typing import List, Optional

from datetime import datetime, date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from services.customer_contacts import Customer_contactsService

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/customer_contacts", tags=["customer_contacts"])


# ---------- Pydantic Schemas ----------
class Customer_contactsData(BaseModel):
    """Entity data schema (for create/update)"""
    customer_id: int
    contact_name: str
    contact_phone: Optional[str] = None
    contact_role: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class Customer_contactsUpdateData(BaseModel):
    """Update entity data (partial updates allowed)"""
    customer_id: Optional[int] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_role: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class Customer_contactsResponse(BaseModel):
    """Entity response schema"""
    id: int
    customer_id: int
    contact_name: str
    contact_phone: Optional[str] = None
    contact_role: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class Customer_contactsListResponse(BaseModel):
    """List response schema"""
    items: List[Customer_contactsResponse]
    total: int
    skip: int
    limit: int


class Customer_contactsBatchCreateRequest(BaseModel):
    """Batch create request"""
    items: List[Customer_contactsData]


class Customer_contactsBatchUpdateItem(BaseModel):
    """Batch update item"""
    id: int
    updates: Customer_contactsUpdateData


class Customer_contactsBatchUpdateRequest(BaseModel):
    """Batch update request"""
    items: List[Customer_contactsBatchUpdateItem]


class Customer_contactsBatchDeleteRequest(BaseModel):
    """Batch delete request"""
    ids: List[int]


# ---------- Routes ----------
@router.get("", response_model=Customer_contactsListResponse)
async def query_customer_contactss(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    """Query customer_contactss with filtering, sorting, and pagination"""
    logger.debug(f"Querying customer_contactss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")
    
    service = Customer_contactsService(db)
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
        logger.debug(f"Found {result['total']} customer_contactss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying customer_contactss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/all", response_model=Customer_contactsListResponse)
async def query_customer_contactss_all(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    # Query customer_contactss with filtering, sorting, and pagination without user limitation
    logger.debug(f"Querying customer_contactss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")

    service = Customer_contactsService(db)
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
        logger.debug(f"Found {result['total']} customer_contactss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying customer_contactss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{id}", response_model=Customer_contactsResponse)
async def get_customer_contacts(
    id: int,
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    """Get a single customer_contacts by ID"""
    logger.debug(f"Fetching customer_contacts with id: {id}, fields={fields}")
    
    service = Customer_contactsService(db)
    try:
        result = await service.get_by_id(id)
        if not result:
            logger.warning(f"Customer_contacts with id {id} not found")
            raise HTTPException(status_code=404, detail="Customer_contacts not found")
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching customer_contacts {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("", response_model=Customer_contactsResponse, status_code=201)
async def create_customer_contacts(
    data: Customer_contactsData,
    db: AsyncSession = Depends(get_db),
):
    """Create a new customer_contacts"""
    logger.debug(f"Creating new customer_contacts with data: {data}")
    
    service = Customer_contactsService(db)
    try:
        result = await service.create(data.model_dump())
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create customer_contacts")
        
        logger.info(f"Customer_contacts created successfully with id: {result.id}")
        return result
    except ValueError as e:
        logger.error(f"Validation error creating customer_contacts: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating customer_contacts: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/batch", response_model=List[Customer_contactsResponse], status_code=201)
async def create_customer_contactss_batch(
    request: Customer_contactsBatchCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create multiple customer_contactss in a single request"""
    logger.debug(f"Batch creating {len(request.items)} customer_contactss")
    
    service = Customer_contactsService(db)
    results = []
    
    try:
        for item_data in request.items:
            result = await service.create(item_data.model_dump())
            if result:
                results.append(result)
        
        logger.info(f"Batch created {len(results)} customer_contactss successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch create: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch create failed: {str(e)}")


@router.put("/batch", response_model=List[Customer_contactsResponse])
async def update_customer_contactss_batch(
    request: Customer_contactsBatchUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update multiple customer_contactss in a single request"""
    logger.debug(f"Batch updating {len(request.items)} customer_contactss")
    
    service = Customer_contactsService(db)
    results = []
    
    try:
        for item in request.items:
            # Only include non-None values for partial updates
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            result = await service.update(item.id, update_dict)
            if result:
                results.append(result)
        
        logger.info(f"Batch updated {len(results)} customer_contactss successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")


@router.put("/{id}", response_model=Customer_contactsResponse)
async def update_customer_contacts(
    id: int,
    data: Customer_contactsUpdateData,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing customer_contacts"""
    logger.debug(f"Updating customer_contacts {id} with data: {data}")

    service = Customer_contactsService(db)
    try:
        # Only include non-None values for partial updates
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        result = await service.update(id, update_dict)
        if not result:
            logger.warning(f"Customer_contacts with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Customer_contacts not found")
        
        logger.info(f"Customer_contacts {id} updated successfully")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error updating customer_contacts {id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating customer_contacts {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/batch")
async def delete_customer_contactss_batch(
    request: Customer_contactsBatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple customer_contactss by their IDs"""
    logger.debug(f"Batch deleting {len(request.ids)} customer_contactss")
    
    service = Customer_contactsService(db)
    deleted_count = 0
    
    try:
        for item_id in request.ids:
            success = await service.delete(item_id)
            if success:
                deleted_count += 1
        
        logger.info(f"Batch deleted {deleted_count} customer_contactss successfully")
        return {"message": f"Successfully deleted {deleted_count} customer_contactss", "deleted_count": deleted_count}
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch delete: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


@router.delete("/{id}")
async def delete_customer_contacts(
    id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a single customer_contacts by ID"""
    logger.debug(f"Deleting customer_contacts with id: {id}")
    
    service = Customer_contactsService(db)
    try:
        success = await service.delete(id)
        if not success:
            logger.warning(f"Customer_contacts with id {id} not found for deletion")
            raise HTTPException(status_code=404, detail="Customer_contacts not found")
        
        logger.info(f"Customer_contacts {id} deleted successfully")
        return {"message": "Customer_contacts deleted successfully", "id": id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting customer_contacts {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")