import json
import logging
from typing import List, Optional

from datetime import datetime, date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_admin_user, get_current_user
from schemas.auth import UserResponse
from services.employees import EmployeesService
from models.commissions import SalesPartner

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/employees", tags=["employees"], dependencies=[Depends(get_current_user)])


async def _ensure_sales_partner_profile(
    db: AsyncSession,
    employee,
    admin: UserResponse,
) -> SalesPartner:
    """Create or synchronize the external partner profile linked to a login account."""
    existing = await db.scalar(
        select(SalesPartner).where(
            SalesPartner.employee_id == employee.id,
            SalesPartner.partner_type.in_(["agency", "partner"]),
        )
    )
    if existing:
        existing.name = employee.name
        existing.contact_name = employee.name
        existing.contact_phone = employee.phone
        existing.contact_email = employee.email
        return existing

    joined_at = date.today()
    if employee.hire_date:
        try:
            joined_at = date.fromisoformat(employee.hire_date)
        except ValueError:
            pass
    base_code = (employee.employee_code or f"PARTNER-{employee.id}").strip().upper()
    partner_code = base_code
    suffix = 1
    while await db.scalar(select(SalesPartner.id).where(SalesPartner.partner_code == partner_code)):
        suffix += 1
        partner_code = f"{base_code}-{suffix}"
    partner = SalesPartner(
        partner_code=partner_code,
        name=employee.name,
        partner_type="partner",
        employee_id=employee.id,
        status="active",
        joined_at=joined_at,
        contact_name=employee.name,
        contact_phone=employee.phone,
        contact_email=employee.email,
        notes=employee.notes,
        created_by_id=str(admin.id),
        created_by_name=admin.name or admin.email,
    )
    db.add(partner)
    return partner


# ---------- Pydantic Schemas ----------
class EmployeesData(BaseModel):
    """Entity data schema (for create/update)"""
    user_id: Optional[str] = None
    name: str
    role: str
    phone: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    employee_code: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    login_username: Optional[str] = None
    hire_date: Optional[str] = None
    supervisor: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class EmployeesUpdateData(BaseModel):
    """Update entity data (partial updates allowed)"""
    user_id: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    employee_code: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    login_username: Optional[str] = None
    hire_date: Optional[str] = None
    supervisor: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class EmployeesResponse(BaseModel):
    """Entity response schema"""
    id: int
    user_id: Optional[str] = None
    name: str
    role: str
    phone: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    employee_code: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    login_username: Optional[str] = None
    hire_date: Optional[str] = None
    supervisor: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

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
    _admin: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new employees"""
    logger.debug(f"Creating new employees with data: {data}")
    
    service = EmployeesService(db)
    try:
        payload = data.model_dump()
        if not payload.get("user_id"):
            payload["user_id"] = (
                payload.get("login_username")
                or payload.get("email")
                or payload.get("employee_code")
                or f"emp_{int(datetime.utcnow().timestamp())}"
            )
        if not payload.get("status"):
            payload["status"] = "active"
        is_sales_partner = payload.get("role") == "sales_partner"
        result = await service.create(payload, commit=not is_sales_partner)
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create employees")
        if is_sales_partner:
            await _ensure_sales_partner_profile(db, result, _admin)
            await db.commit()
            await db.refresh(result)
        
        logger.info(f"Employees created successfully with id: {result.id}")
        return result
    except ValueError as e:
        await db.rollback()
        logger.error(f"Validation error creating employees: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating employees: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/batch", response_model=List[EmployeesResponse], status_code=201)
async def create_employeess_batch(
    request: EmployeesBatchCreateRequest,
    _admin: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create multiple employeess in a single request"""
    logger.debug(f"Batch creating {len(request.items)} employeess")
    
    service = EmployeesService(db)
    results = []
    
    try:
        if any(item.role == "sales_partner" for item in request.items):
            raise HTTPException(
                status_code=400,
                detail="销售合伙人账号请使用单个新增，以确保登录账号与分润档案同步建立",
            )
        for item_data in request.items:
            result = await service.create(item_data.model_dump())
            if result:
                results.append(result)
        
        logger.info(f"Batch created {len(results)} employeess successfully")
        return results
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch create: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch create failed: {str(e)}")


@router.put("/batch", response_model=List[EmployeesResponse])
async def update_employeess_batch(
    request: EmployeesBatchUpdateRequest,
    _admin: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update multiple employeess in a single request"""
    logger.debug(f"Batch updating {len(request.items)} employeess")
    
    service = EmployeesService(db)
    results = []
    
    try:
        if any(item.updates.role == "sales_partner" for item in request.items):
            raise HTTPException(
                status_code=400,
                detail="销售合伙人角色请使用单个编辑，以确保登录账号与分润档案同步",
            )
        for item in request.items:
            # Only include non-None values for partial updates
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            result = await service.update(item.id, update_dict)
            if result:
                results.append(result)
        
        logger.info(f"Batch updated {len(results)} employeess successfully")
        return results
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")


@router.put("/{id}", response_model=EmployeesResponse)
async def update_employees(
    id: int,
    data: EmployeesUpdateData,
    _admin: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing employees"""
    logger.debug(f"Updating employees {id} with data: {data}")

    service = EmployeesService(db)
    try:
        # Only include non-None values for partial updates
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        existing = await service.get_by_id(id)
        if not existing:
            logger.warning(f"Employees with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Employees not found")
        target_role = update_dict.get("role", existing.role)
        is_sales_partner = target_role == "sales_partner"
        result = await service.update(id, update_dict, commit=not is_sales_partner)
        if not result:
            logger.warning(f"Employees with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Employees not found")
        if is_sales_partner:
            await _ensure_sales_partner_profile(db, result, _admin)
            await db.commit()
            await db.refresh(result)
        
        logger.info(f"Employees {id} updated successfully")
        return result
    except HTTPException:
        await db.rollback()
        raise
    except ValueError as e:
        await db.rollback()
        logger.error(f"Validation error updating employees {id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating employees {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/batch")
async def delete_employeess_batch(
    request: EmployeesBatchDeleteRequest,
    _admin: UserResponse = Depends(get_admin_user),
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
    _admin: UserResponse = Depends(get_admin_user),
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
