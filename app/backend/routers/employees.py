import json
import logging
from typing import List, Optional

from datetime import datetime, date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from services.employees import EmployeesService

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/employees", tags=["employees"])


# ---------- Pydantic Schemas ----------
class EmployeesData(BaseModel):
    """Entity data schema (for create/update)"""
    user_id: str
    name: str
    role: str
    phone: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None


class EmployeesUpdateData(BaseModel):
    """Update entity data (partial updates allowed)"""
    user_id: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None


class EmployeesResponse(BaseModel):
    """Entity response schema"""
    id: int
    user_id: Optional[str] = None
    name: str
    role: str
    phone: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class EmployeesListResponse(BaseModel):
    """List response schema"""
    items: List[EmployeesResponse]
    total: int
    skip: int
    limit: int


class EmployeesBatchCreateRequest(BaseModel):
    """Batch create request"""
    items: List[EmployeesData]


class EmployeesBatchUpdateItem(BaseModel):
    """Batch update item"""
    id: int
    updates: EmployeesUpdateData


class EmployeesBatchUpdateRequest(BaseModel):
    """Batch update request"""
    items: List[EmployeesBatchUpdateItem]


class EmployeesBatchDeleteRequest(BaseModel):
    """Batch delete request"""
    ids: List[int]


# ---------- Routes ----------
@router.get("", response_model=EmployeesListResponse)
async def query_employeess(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    """Query employeess with filtering, sorting, and pagination"""
    logger.debug(f"Querying employeess: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")
    
    service = EmployeesService(db)
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
        logger.debug(f"Found {result['total']} employeess")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying employeess: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/all", response_model=EmployeesListResponse)
async def query_employeess_all(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    # Query employeess with filtering, sorting, and pagination without user limitation
    logger.debug(f"Querying employeess: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")

    service = EmployeesService(db)
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
        logger.debug(f"Found {result['total']} employeess")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying employeess: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{id}", response_model=EmployeesResponse)
async def get_employees(
    id: int,
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    db: AsyncSession = Depends(get_db),
):
    """Get a single employees by ID"""
    logger.debug(f"Fetching employees with id: {id}, fields={fields}")
    
    service = EmployeesService(db)
    try:
        result = await service.get_by_id(id)
        if not result:
            logger.warning(f"Employees with id {id} not found")
            raise HTTPException(status_code=404, detail="Employees not found")
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching employees {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("", response_model=EmployeesResponse, status_code=201)
async def create_employees(
    data: EmployeesData,
    db: AsyncSession = Depends(get_db),
):
    """Create a new employees"""
    logger.debug(f"Creating new employees with data: {data}")
    
    service = EmployeesService(db)
    try:
        result = await service.create(data.model_dump())
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create employees")
        
        logger.info(f"Employees created successfully with id: {result.id}")
        return result
    except ValueError as e:
        logger.error(f"Validation error creating employees: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating employees: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/batch", response_model=List[EmployeesResponse], status_code=201)
async def create_employeess_batch(
    request: EmployeesBatchCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create multiple employeess in a single request"""
    logger.debug(f"Batch creating {len(request.items)} employeess")
    
    service = EmployeesService(db)
    results = []
    
    try:
        for item_data in request.items:
            result = await service.create(item_data.model_dump())
            if result:
                results.append(result)
        
        logger.info(f"Batch created {len(results)} employeess successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch create: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch create failed: {str(e)}")


@router.put("/batch", response_model=List[EmployeesResponse])
async def update_employeess_batch(
    request: EmployeesBatchUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update multiple employeess in a single request"""
    logger.debug(f"Batch updating {len(request.items)} employeess")
    
    service = EmployeesService(db)
    results = []
    
    try:
        for item in request.items:
            # Only include non-None values for partial updates
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            result = await service.update(item.id, update_dict)
            if result:
                results.append(result)
        
        logger.info(f"Batch updated {len(results)} employeess successfully")
        return results
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")


@router.put("/{id}", response_model=EmployeesResponse)
async def update_employees(
    id: int,
    data: EmployeesUpdateData,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing employees"""
    logger.debug(f"Updating employees {id} with data: {data}")

    service = EmployeesService(db)
    try:
        # Only include non-None values for partial updates
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        result = await service.update(id, update_dict)
        if not result:
            logger.warning(f"Employees with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Employees not found")
        
        logger.info(f"Employees {id} updated successfully")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error updating employees {id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating employees {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/batch")
async def delete_employeess_batch(
    request: EmployeesBatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple employeess by their IDs"""
    logger.debug(f"Batch deleting {len(request.ids)} employeess")
    
    service = EmployeesService(db)
    deleted_count = 0
    
    try:
        for item_id in request.ids:
            success = await service.delete(item_id)
            if success:
                deleted_count += 1
        
        logger.info(f"Batch deleted {deleted_count} employeess successfully")
        return {"message": f"Successfully deleted {deleted_count} employeess", "deleted_count": deleted_count}
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch delete: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


@router.delete("/{id}")
async def delete_employees(
    id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a single employees by ID"""
    logger.debug(f"Deleting employees with id: {id}")
    
    service = EmployeesService(db)
    try:
        success = await service.delete(id)
        if not success:
            logger.warning(f"Employees with id {id} not found for deletion")
            raise HTTPException(status_code=404, detail="Employees not found")
        
        logger.info(f"Employees {id} deleted successfully")
        return {"message": "Employees deleted successfully", "id": id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting employees {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")