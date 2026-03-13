import json
import logging
from typing import List, Optional

from datetime import datetime, date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from services.payments import PaymentsService
from dependencies.auth import get_current_user
from schemas.auth import UserResponse

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/payments", tags=["payments"])


# ---------- Pydantic Schemas ----------
class PaymentsData(BaseModel):
    """Entity data schema (for create/update)"""
    customer_id: int
    customer_name: Optional[str] = None
    income_type: Optional[str] = None
    product_name: Optional[str] = None
    amount_due: float
    amount_paid: float
    currency: Optional[str] = None
    payment_date: Optional[datetime] = None
    payment_method: Optional[str] = None
    billing_cycle: Optional[str] = None
    coverage_start: Optional[datetime] = None
    coverage_end: Optional[datetime] = None
    has_invoice: Optional[bool] = None
    outstanding_amount: Optional[float] = None
    expense_month: Optional[str] = None
    recorded_by: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class PaymentsUpdateData(BaseModel):
    """Update entity data (partial updates allowed)"""
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    income_type: Optional[str] = None
    product_name: Optional[str] = None
    amount_due: Optional[float] = None
    amount_paid: Optional[float] = None
    currency: Optional[str] = None
    payment_date: Optional[datetime] = None
    payment_method: Optional[str] = None
    billing_cycle: Optional[str] = None
    coverage_start: Optional[datetime] = None
    coverage_end: Optional[datetime] = None
    has_invoice: Optional[bool] = None
    outstanding_amount: Optional[float] = None
    expense_month: Optional[str] = None
    recorded_by: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class PaymentsResponse(BaseModel):
    """Entity response schema"""
    id: int
    customer_id: int
    customer_name: Optional[str] = None
    income_type: Optional[str] = None
    product_name: Optional[str] = None
    amount_due: float
    amount_paid: float
    currency: Optional[str] = None
    payment_date: Optional[datetime] = None
    payment_method: Optional[str] = None
    billing_cycle: Optional[str] = None
    coverage_start: Optional[datetime] = None
    coverage_end: Optional[datetime] = None
    has_invoice: Optional[bool] = None
    outstanding_amount: Optional[float] = None
    expense_month: Optional[str] = None
    recorded_by: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    user_id: Optional[str] = None

    class Config:
        from_attributes = True


class PaymentsListResponse(BaseModel):
    """List response schema"""
    items: List[PaymentsResponse]
    total: int
    skip: int
    limit: int


class PaymentsBatchCreateRequest(BaseModel):
    """Batch create request"""
    items: List[PaymentsData]


class PaymentsBatchUpdateItem(BaseModel):
    """Batch update item"""
    id: int
    updates: PaymentsUpdateData


class PaymentsBatchUpdateRequest(BaseModel):
    """Batch update request"""
    items: List[PaymentsBatchUpdateItem]


class PaymentsBatchDeleteRequest(BaseModel):
    """Batch delete request"""
    ids: List[int]


# ---------- Routes ----------
@router.get("", response_model=PaymentsListResponse)
async def query_paymentss(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Query paymentss with filtering, sorting, and pagination (user can only see their own records)"""
    logger.debug(f"Querying paymentss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")
    
    service = PaymentsService(db)
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
            user_id=str(current_user.id),
        )
        logger.debug(f"Found {result['total']} paymentss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying paymentss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/all", response_model=PaymentsListResponse)
async def query_paymentss_all(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    # Query paymentss with filtering, sorting, and pagination without user limitation
    logger.debug(f"Querying paymentss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")

    service = PaymentsService(db)
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
        logger.debug(f"Found {result['total']} paymentss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying paymentss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{id}", response_model=PaymentsResponse)
async def get_payments(
    id: int,
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single payments by ID"""
    logger.debug(f"Fetching payments with id: {id}, fields={fields}")
    
    service = PaymentsService(db)
    try:
        result = await service.get_by_id(id)
        if not result:
            logger.warning(f"Payments with id {id} not found")
            raise HTTPException(status_code=404, detail="Payments not found")
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching payments {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("", response_model=PaymentsResponse, status_code=201)
async def create_payments(
    data: PaymentsData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new payments"""
    logger.debug(f"Creating new payments with data: {data}")
    
    service = PaymentsService(db)
    try:
        result = await service.create(data.model_dump(), user_id=str(current_user.id))
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create payments")
        
        logger.info(f"Payments created successfully with id: {result.id}")
        return result
    except ValueError as e:
        logger.error(f"Validation error creating payments: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating payments: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/batch", response_model=List[PaymentsResponse], status_code=201)
async def create_paymentss_batch(
    request: PaymentsBatchCreateRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create multiple paymentss in a single request"""
    logger.debug(f"Batch creating {len(request.items)} paymentss")
    
    service = PaymentsService(db)
    results = []
    
    try:
        for item_data in request.items:
            result = await service.create(item_data.model_dump(), user_id=str(current_user.id))
            if result:
                results.append(result)
        
        logger.info(f"Batch created {len(results)} paymentss successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch create: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch create failed: {str(e)}")


@router.put("/batch", response_model=List[PaymentsResponse])
async def update_paymentss_batch(
    request: PaymentsBatchUpdateRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update multiple paymentss in a single request (requires ownership)"""
    logger.debug(f"Batch updating {len(request.items)} paymentss")
    
    service = PaymentsService(db)
    results = []
    
    try:
        for item in request.items:
            # Only include non-None values for partial updates
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            result = await service.update(item.id, update_dict)
            if result:
                results.append(result)
        
        logger.info(f"Batch updated {len(results)} paymentss successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")


@router.put("/{id}", response_model=PaymentsResponse)
async def update_payments(
    id: int,
    data: PaymentsUpdateData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing payments"""
    logger.debug(f"Updating payments {id} with data: {data}")

    service = PaymentsService(db)
    try:
        # Only include non-None values for partial updates
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        result = await service.update(id, update_dict)
        if not result:
            logger.warning(f"Payments with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Payments not found")
        
        logger.info(f"Payments {id} updated successfully")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error updating payments {id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating payments {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/batch")
async def delete_paymentss_batch(
    request: PaymentsBatchDeleteRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple paymentss by their IDs (requires ownership)"""
    logger.debug(f"Batch deleting {len(request.ids)} paymentss")
    
    service = PaymentsService(db)
    deleted_count = 0
    
    try:
        for item_id in request.ids:
            success = await service.delete(item_id)
            if success:
                deleted_count += 1
        
        logger.info(f"Batch deleted {deleted_count} paymentss successfully")
        return {"message": f"Successfully deleted {deleted_count} paymentss", "deleted_count": deleted_count}
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch delete: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


@router.delete("/{id}")
async def delete_payments(
    id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single payments by ID"""
    logger.debug(f"Deleting payments with id: {id}")
    
    service = PaymentsService(db)
    try:
        success = await service.delete(id)
        if not success:
            logger.warning(f"Payments with id {id} not found for deletion")
            raise HTTPException(status_code=404, detail="Payments not found")
        
        logger.info(f"Payments {id} deleted successfully")
        return {"message": "Payments deleted successfully", "id": id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting payments {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")