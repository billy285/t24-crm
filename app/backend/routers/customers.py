import json
import logging
from typing import List, Optional

from datetime import datetime, date

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_admin_user, get_current_user
from schemas.auth import UserResponse
from services.customers import CustomersService
from models.customers import Customers
from models.customer_access_grants import CustomerAccessGrant
from models.employees import Employees
from models.management_decisions import BusinessLine, CustomerEngagement, ProductCatalog
from services.commissions import auto_assign_new_customer
from services.management_decision_workflow import save_customer_classification_review
from services.operation_logs import Operation_logsService, build_server_operation_log_data
from services.role_permissions import require_any_page_permission, require_button_permission

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/customers", tags=["customers"], dependencies=[Depends(get_current_user)])

CUSTOMER_OWNER_FIELDS = {"sales_person", "sales_employee_id"}
ACTIVE_PROJECT_STATUSES = {"pending_setup", "trial", "active_paid", "at_risk", "paused", "pending_stop", "reactivated"}


class CustomerPayloadMixin(BaseModel):
    @field_validator("sales_employee_id", "monthly_orders", mode="before", check_fields=False)
    @classmethod
    def blank_string_to_none(cls, value):
        if value == "":
            return None
        return value


def _is_admin_role(user: UserResponse) -> bool:
    return str(user.role or "").lower() in {"admin", "super_admin"}


async def _require_customer_page(db: AsyncSession, user: UserResponse) -> None:
    """Full customer profiles are only available to the customer workspace."""
    await require_any_page_permission(db, user, {"/customers"})


async def _require_customer_write(db: AsyncSession, user: UserResponse, permission: str) -> None:
    await _require_customer_page(db, user)
    await require_button_permission(db, user, permission, admin_override=True)


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


class CustomerAccessMember(BaseModel):
    employee_id: int
    name: str
    role: str
    department: Optional[str] = None
    employee_code: Optional[str] = None


class CustomerAccessResponse(BaseModel):
    customer_id: int
    members: List[CustomerAccessMember]


class CustomerAccessUpdateRequest(BaseModel):
    employee_ids: List[int] = Field(default_factory=list)


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
    commission_partner_id: Optional[int] = Field(None, gt=0)
    commission_effective_from: Optional[date] = None


class CustomerWithProjectsUpdateRequest(BaseModel):
    customer: CustomersUpdateData
    projects: List[CustomerProjectInput] = Field(default_factory=list)


def _validate_customer_project_consistency(status: Optional[str], projects: List[CustomerProjectInput]) -> None:
    if status == "lost" and any(row.status in ACTIVE_PROJECT_STATUSES for row in projects):
        raise ValueError("客户标记流失前，请先将所有合作项目改为“项目已停止”或“已完成”；成交和收款历史无需删除")


async def _ensure_no_active_projects_before_direct_loss(db: AsyncSession, customer_id: int) -> None:
    active_project = (await db.execute(
        select(CustomerEngagement.id).where(
            CustomerEngagement.customer_id == customer_id,
            CustomerEngagement.status.in_(ACTIVE_PROJECT_STATUSES),
        ).limit(1)
    )).scalar_one_or_none()
    if active_project:
        raise ValueError("该客户仍有合作项目，请使用“客户生命周期—停止合作”完成状态闭环；成交和收款历史无需删除")


async def _ensure_owner_visibility_grant(db: AsyncSession, customer: Customers, actor: UserResponse) -> None:
    """Give a selected owner initial access while keeping later revocation independent."""
    employee_id = customer.sales_employee_id
    if not employee_id and customer.sales_person:
        employee_id = (await db.execute(
            select(Employees.id).where(Employees.name == customer.sales_person).limit(1)
        )).scalar_one_or_none()
    if not employee_id:
        return
    employee = await db.get(Employees, int(employee_id))
    if not employee or employee.status not in {"active", "probation"} or employee.role not in {"sales", "sales_manager", "ops", "operations", "design"}:
        return
    existing = (await db.execute(
        select(CustomerAccessGrant.id).where(
            CustomerAccessGrant.customer_id == customer.id,
            CustomerAccessGrant.employee_id == int(employee_id),
        )
    )).scalar_one_or_none()
    if existing is None:
        db.add(CustomerAccessGrant(
            customer_id=customer.id,
            employee_id=int(employee_id),
            granted_by_id=str(actor.id),
            granted_by_name=actor.name or actor.email,
        ))


def _actor_name(user: UserResponse) -> str:
    return user.name or user.email or "管理员"


def _new_customer_commission_date(
    customer: Customers,
    projects: List[CustomerProjectInput] | None = None,
    requested: date | None = None,
) -> date:
    if requested:
        return requested
    paid_dates = [row.paid_started_at.date() for row in (projects or []) if row.paid_started_at]
    if paid_dates:
        return min(paid_dates)
    if customer.created_at:
        return customer.created_at.date()
    return date.today()


async def _auto_assign_created_customer(
    db: AsyncSession,
    customer: Customers,
    user: UserResponse,
    *,
    projects: List[CustomerProjectInput] | None = None,
    partner_id: int | None = None,
    effective_from: date | None = None,
) -> None:
    await auto_assign_new_customer(
        db,
        customer_id=customer.id,
        sales_employee_id=customer.sales_employee_id,
        explicit_partner_id=partner_id,
        effective_from=_new_customer_commission_date(customer, projects, effective_from),
        actor_id=str(user.id),
        actor_name=_actor_name(user),
    )


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
    await _require_customer_page(db, current_user)
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
    await _require_customer_page(db, current_user)
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
    await _require_customer_page(db, current_user)
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
    await _require_customer_page(db, current_user)
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
            "stop_reason_code": engagement.stop_reason_code,
            "stop_note": engagement.stop_note,
        } for engagement, line, product in rows],
        "total": len(rows),
    }


@router.get("/{id}/access", response_model=CustomerAccessResponse)
async def get_customer_access(
    id: int,
    _admin: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """List employees explicitly invited to view a customer."""
    if not await db.get(Customers, id):
        raise HTTPException(status_code=404, detail="Customer not found")
    rows = (await db.execute(
        select(CustomerAccessGrant, Employees)
        .join(Employees, Employees.id == CustomerAccessGrant.employee_id)
        .where(CustomerAccessGrant.customer_id == id)
        .order_by(Employees.name.asc())
    )).all()
    return CustomerAccessResponse(
        customer_id=id,
        members=[
            CustomerAccessMember(
                employee_id=employee.id,
                name=employee.name,
                role=employee.role,
                department=employee.department,
                employee_code=employee.employee_code,
            )
            for _grant, employee in rows
        ],
    )


@router.put("/{id}/access", response_model=CustomerAccessResponse)
async def replace_customer_access(
    id: int,
    data: CustomerAccessUpdateRequest,
    admin: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Replace visibility without changing sales, project, or commission ownership."""
    if not await db.get(Customers, id):
        raise HTTPException(status_code=404, detail="Customer not found")

    requested_ids = sorted(set(data.employee_ids))
    employees = list((await db.execute(
        select(Employees).where(
            Employees.id.in_(requested_ids),
            Employees.status.in_(("active", "probation")),
            Employees.role.in_(("sales", "sales_manager", "ops", "operations", "design")),
        )
    )).scalars().all()) if requested_ids else []
    actual_ids = {employee.id for employee in employees}
    if actual_ids != set(requested_ids):
        raise HTTPException(status_code=400, detail="Only active internal sales, operations, or design employees can be invited")

    await db.execute(delete(CustomerAccessGrant).where(CustomerAccessGrant.customer_id == id))
    await db.flush()
    for employee_id in requested_ids:
        db.add(CustomerAccessGrant(
            customer_id=id,
            employee_id=employee_id,
            granted_by_id=str(admin.id),
            granted_by_name=admin.name or admin.email,
        ))
    await db.commit()

    employee_by_id = {employee.id: employee for employee in employees}
    return CustomerAccessResponse(
        customer_id=id,
        members=[
            CustomerAccessMember(
                employee_id=employee_by_id[employee_id].id,
                name=employee_by_id[employee_id].name,
                role=employee_by_id[employee_id].role,
                department=employee_by_id[employee_id].department,
                employee_code=employee_by_id[employee_id].employee_code,
            )
            for employee_id in requested_ids
        ],
    )


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
        await _require_customer_write(db, current_user, "customer_create")
        result = await service.create(_assigned_to_current_user(data.model_dump(), current_user), commit=False)
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create customers")
        await _ensure_owner_visibility_grant(db, result, current_user)
        await _auto_assign_created_customer(db, result, current_user)
        await db.commit()
        await db.refresh(result)
        
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
    await _require_customer_write(db, current_user, "customer_create")
    if len(request.projects) > 12:
        raise HTTPException(status_code=400, detail="单个客户最多维护12个合作项目")
    service = CustomersService(db)
    try:
        _validate_customer_project_consistency(request.customer.status, request.projects)
        customer = await service.create(
            _assigned_to_current_user(request.customer.model_dump(), current_user),
            commit=False,
        )
        await _ensure_owner_visibility_grant(db, customer, current_user)
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
        await _auto_assign_created_customer(
            db,
            customer,
            current_user,
            projects=request.projects,
            partner_id=request.commission_partner_id,
            effective_from=request.commission_effective_from,
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
        await _require_customer_write(db, current_user, "customer_create")
        for item_data in request.items:
            result = await service.create(_assigned_to_current_user(item_data.model_dump(), current_user), commit=False)
            if result:
                await _ensure_owner_visibility_grant(db, result, current_user)
                await _auto_assign_created_customer(db, result, current_user)
                results.append(result)
        await db.commit()
        for result in results:
            await db.refresh(result)
        
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
        await _require_customer_write(db, current_user, "customer_edit")
        for item in request.items:
            if item.updates.status == "lost":
                await _ensure_no_active_projects_before_direct_loss(db, item.id)
            # Only include non-None values for partial updates
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            update_dict = _strip_owner_fields_for_non_admin(update_dict, current_user)
            result = await service.update(item.id, update_dict, scope_user=current_user, commit=False)
            if result:
                if _is_admin_role(current_user) and CUSTOMER_OWNER_FIELDS.intersection(update_dict):
                    await _ensure_owner_visibility_grant(db, result, current_user)
                results.append(result)
        await db.commit()
        for result in results:
            await db.refresh(result)

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
        await _require_customer_write(db, current_user, "customer_edit")
        if data.status == "lost":
            await _ensure_no_active_projects_before_direct_loss(db, id)
        # Only include non-None values for partial updates
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        update_dict = _strip_owner_fields_for_non_admin(update_dict, current_user)
        owner_changed = _is_admin_role(current_user) and bool(CUSTOMER_OWNER_FIELDS.intersection(update_dict))
        result = await service.update(id, update_dict, scope_user=current_user, commit=not owner_changed)
        if not result:
            logger.warning(f"Customers with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Customers not found")
        
        if owner_changed:
            await _ensure_owner_visibility_grant(db, result, current_user)
            await db.commit()
            await db.refresh(result)
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
    await _require_customer_write(db, current_user, "customer_edit")
    if len(request.projects) > 12:
        raise HTTPException(status_code=400, detail="单个客户最多维护12个合作项目")
    service = CustomersService(db)
    try:
        _validate_customer_project_consistency(request.customer.status, request.projects)
        update_dict = {key: value for key, value in request.customer.model_dump().items() if value is not None}
        update_dict = _strip_owner_fields_for_non_admin(update_dict, current_user)
        customer = await service.update(id, update_dict, scope_user=current_user, commit=False)
        if not customer:
            raise HTTPException(status_code=404, detail="Customers not found")
        if _is_admin_role(current_user) and CUSTOMER_OWNER_FIELDS.intersection(update_dict):
            await _ensure_owner_visibility_grant(db, customer, current_user)
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
    http_request: Request,
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple customerss by their IDs"""
    logger.debug(f"Batch deleting {len(request.ids)} customerss")
    
    service = CustomersService(db)
    deleted_count = 0
    
    try:
        customers = []
        for item_id in request.ids:
            customer = await service.get_by_id(item_id, scope_user=current_user)
            if not customer:
                raise HTTPException(status_code=404, detail="Customers not found")
            customers.append(customer)

        audit_service = Operation_logsService(db)
        for customer in customers:
            await audit_service.create(
                build_server_operation_log_data(
                    current_user=current_user,
                    request=http_request,
                    customer_id=customer.id,
                    action_type="delete_customer",
                    action_detail=f"删除客户: {customer.business_name}"[:2000],
                ),
                user_id=str(current_user.id),
                commit=False,
            )
        for item_id in request.ids:
            success = await service.delete(item_id, scope_user=current_user, commit=False)
            if success:
                deleted_count += 1
        await db.commit()
        
        logger.info(f"Batch deleted {deleted_count} customerss successfully")
        return {"message": f"Successfully deleted {deleted_count} customerss", "deleted_count": deleted_count}
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch delete: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


@router.delete("/{id}")
async def delete_customers(
    id: int,
    request: Request,
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single customers by ID"""
    logger.debug(f"Deleting customers with id: {id}")
    
    service = CustomersService(db)
    try:
        customer = await service.get_by_id(id, scope_user=current_user)
        if not customer:
            logger.warning(f"Customers with id {id} not found for deletion")
            raise HTTPException(status_code=404, detail="Customers not found")

        await Operation_logsService(db).create(
            build_server_operation_log_data(
                current_user=current_user,
                request=request,
                customer_id=customer.id,
                action_type="delete_customer",
                action_detail=f"删除客户: {customer.business_name}"[:2000],
            ),
            user_id=str(current_user.id),
            commit=False,
        )
        success = await service.delete(id, scope_user=current_user, commit=False)
        if not success:  # Defensive: the preflight lookup above already found it.
            raise HTTPException(status_code=404, detail="Customers not found")
        await db.commit()

        logger.info(f"Customers {id} deleted successfully")
        return {"message": "Customers deleted successfully", "id": id}
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting customers {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
