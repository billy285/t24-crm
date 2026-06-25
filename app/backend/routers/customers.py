import json
import logging
from typing import List, Optional

from datetime import datetime, date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_admin_user, get_current_user
from schemas.auth import UserResponse
from services.customers import CustomersService

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/customers", tags=["customers"], dependencies=[Depends(get_current_user)])

CUSTOMER_WRITE_ROLES = {"admin", "super_admin", "sales", "ops", "operations"}
CUSTOMER_OWNER_FIELDS = {"sales_person", "sales_employee_id"}


class CustomerPayloadMixin(BaseModel):
    @field_validator("sales_employee_id", "monthly_orders", mode="before", check_fields=False)
    @classmethod
    def blank_string_to_none(cls, value):
        if value == "":
            return None
        return value


def _is_admin_role(user: UserResponse) -> bool:
    return str(user.role or "").lower() in {"admin", "super_admin"}


def _ensure_customer_write_allowed(user: UserResponse) -> None:
    if str(user.role or "").lower() not in CUSTOMER_WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Customer write access required")


def _assigned_to_current_user(data: dict, user: UserResponse) -> dict:
    if _is_admin_role(user):
        return data

    assigned = dict(data)
    try:
        assigned["sales_employee_id"] = int(user.id)
    except (TypeError, ValueError):
        assigned.pop("sales_employee_id", None)
    if user.name:
        assigned["sales_person"] = user.name
    return assigned


def _strip_owner_fields_for_non_admin(update_dict: dict, user: UserResponse) -> dict:
    if _is_admin_role(user):
        return update_dict
    return {key: value for key, value in update_dict.items() if key not in CUSTOMER_OWNER_FIELDS}


# ---------- Pydantic Schemas ----------
class CustomersData(CustomerPayloadMixin):
    """Entity data schema (for create/update)"""
    customer_code: Optional[str] = None
    business_name: str
    contact_name: str
    phone: str
    wechat: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    google_business_link: Optional[str] = None
    facebook_link: Optional[str] = None
    instagram_link: Optional[str] = None
    yelp_link: Optional[str] = None
    tiktok_link: Optional[str] = None
    has_ordering_system: Optional[bool] = None
    current_platform: Optional[str] = None
    interested_packages: Optional[str] = None
    monthly_orders: Optional[int] = None
    source: Optional[str] = None
    sales_person: Optional[str] = None
    sales_employee_id: Optional[int] = None
    level: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CustomersUpdateData(CustomerPayloadMixin):
    """Update entity data (partial updates allowed)"""
    customer_code: Optional[str] = None
    business_name: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    wechat: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    google_business_link: Optional[str] = None
    facebook_link: Optional[str] = None
    instagram_link: Optional[str] = None
    yelp_link: Optional[str] = None
    tiktok_link: Optional[str] = None
    has_ordering_system: Optional[bool] = None
    current_platform: Optional[str] = None
    interested_packages: Optional[str] = None
    monthly_orders: Optional[int] = None
    source: Optional[str] = None
    sales_person: Optional[str] = None
    sales_employee_id: Optional[int] = None
    level: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CustomersResponse(BaseModel):
    """Entity response schema"""
    id: int
    customer_code: Optional[str] = None
    business_name: str
    contact_name: str
    phone: str
    wechat: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    google_business_link: Optional[str] = None
    facebook_link: Optional[str] = None
    instagram_link: Optional[str] = None
    yelp_link: Optional[str] = None
    tiktok_link: Optional[str] = None
    has_ordering_system: Optional[bool] = None
    current_platform: Optional[str] = None
    interested_packages: Optional[str] = None
    monthly_orders: Optional[int] = None
    source: Optional[str] = None
    sales_person: Optional[str] = None
    sales_employee_id: Optional[int] = None
    level: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CustomersListResponse(BaseModel):
    """List response schema"""
    items: List[CustomersResponse]
    total: int
    skip: int
    limit: int


class CustomersBatchCreateRequest(BaseModel):
    """Batch create request"""
    items: List[CustomersData]


class CustomersBatchUpdateItem(BaseModel):
    """Batch update item"""
    id: int
    updates: CustomersUpdateData


class CustomersBatchUpdateRequest(BaseModel):
    """Batch update request"""
    items: List[CustomersBatchUpdateItem]


class CustomersBatchDeleteRequest(BaseModel):
    """Batch delete request"""
    ids: List[int]


# ---------- Routes ----------
@router.get("", response_model=CustomersListResponse)
async def query_customerss(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Query customerss with filtering, sorting, and pagination"""
    logger.debug(f"Querying customerss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")
    
    service = CustomersService(db)
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
            scope_user=current_user,
        )
        logger.debug(f"Found {result['total']} customerss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying customerss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/all", response_model=CustomersListResponse)
async def query_customerss_all(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Query customerss with role-based data limitation
    logger.debug(f"Querying customerss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")

    service = CustomersService(db)
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
            scope_user=current_user,
        )
        logger.debug(f"Found {result['total']} customerss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying customerss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/{id}", response_model=CustomersResponse)
async def get_customers(
    id: int,
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single customers by ID"""
    logger.debug(f"Fetching customers with id: {id}, fields={fields}")
    
    service = CustomersService(db)
    try:
        result = await service.get_by_id(id, scope_user=current_user)
        if not result:
            logger.warning(f"Customers with id {id} not found")
            raise HTTPException(status_code=404, detail="Customers not found")
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching customers {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("", response_model=CustomersResponse, status_code=201)
async def create_customers(
    data: CustomersData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new customers"""
    logger.debug(f"Creating new customers with data: {data}")
    
    service = CustomersService(db)
    try:
        _ensure_customer_write_allowed(current_user)
        result = await service.create(_assigned_to_current_user(data.model_dump(), current_user))
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create customers")
        
        logger.info(f"Customers created successfully with id: {result.id}")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error creating customers: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating customers: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/batch", response_model=List[CustomersResponse], status_code=201)
async def create_customerss_batch(
    request: CustomersBatchCreateRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create multiple customerss in a single request"""
    logger.debug(f"Batch creating {len(request.items)} customerss")
    
    service = CustomersService(db)
    results = []
    
    try:
        _ensure_customer_write_allowed(current_user)
        for item_data in request.items:
            result = await service.create(_assigned_to_current_user(item_data.model_dump(), current_user))
            if result:
                results.append(result)
        
        logger.info(f"Batch created {len(results)} customerss successfully")
        return results
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch create: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch create failed: {str(e)}")


@router.put("/batch", response_model=List[CustomersResponse])
async def update_customerss_batch(
    request: CustomersBatchUpdateRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update multiple customerss in a single request"""
    logger.debug(f"Batch updating {len(request.items)} customerss")
    
    service = CustomersService(db)
    results = []
    
    try:
        _ensure_customer_write_allowed(current_user)
        for item in request.items:
            # Only include non-None values for partial updates
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            update_dict = _strip_owner_fields_for_non_admin(update_dict, current_user)
            result = await service.update(item.id, update_dict, scope_user=current_user)
            if result:
                results.append(result)
        
        logger.info(f"Batch updated {len(results)} customerss successfully")
        return results
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")


@router.put("/{id}", response_model=CustomersResponse)
async def update_customers(
    id: int,
    data: CustomersUpdateData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing customers"""
    logger.debug(f"Updating customers {id} with data: {data}")

    service = CustomersService(db)
    try:
        _ensure_customer_write_allowed(current_user)
        # Only include non-None values for partial updates
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        update_dict = _strip_owner_fields_for_non_admin(update_dict, current_user)
        result = await service.update(id, update_dict, scope_user=current_user)
        if not result:
            logger.warning(f"Customers with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Customers not found")
        
        logger.info(f"Customers {id} updated successfully")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error updating customers {id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating customers {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/batch")
async def delete_customerss_batch(
    request: CustomersBatchDeleteRequest,
    _admin: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple customerss by their IDs"""
    logger.debug(f"Batch deleting {len(request.ids)} customerss")
    
    service = CustomersService(db)
    deleted_count = 0
    
    try:
        for item_id in request.ids:
            success = await service.delete(item_id)
            if success:
                deleted_count += 1
        
        logger.info(f"Batch deleted {deleted_count} customerss successfully")
        return {"message": f"Successfully deleted {deleted_count} customerss", "deleted_count": deleted_count}
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch delete: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


@router.delete("/{id}")
async def delete_customers(
    id: int,
    _admin: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single customers by ID"""
    logger.debug(f"Deleting customers with id: {id}")
    
    service = CustomersService(db)
    try:
        success = await service.delete(id)
        if not success:
            logger.warning(f"Customers with id {id} not found for deletion")
            raise HTTPException(status_code=404, detail="Customers not found")
        
        logger.info(f"Customers {id} deleted successfully")
        return {"message": "Customers deleted successfully", "id": id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting customers {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
