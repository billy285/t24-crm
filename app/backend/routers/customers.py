import json
import logging
from typing import List, Optional

from datetime import datetime, date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_admin_user, get_current_user
from schemas.auth import UserResponse
from services.customers import CustomersService
from models.management_decisions import BusinessLine, CustomerEngagement, ProductCatalog
from services.management_decision_workflow import save_customer_classification_review

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
    selected_platforms: Optional[str] = None
    interested_packages: Optional[str] = None
    interested_packages_snapshot: Optional[str] = None
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
    selected_platforms: Optional[str] = None
    interested_packages: Optional[str] = None
    interested_packages_snapshot: Optional[str] = None
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
    selected_platforms: Optional[str] = None
    interested_packages: Optional[str] = None
    interested_packages_snapshot: Optional[str] = None
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


class CustomerProjectInput(BaseModel):
    engagement_id: Optional[int] = None
    business_line_code: str
    product_code: Optional[str] = None
    product_name: Optional[str] = None
    package_name: Optional[str] = None
    status: str = "pending_setup"
    billing_cycle: Optional[str] = None
    collection_method: Optional[str] = None
    currency: str = "USD"
    owner_employee_id: Optional[int] = None
    sales_employee_id: Optional[int] = None
    paid_started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    stop_reason_code: Optional[str] = None
    stop_note: Optional[str] = None
    source_payment_ids: List[int] = Field(default_factory=list)
    source_subscription_ids: List[int] = Field(default_factory=list)


class CustomerWithProjectsCreateRequest(BaseModel):
    customer: CustomersData
    projects: List[CustomerProjectInput] = Field(default_factory=list)


class CustomerWithProjectsUpdateRequest(BaseModel):
    customer: CustomersUpdateData
    projects: List[CustomerProjectInput] = Field(default_factory=list)


def _actor_name(user: UserResponse) -> str:
    return user.name or user.email or "管理员"


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


@router.get("/{id}/projects")
async def get_customer_projects(
    id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = CustomersService(db)
    customer = await service.get_by_id(id, scope_user=current_user)
    if not customer:
        raise HTTPException(status_code=404, detail="Customers not found")
    rows = (await db.execute(
        select(CustomerEngagement, BusinessLine, ProductCatalog)
        .join(BusinessLine, BusinessLine.id == CustomerEngagement.business_line_id)
        .join(ProductCatalog, ProductCatalog.id == CustomerEngagement.product_id)
        .where(CustomerEngagement.customer_id == id)
        .order_by(CustomerEngagement.id.asc())
    )).all()
    return {
        "items": [{
            "id": engagement.id,
            "business_line_code": line.code,
            "business_line_name": line.name,
            "product_code": product.code,
            "product_name": product.name,
            "package_name": engagement.package_name or product.name,
            "status": engagement.status,
            "billing_cycle": engagement.billing_cycle,
            "collection_method": engagement.collection_method,
            "currency": engagement.currency,
            "owner_employee_id": engagement.owner_employee_id,
            "sales_employee_id": engagement.sales_employee_id,
            "paid_started_at": engagement.paid_started_at,
            "stopped_at": engagement.stopped_at,
        } for engagement, line, product in rows],
        "total": len(rows),
    }


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


@router.post("/with-projects", response_model=CustomersResponse, status_code=201)
async def create_customer_with_projects(
    request: CustomerWithProjectsCreateRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_customer_write_allowed(current_user)
    if len(request.projects) > 12:
        raise HTTPException(status_code=400, detail="单个客户最多维护12个合作项目")
    service = CustomersService(db)
    try:
        customer = await service.create(
            _assigned_to_current_user(request.customer.model_dump(), current_user),
            commit=False,
        )
        if request.projects:
            await save_customer_classification_review(
                db,
                customer_id=customer.id,
                decision="confirmed",
                projects=[row.model_dump() for row in request.projects],
                note="客户管理首次录入时建立合作项目",
                actor_id=str(current_user.id),
                actor_name=_actor_name(current_user),
                commit=False,
            )
        await db.commit()
        await db.refresh(customer)
        return customer
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await db.rollback()
        raise


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


@router.put("/{id}/with-projects", response_model=CustomersResponse)
async def update_customer_with_projects(
    id: int,
    request: CustomerWithProjectsUpdateRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_customer_write_allowed(current_user)
    if len(request.projects) > 12:
        raise HTTPException(status_code=400, detail="单个客户最多维护12个合作项目")
    service = CustomersService(db)
    try:
        update_dict = {key: value for key, value in request.customer.model_dump().items() if value is not None}
        update_dict = _strip_owner_fields_for_non_admin(update_dict, current_user)
        customer = await service.update(id, update_dict, scope_user=current_user, commit=False)
        if not customer:
            raise HTTPException(status_code=404, detail="Customers not found")
        if request.projects:
            await save_customer_classification_review(
                db,
                customer_id=id,
                decision="confirmed",
                projects=[row.model_dump() for row in request.projects],
                note="客户管理更新合作项目",
                actor_id=str(current_user.id),
                actor_name=_actor_name(current_user),
                commit=False,
            )
        await db.commit()
        await db.refresh(customer)
        return customer
    except HTTPException:
        await db.rollback()
        raise
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        await db.rollback()
        raise


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
