import json
import logging
from typing import List, Optional

from datetime import datetime, date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from services.company_expenses import Company_expensesService

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/company_expenses", tags=["company_expenses"])


# ---------- Pydantic Schemas ----------
class Company_expensesData(BaseModel):
    """Entity data schema (for create/update)"""
    category: str
    category_name: Optional[str] = None
    amount: float
    currency: Optional[str] = None
    expense_date: Optional[datetime] = None
    expense_month: Optional[str] = None
    notes: Optional[str] = None
    recorded_by: Optional[str] = None
    created_at: Optional[datetime] = None


class Company_expensesUpdateData(BaseModel):
    """Update entity data (partial updates allowed)"""
    category: Optional[str] = None
    category_name: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    expense_date: Optional[datetime] = None
    expense_month: Optional[str] = None
    notes: Optional[str] = None
    recorded_by: Optional[str] = None
    created_at: Optional[datetime] = None
    user_id: Optional[str] = None


class Company_expensesResponse(BaseModel):
    """Entity response schema"""
    id: int
    category: Optional[str] = None
    category_name: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    expense_date: Optional[datetime] = None
    expense_month: Optional[str] = None
    notes: Optional[str] = None
    recorded_by: Optional[str] = None
    created_at: Optional[datetime] = None
    user_id: Optional[str] = None

    class Config:
        from_attributes = True


class Company_expensesListResponse(BaseModel):
    """List response schema"""
    items: List[Company_expensesResponse]
    total: int
    skip: int
    limit: int


class Company_expensesBatchCreateRequest(BaseModel):
    """Batch create request"""
    items: List[Company_expensesData]


class Company_expensesBatchUpdateItem(BaseModel):
    """Batch update item"""
    id: int
    updates: Company_expensesUpdateData


class Company_expensesBatchUpdateRequest(BaseModel):
    """Batch update request"""
    items: List[Company_expensesBatchUpdateItem]


class Company_expensesBatchDeleteRequest(BaseModel):
    """Batch delete request"""
    ids: List[int]


# ---------- Routes ----------
@router.get("", response_model=Company_expensesListResponse)
async def query_company_expensess(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    """Query company_expensess with filtering, sorting, and pagination"""
    logger.debug(f"Querying company_expensess: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")
    
    service = Company_expensesService(db)
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
        logger.debug(f"Found {result['total']} company_expensess")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying company_expensess: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/all", response_model=Company_expensesListResponse)
async def query_company_expensess_all(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    # Query company_expensess with filtering, sorting, and pagination without user limitation
    logger.debug(f"Querying company_expensess: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")

    service = Company_expensesService(db)
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
        logger.debug(f"Found {result['total']} company_expensess")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying company_expensess: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{id}", response_model=Company_expensesResponse)
async def get_company_expenses(
    id: int,
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    """Get a single company_expenses by ID"""
    logger.debug(f"Fetching company_expenses with id: {id}, fields={fields}")
    
    service = Company_expensesService(db)
    try:
        result = await service.get_by_id(id)
        if not result:
            logger.warning(f"Company_expenses with id {id} not found")
            raise HTTPException(status_code=404, detail="Company_expenses not found")
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching company_expenses {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("", response_model=Company_expensesResponse, status_code=201)
async def create_company_expenses(
    data: Company_expensesData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new company_expenses"""
    logger.debug(f"Creating new company_expenses with data: {data}")
    
    service = Company_expensesService(db)
    try:
        result = await service.create(data.model_dump(), user_id=str(current_user.id))
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create company_expenses")
        
        logger.info(f"Company_expenses created successfully with id: {result.id}")
        return result
    except ValueError as e:
        logger.error(f"Validation error creating company_expenses: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating company_expenses: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/batch", response_model=List[Company_expensesResponse], status_code=201)
async def create_company_expensess_batch(
    request: Company_expensesBatchCreateRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create multiple company_expensess in a single request"""
    logger.debug(f"Batch creating {len(request.items)} company_expensess")
    
    service = Company_expensesService(db)
    results = []
    
    try:
        for item_data in request.items:
            result = await service.create(item_data.model_dump(), user_id=str(current_user.id))
            if result:
                results.append(result)
        
        logger.info(f"Batch created {len(results)} company_expensess successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch create: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch create failed: {str(e)}")


@router.put("/batch", response_model=List[Company_expensesResponse])
async def update_company_expensess_batch(
    request: Company_expensesBatchUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update multiple company_expensess in a single request"""
    logger.debug(f"Batch updating {len(request.items)} company_expensess")
    
    service = Company_expensesService(db)
    results = []
    
    try:
        for item in request.items:
            # Only include non-None values for partial updates
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            result = await service.update(item.id, update_dict)
            if result:
                results.append(result)
        
        logger.info(f"Batch updated {len(results)} company_expensess successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")


@router.put("/{id}", response_model=Company_expensesResponse)
async def update_company_expenses(
    id: int,
    data: Company_expensesUpdateData,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing company_expenses"""
    logger.debug(f"Updating company_expenses {id} with data: {data}")

    service = Company_expensesService(db)
    try:
        # Only include non-None values for partial updates
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        result = await service.update(id, update_dict)
        if not result:
            logger.warning(f"Company_expenses with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Company_expenses not found")
        
        logger.info(f"Company_expenses {id} updated successfully")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error updating company_expenses {id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating company_expenses {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/batch")
async def delete_company_expensess_batch(
    request: Company_expensesBatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple company_expensess by their IDs"""
    logger.debug(f"Batch deleting {len(request.ids)} company_expensess")
    
    service = Company_expensesService(db)
    deleted_count = 0
    
    try:
        for item_id in request.ids:
            success = await service.delete(item_id)
            if success:
                deleted_count += 1
        
        logger.info(f"Batch deleted {deleted_count} company_expensess successfully")
        return {"message": f"Successfully deleted {deleted_count} company_expensess", "deleted_count": deleted_count}
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch delete: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


@router.delete("/{id}")
async def delete_company_expenses(
    id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a single company_expenses by ID"""
    logger.debug(f"Deleting company_expenses with id: {id}")
    
    service = Company_expensesService(db)
    try:
        success = await service.delete(id)
        if not success:
            logger.warning(f"Company_expenses with id {id} not found for deletion")
            raise HTTPException(status_code=404, detail="Company_expenses not found")
        
        logger.info(f"Company_expenses {id} deleted successfully")
        return {"message": "Company_expenses deleted successfully", "id": id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting company_expenses {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")