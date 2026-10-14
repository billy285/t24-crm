import json
import logging
from typing import List, Literal, Optional
from types import SimpleNamespace

from datetime import datetime, date, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_admin_user, get_current_user
from schemas.auth import UserResponse
from services.customers import CustomersService
from services.customer_scope import ensure_customer_access
from models.customers import Customers
from models.customer_access_grants import CustomerAccessGrant, CustomerAccessAudit
from models.employees import Employees
from models.management_decisions import BusinessLine, CustomerEngagement, ProductCatalog
from services.commissions import auto_assign_new_customer
from services.management_decision_workflow import save_customer_classification_review
from services.operation_logs import Operation_logsService, build_server_operation_log_data
from services.role_permissions import require_any_page_permission, require_button_permission
from services.phone_numbers import parse_phone_number
from services.customer_record_audit import record_customer_change
from services.customer_permissions import (
    GRANT_FIELDS, MODULES, customer_permissions_for_rows, get_customer_owner_user,
    get_customer_permissions, grant_snapshot, is_customer_owner, preview_customer_permissions,
    DEFAULT_INVITATION_SCOPES, SHARED_BASIC_FIELDS, is_active_customer_invitation,
)

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/customers", tags=["customers"], dependencies=[Depends(get_current_user)])

CUSTOMER_OWNER_FIELDS = {"sales_person", "sales_employee_id"}
ACTIVE_PROJECT_STATUSES = {"pending_setup", "trial", "active_paid", "at_risk", "paused", "pending_stop", "reactivated"}


def _validate_customer_phone(payload: dict, existing: Customers | None = None) -> None:
    phone = payload.get("phone", existing.phone if existing else None)
    country = payload.get("country", existing.country if existing else None)
    if existing and phone == existing.phone and country == existing.country:
        return
    result = parse_phone_number(phone, country)
    if not result.is_valid:
        raise HTTPException(status_code=400, detail=result.reason)


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
    if not is_customer_owner(user) and data.get("notes"):
        raise HTTPException(status_code=403, detail="历史备注仅老板管理；请使用已授权的业务记录栏目")
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
    # Historical notes may include financial/private details; sharing basic
    # information must not allow reading or overwriting them.
    if not is_customer_owner(user) and "notes" in update_dict:
        raise HTTPException(status_code=403, detail="历史备注仅老板管理")
    return update_dict


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
    effective_permissions: dict = Field(default_factory=dict)

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


class CustomerAccessAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: int = Field(gt=0)
    access_level: Literal["none", "read_only", "read_write"] = "read_only"
    scopes: dict[Literal["basic", "contacts", "followups", "opportunities", "delivery", "renewals", "deals", "materials"], Literal["none", "read_only", "read_write"]] = Field(default_factory=lambda: dict(DEFAULT_INVITATION_SCOPES))
    finance_access: Literal["none"] = "none"
    can_export: bool = False
    can_delete: bool = False
    can_reassign: bool = False

    @model_validator(mode="after")
    def no_hidden_permissions(self):
        self.scopes = {name: self.scopes.get(name, "none") for name in MODULES}
        if self.access_level == "none":
            self.scopes = {name: "none" for name in MODULES}
            self.finance_access = "none"
            self.can_export = self.can_delete = self.can_reassign = False
        if self.access_level != "read_write":
            self.can_delete = self.can_reassign = False
        return self


class CustomerAccessMember(BaseModel):
    employee_id: int
    name: str
    role: str
    access_level: str
    scopes: dict = Field(default_factory=dict)
    finance_access: str = "none"
    can_export: bool = False
    can_delete: bool = False
    can_reassign: bool = False
    department: Optional[str] = None
    employee_code: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    explicit: bool = False
    invitation_source: str
    invitation_status: str
    invited_at: Optional[str] = None
    invited_by_id: Optional[str] = None
    invited_by_name: Optional[str] = None
    effective_permissions: dict = Field(default_factory=dict)


class CustomerAccessResponse(BaseModel):
    customer_id: int
    members: List[CustomerAccessMember]
    eligible_employees: list[dict] = Field(default_factory=list)
    pending_legacy_members: List[CustomerAccessMember] = Field(default_factory=list)
    owner: Optional[dict] = None


class CustomerFinanceAccessInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    finance_access: Literal["none", "status", "receipts", "profit"]


class CustomerAccessUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    members: List[CustomerAccessAssignment] = Field(default_factory=list, max_length=200)
    employee_ids: Optional[List[int]] = None


class CustomerAccessBulkUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_ids: List[int] = Field(min_length=1, max_length=200)
    operation: Literal["upsert", "remove"]
    members: List[CustomerAccessAssignment] = Field(min_length=1, max_length=100)


class CustomerAccessBulkResponse(BaseModel):
    customer_count: int
    member_count: int
    updated_grants: int


class CustomerPrivateNoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    private_notes: Optional[str] = Field(default=None, max_length=30000)


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




def _actor_name(user: UserResponse) -> str:
    return user.name or user.email or "管理员"


def _access_assignment_map(data: CustomerAccessUpdateRequest | CustomerAccessBulkUpdateRequest) -> dict[int, dict]:
    assignments = {item.employee_id: item.model_dump() for item in data.members}
    if len(assignments) != len(data.members):
        raise HTTPException(status_code=400, detail="同一员工不能重复设置权限")
    if isinstance(data, CustomerAccessUpdateRequest) and data.employee_ids is not None:
        for employee_id in data.employee_ids:
            assignments.setdefault(employee_id, CustomerAccessAssignment(employee_id=employee_id).model_dump())
    return assignments


async def _eligible_access_employees(db: AsyncSession, employee_ids: set[int], *,
                                    existing: dict[int, dict] | None = None,
                                    assignments: dict[int, dict] | None = None,
                                    removing: bool = False) -> dict[int, Employees]:
    employees = list((await db.execute(
        select(Employees).where(
            Employees.id.in_(employee_ids),
            Employees.role.in_(("admin", "finance", "sales", "sales_manager", "ops", "operations", "design")),
        )
    )).scalars().all()) if employee_ids else []
    def allowed(employee):
        if employee.status in {"active", "probation"}:
            return True
        previous = (existing or {}).get(employee.id)
        requested = (assignments or {}).get(employee.id)
        # A stopped team member must not prevent editing other members. Keep
        # exactly the existing rule or remove/deny it; never grant an upgrade.
        return previous is not None and (removing or requested == {key: previous[key] for key in ("employee_id", *GRANT_FIELDS)} or (requested or {}).get("access_level") == "none")
    employee_by_id = {employee.id: employee for employee in employees if allowed(employee)}
    if set(employee_by_id) != employee_ids:
        raise HTTPException(status_code=400, detail="只能设置在职的内部员工；老板权限及外部渠道不在客户共享范围内")
    return employee_by_id


async def _access_response(db: AsyncSession, customer: Customers) -> CustomerAccessResponse:
    grants = {row.employee_id: row for row in (await db.execute(
        select(CustomerAccessGrant).where(CustomerAccessGrant.customer_id == customer.id)
    )).scalars()}
    employees = list((await db.execute(select(Employees).order_by(Employees.name))).scalars())
    members, pending, eligible, owner = [], [], [], None
    for employee in employees:
        user = SimpleNamespace(id=str(employee.id), role=employee.role, name=employee.name)
        base = {"employee_id": employee.id, "name": employee.name, "role": employee.role,
                "email": employee.email, "status": employee.status, "department": employee.department,
                "employee_code": employee.employee_code}
        if employee.role == "super_admin":
            if owner is None:
                owner = {"id": employee.id, **base}
            continue
        grant = grants.get(employee.id)
        permission = (await customer_permissions_for_rows(db, user, [customer]))[customer.id]
        employment_active = employee.status in {"active", "probation"}
        internal = employee.role in {"admin", "finance", "sales", "sales_manager", "ops", "operations", "design"}
        if employment_active and internal:
            eligible.append({"id": employee.id, **base, "effective_permissions": permission})
        if grant is not None:
            member = CustomerAccessMember(**{**grant_snapshot(grant), **base},
                explicit=is_active_customer_invitation(grant), effective_permissions=permission)
            if is_active_customer_invitation(grant) and employment_active and internal:
                members.append(member)
            elif grant.invitation_status == "pending_review":
                pending.append(member)
    return CustomerAccessResponse(customer_id=customer.id, members=members, eligible_employees=eligible,
                                  pending_legacy_members=pending, owner=owner)


def _set_owner_invitation(grant: CustomerAccessGrant, assignment: dict, actor: UserResponse):
    was_active = is_active_customer_invitation(grant)
    separate_finance = grant.finance_access if was_active else "none"
    for key in GRANT_FIELDS:
        setattr(grant, key, assignment[key])
    grant.finance_access = separate_finance
    grant.granted_by_id, grant.granted_by_name = str(actor.id), _actor_name(actor)
    if assignment["access_level"] == "none":
        _revoke_invitation(grant, actor)
        return
    if not was_active:
        grant.invited_at = datetime.now(timezone.utc)
        grant.invited_by_id, grant.invited_by_name = str(actor.id), _actor_name(actor)
    grant.invitation_source, grant.invitation_status = "owner_invitation", "active"


def _revoke_invitation(grant: CustomerAccessGrant, actor: UserResponse):
    grant.invitation_status = "revoked"
    grant.access_level, grant.finance_access = "none", "none"
    grant.scopes = {name: "none" for name in MODULES}
    grant.can_export = grant.can_delete = grant.can_reassign = False
    grant.granted_by_id, grant.granted_by_name = str(actor.id), _actor_name(actor)


async def _grant_snapshots(db: AsyncSession, customer_id: int) -> list[dict]:
    return [grant_snapshot(row) for row in (await db.execute(select(CustomerAccessGrant).where(
        CustomerAccessGrant.customer_id == customer_id).order_by(CustomerAccessGrant.employee_id))).scalars()]


async def _audit_grants(db: AsyncSession, customer_id: int, actor: UserResponse, before: list[dict]):
    after = await _grant_snapshots(db, customer_id)
    if before != after:
        db.add(CustomerAccessAudit(customer_id=customer_id, actor_id=str(actor.id), actor_name=_actor_name(actor), before=before, after=after))


def _shared_package_labels(raw: str | None, selected: str | None) -> str | None:
    """Legacy snapshots can be arbitrary JSON: share labels, never metadata."""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict):
        return None
    selected_keys = {key.strip() for key in (selected or "").split(",") if key.strip()}
    labels = {}
    for key, item in value.items():
        label = item if isinstance(item, str) else item.get("label") if isinstance(item, dict) else None
        if key in selected_keys and isinstance(label, str):
            labels[key] = label
    return json.dumps(labels, ensure_ascii=False)


def _shared_platform_names(raw: str | None) -> str | None:
    from services.customer_permissions import shared_platform_names
    return shared_platform_names(raw)


async def _customer_responses(db: AsyncSession, user: UserResponse, rows: list[Customers]) -> list[dict]:
    permissions = await customer_permissions_for_rows(db, user, rows)
    responses = []
    for row in rows:
        response = CustomersResponse.model_validate(row).model_dump()
        effective = permissions[row.id]
        if not is_customer_owner(user):
            response = {key: value if key in SHARED_BASIC_FIELDS else None for key, value in response.items()}
            response["interested_packages_snapshot"] = _shared_package_labels(row.interested_packages_snapshot, row.interested_packages)
            response["selected_platforms"] = _shared_platform_names(row.selected_platforms)
        if not effective["modules"]["basic"]["read"]:
            response = {key: (value if key in {"id", "business_name"} else "" if key in {"phone", "contact_name"} else None)
                        for key, value in response.items()}
        response["effective_permissions"] = effective
        responses.append(response)
    return responses


async def _check_owner_update(db: AsyncSession, user: UserResponse, customer: Customers, updates: dict):
    if any(key in updates and updates[key] != getattr(customer, key) for key in CUSTOMER_OWNER_FIELDS):
        await ensure_customer_access(db, user, customer.id, write=True, action="reassign")
        await require_button_permission(db, user, "customer_assign", admin_override=True)


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
        result["items"] = await _customer_responses(db, current_user, result["items"])
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
        result["items"] = await _customer_responses(db, current_user, result["items"])
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
        
        return (await _customer_responses(db, current_user, [result]))[0]
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
    await ensure_customer_access(db, current_user, id, module="delivery")
    rows = (await db.execute(
        select(CustomerEngagement, BusinessLine, ProductCatalog)
        .join(BusinessLine, BusinessLine.id == CustomerEngagement.business_line_id)
        .join(ProductCatalog, ProductCatalog.id == CustomerEngagement.product_id)
        .where(CustomerEngagement.customer_id == id)
        .order_by(CustomerEngagement.id.asc())
    )).all()
    items = [{
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
        } for engagement, line, product in rows]
    if not is_customer_owner(current_user):
        allowed = {"id", "business_line_code", "business_line_name", "product_code", "product_name",
                   "package_name", "status", "billing_cycle", "owner_employee_id", "sales_employee_id", "stopped_at"}
        items = [{key: ("active" if key == "status" and value == "active_paid" else value)
                  for key, value in item.items() if key in allowed} for item in items]
    return {"items": items, "total": len(rows)}


@router.get("/{id}/access", response_model=CustomerAccessResponse)
async def get_customer_access(id: int, _admin: UserResponse = Depends(get_customer_owner_user), db: AsyncSession = Depends(get_db)):
    customer = await db.get(Customers, id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return await _access_response(db, customer)


@router.put("/{id}/access", response_model=CustomerAccessResponse)
async def replace_customer_access(id: int, data: CustomerAccessUpdateRequest, admin: UserResponse = Depends(get_customer_owner_user), db: AsyncSession = Depends(get_db)):
    customer = (await db.execute(select(Customers).where(Customers.id == id).with_for_update())).scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    assignments = _access_assignment_map(data)
    before = await _grant_snapshots(db, id)
    await _eligible_access_employees(db, set(assignments), existing={row["employee_id"]:row for row in before}, assignments=assignments)
    try:
        existing = {row.employee_id: row for row in (await db.execute(select(CustomerAccessGrant).where(CustomerAccessGrant.customer_id == id))).scalars()}
        for employee_id, grant in existing.items():
            if is_active_customer_invitation(grant) and employee_id not in assignments:
                _revoke_invitation(grant, admin)
        for employee_id, assignment in assignments.items():
            grant = existing.get(employee_id)
            if grant is None:
                grant = CustomerAccessGrant(customer_id=id, employee_id=employee_id)
                db.add(grant)
            _set_owner_invitation(grant, assignment, admin)
        await db.flush()
        await _audit_grants(db, id, admin, before)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return await _access_response(db, customer)


@router.put("/{id}/access/{employee_id}/finance")
async def set_customer_finance_access(id: int, employee_id: int, data: CustomerFinanceAccessInput,
                                     owner: UserResponse = Depends(get_customer_owner_user), db: AsyncSession = Depends(get_db)):
    customer = (await db.execute(select(Customers).where(Customers.id == id).with_for_update())).scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    before = await _grant_snapshots(db, id)
    grant = (await db.execute(select(CustomerAccessGrant).where(CustomerAccessGrant.customer_id == id,
                CustomerAccessGrant.employee_id == employee_id))).scalar_one_or_none()
    if not is_active_customer_invitation(grant):
        raise HTTPException(status_code=409, detail="请先由老板明确邀请该员工，再单独设置财务权限")
    await _eligible_access_employees(db, {employee_id})
    try:
        grant.finance_access = data.finance_access
        await db.flush()
        await _audit_grants(db, id, owner, before)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return await _access_response(db, customer)


@router.post("/{id}/access/preview")
async def preview_customer_access(id: int, data: CustomerAccessAssignment, _owner: UserResponse = Depends(get_customer_owner_user), db: AsyncSession = Depends(get_db)):
    customer = await db.get(Customers, id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    employee = (await _eligible_access_employees(db, {data.employee_id}))[data.employee_id]
    assignment = data.model_dump()
    current = (await db.execute(select(CustomerAccessGrant).where(CustomerAccessGrant.customer_id == id,
              CustomerAccessGrant.employee_id == data.employee_id))).scalar_one_or_none()
    if data.access_level != "none" and is_active_customer_invitation(current):
        assignment["finance_access"] = current.finance_access
    permissions = await preview_customer_permissions(db, employee, customer, assignment)
    visible = [name for name, value in permissions["modules"].items() if value["read"]]
    if permissions["finance_access"] != "none":
        visible.append("finance:" + permissions["finance_access"])
    return {"employee_id": data.employee_id, "effective_permissions": permissions, "visible_sections": visible}


@router.get("/{id}/access/history")
async def customer_access_history(id: int, _owner: UserResponse = Depends(get_customer_owner_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(CustomerAccessAudit).where(CustomerAccessAudit.customer_id == id).order_by(CustomerAccessAudit.id.desc()).limit(100))).scalars()
    return {"items": [{"id": row.id, "actor_id": row.actor_id, "actor_name": row.actor_name, "created_at": row.created_at, "before": row.before, "after": row.after} for row in rows]}


@router.get("/{id}/record-audits")
async def customer_record_audits(id: int, _owner: UserResponse = Depends(get_customer_owner_user), db: AsyncSession = Depends(get_db)):
    from models.customer_record_audits import CustomerRecordAudit
    rows = (await db.execute(select(CustomerRecordAudit).where(CustomerRecordAudit.customer_id == id).order_by(CustomerRecordAudit.id.desc()).limit(100))).scalars()
    return {"items": [{"id": row.id, "module": row.module, "entity_type": row.entity_type, "entity_id": row.entity_id, "actor_id": row.actor_id, "actor_name": row.actor_name, "action": row.action, "created_at": row.created_at, "before": row.before, "after": row.after} for row in rows]}


@router.get("/{id}/private-note")
async def get_customer_private_note(id: int, _owner: UserResponse = Depends(get_customer_owner_user), db: AsyncSession = Depends(get_db)):
    customer = await db.get(Customers, id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return {"customer_id": id, "private_notes": customer.private_notes}


@router.put("/{id}/private-note")
async def update_customer_private_note(id: int, data: CustomerPrivateNoteInput, owner: UserResponse = Depends(get_customer_owner_user), db: AsyncSession = Depends(get_db)):
    customer = (await db.execute(select(Customers).where(Customers.id == id).with_for_update())).scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    customer.private_notes = data.private_notes
    # Keep sensitive contents only in owner-only storage, never public logs.
    from models.customer_record_audits import CustomerRecordAudit
    db.add(CustomerRecordAudit(customer_id=id, module="private_notes", entity_type="customers", entity_id=id,
        actor_id=str(owner.id), actor_name=_actor_name(owner), action="update", before={"private_notes": "[redacted]"}, after={"private_notes": "[redacted]"}))
    await db.commit()
    return {"customer_id": id, "private_notes": customer.private_notes}


@router.post("/access/bulk-update", response_model=CustomerAccessBulkResponse)
async def bulk_update_customer_access(data: CustomerAccessBulkUpdateRequest, admin: UserResponse = Depends(get_customer_owner_user), db: AsyncSession = Depends(get_db)):
    customer_ids = sorted(set(data.customer_ids))
    customers = set((await db.execute(select(Customers.id).where(Customers.id.in_(customer_ids)).order_by(Customers.id).with_for_update())).scalars())
    if customers != set(customer_ids):
        raise HTTPException(status_code=404, detail="部分客户不存在，请刷新列表后重试")
    assignments = _access_assignment_map(data)
    updated_grants = 0
    try:
        for customer_id in customer_ids:
            before = await _grant_snapshots(db, customer_id)
            await _eligible_access_employees(db, set(assignments), existing={row["employee_id"]:row for row in before}, assignments=assignments, removing=data.operation == "remove")
            existing = {row.employee_id: row for row in (await db.execute(select(CustomerAccessGrant).where(CustomerAccessGrant.customer_id == customer_id))).scalars()}
            for employee_id, assignment in assignments.items():
                grant = existing.get(employee_id)
                if data.operation == "remove":
                    if grant:
                        _revoke_invitation(grant, admin)
                        updated_grants += 1
                else:
                    if not grant:
                        grant = CustomerAccessGrant(customer_id=customer_id, employee_id=employee_id)
                        db.add(grant)
                    _set_owner_invitation(grant, assignment, admin)
                    updated_grants += 1
            await db.flush()
            await _audit_grants(db, customer_id, admin, before)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return CustomerAccessBulkResponse(customer_count=len(customer_ids), member_count=len(assignments), updated_grants=updated_grants)


@router.post("/access/export")
async def export_customers(data: CustomersBatchDeleteRequest, request: Request, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _require_customer_page(db, user)
    await require_button_permission(db, user, "customer_export", admin_override=True)
    if not data.ids or len(data.ids) > 2000:
        raise HTTPException(status_code=400, detail="请选择 1 至 2000 位客户")
    rows = []
    for customer_id in sorted(set(data.ids)):
        rows.append(await ensure_customer_access(db, user, customer_id, action="export"))
    response = await _customer_responses(db, user, rows)
    await Operation_logsService(db).create(build_server_operation_log_data(current_user=user, request=request,
        action_type="export_data", action_detail=f"导出已授权客户 {len(rows)} 位（客户ID：{','.join(str(row.id) for row in rows)})"[:2000]), user_id=str(user.id), commit=False)
    await db.commit()
    return {"items": response, "total": len(response)}


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
        _validate_customer_phone(data.model_dump())
        result = await service.create(_assigned_to_current_user(data.model_dump(), current_user), commit=False)
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create customers")

        await _auto_assign_created_customer(db, result, current_user)
        await db.commit()
        await db.refresh(result)
        
        logger.info(f"Customers created successfully with id: {result.id}")
        return (await _customer_responses(db, current_user, [result]))[0]
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
    if not is_customer_owner(current_user) and (request.projects or request.commission_partner_id is not None or request.commission_effective_from is not None):
        raise HTTPException(status_code=403, detail="合作项目及分润归属配置仅老板可以设置")
    if len(request.projects) > 12:
        raise HTTPException(status_code=400, detail="单个客户最多维护12个合作项目")
    service = CustomersService(db)
    try:
        _validate_customer_project_consistency(request.customer.status, request.projects)
        _validate_customer_phone(request.customer.model_dump())
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
        return (await _customer_responses(db, current_user, [customer]))[0]
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
            _validate_customer_phone(item_data.model_dump())
        for item_data in request.items:
            result = await service.create(_assigned_to_current_user(item_data.model_dump(), current_user), commit=False)
            if result:

                await _auto_assign_created_customer(db, result, current_user)
                results.append(result)
        await db.commit()
        for result in results:
            await db.refresh(result)
        
        logger.info(f"Batch created {len(results)} customerss successfully")
        return await _customer_responses(db, current_user, results)
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
            existing = await ensure_customer_access(db, current_user, item.id, write=True)
            _validate_customer_phone(item.updates.model_dump(exclude_none=True), existing)
            await _check_owner_update(db, current_user, existing, item.updates.model_dump(exclude_none=True))
        for item in request.items:
            existing = await ensure_customer_access(db, current_user, item.id, write=True)
            if item.updates.status == "lost":
                await _ensure_no_active_projects_before_direct_loss(db, item.id)
            # Only include non-None values for partial updates
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            update_dict = _strip_owner_fields_for_non_admin(update_dict, current_user)
            record_customer_change(db, current_user, existing, "basic", changes=update_dict)
            result = await service.update(item.id, update_dict, scope_user=current_user, commit=False)
            if result:
                results.append(result)
        await db.commit()
        for result in results:
            await db.refresh(result)

        logger.info(f"Batch updated {len(results)} customerss successfully")
        return await _customer_responses(db, current_user, results)
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
        existing = await ensure_customer_access(db, current_user, id, write=True)
        await _check_owner_update(db, current_user, existing, data.model_dump(exclude_none=True))
        _validate_customer_phone(data.model_dump(exclude_none=True), existing)
        if data.status == "lost":
            await _ensure_no_active_projects_before_direct_loss(db, id)
        # Only include non-None values for partial updates
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        update_dict = _strip_owner_fields_for_non_admin(update_dict, current_user)
        record_customer_change(db, current_user, existing, "basic", changes=update_dict)
        result = await service.update(id, update_dict, scope_user=current_user, commit=False)
        if not result:
            logger.warning(f"Customers with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Customers not found")
        
        await db.commit()
        await db.refresh(result)
        logger.info(f"Customers {id} updated successfully")
        return (await _customer_responses(db, current_user, [result]))[0]
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
    existing = await ensure_customer_access(db, current_user, id, write=True)
    await _check_owner_update(db, current_user, existing, request.customer.model_dump(exclude_none=True))
    if request.projects:
        if not is_customer_owner(current_user):
            raise HTTPException(status_code=403, detail="合作项目及财务来源配置仅老板可以设置")
        await ensure_customer_access(db, current_user, id, write=True, module="delivery")
        await require_button_permission(db, current_user, "task_edit", admin_override=True)
        # This composite endpoint can also change project owners and financial
        # source links. Keep those high-impact actions separately authorized.
        await ensure_customer_access(db, current_user, id, write=True, module="delivery", action="reassign")
    _validate_customer_phone(request.customer.model_dump(exclude_none=True), existing)
    if len(request.projects) > 12:
        raise HTTPException(status_code=400, detail="单个客户最多维护12个合作项目")
    service = CustomersService(db)
    try:
        _validate_customer_project_consistency(request.customer.status, request.projects)
        update_dict = {key: value for key, value in request.customer.model_dump().items() if value is not None}
        update_dict = _strip_owner_fields_for_non_admin(update_dict, current_user)
        record_customer_change(db, current_user, existing, "basic", changes=update_dict)
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
        return (await _customer_responses(db, current_user, [customer]))[0]
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
    current_user: UserResponse = Depends(get_customer_owner_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple customerss by their IDs"""
    logger.debug(f"Batch deleting {len(request.ids)} customerss")
    
    service = CustomersService(db)
    deleted_count = 0
    
    try:
        customers = []
        for item_id in request.ids:
            customer = await ensure_customer_access(db, current_user, item_id, write=True, action="delete")
            customers.append(customer)

        audit_service = Operation_logsService(db)
        for customer in customers:
            record_customer_change(db, current_user, customer, "basic", deleted=True)
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
    current_user: UserResponse = Depends(get_customer_owner_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single customers by ID"""
    logger.debug(f"Deleting customers with id: {id}")
    
    service = CustomersService(db)
    try:
        customer = await ensure_customer_access(db, current_user, id, write=True, action="delete")
        record_customer_change(db, current_user, customer, "basic", deleted=True)

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
