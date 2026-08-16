import json
import logging
from typing import Dict, List, Literal, Optional, Sequence
from zoneinfo import ZoneInfo

from datetime import datetime, date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_admin_user, get_current_user
from models.commissions import SalesPartner
from models.customers import Customers
from models.employees import Employees
from models.management_decisions import CustomerEngagement
from models.service_progresses import Service_progresses
from models.service_tasks import Service_tasks
from models.tasks import Tasks
from schemas.auth import UserResponse
from services.commissions import transfer_partner_attributions_to_direct
from services.employees import EmployeesService

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/employees", tags=["employees"], dependencies=[Depends(get_current_user)])


ACTIVE_EMPLOYEE_STATUSES = {"active", "probation"}
TERMINAL_EMPLOYEE_STATUSES = {"disabled", "inactive", "resigned", "terminated"}
# `disabled` is an emergency login lock and may intentionally retain work
# ownership for later reactivation. Formal offboarding states require handoff.
OWNERSHIP_HANDOFF_STATUSES = {"inactive", "resigned", "terminated"}
CLOSED_TASK_STATUSES = {"completed", "cancelled"}
CLOSED_SERVICE_STAGES = {"ended", "stopped", "completed", "cancelled"}
EXTERNAL_PARTNER_TYPES = {"agency", "partner"}
BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")
EmployeeStatus = Literal["active", "probation", "disabled", "inactive", "resigned", "terminated"]


def _employee_update_payload(data: "EmployeesUpdateData") -> dict:
    """Preserve the existing partial-update contract while ignoring omitted/null fields."""
    return data.model_dump(exclude_unset=True, exclude_none=True)


async def _actor_employee_id(db: AsyncSession, admin: UserResponse) -> Optional[int]:
    """Resolve both employee-JWT numeric IDs and legacy platform identities."""
    try:
        numeric_id = int(admin.id)
    except (TypeError, ValueError):
        numeric_id = None
    if numeric_id is not None and await db.get(Employees, numeric_id):
        return numeric_id

    identity_filters = [Employees.user_id == str(admin.id)]
    if admin.email:
        identity_filters.append(func.lower(Employees.email) == admin.email.strip().lower())
    matches = list((await db.scalars(
        select(Employees).where(or_(*identity_filters)).limit(2)
    )).all())
    return matches[0].id if len(matches) == 1 else None


async def _load_employee_targets(
    db: AsyncSession,
    ids: Sequence[int],
) -> Dict[int, Employees]:
    """Load every target before mutations so batch requests cannot partially apply."""
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=400, detail="批量请求不能重复包含同一员工")
    if not ids:
        return {}
    rows = list((await db.scalars(select(Employees).where(Employees.id.in_(ids)))).all())
    by_id = {row.id: row for row in rows}
    missing = [employee_id for employee_id in ids if employee_id not in by_id]
    if missing:
        raise HTTPException(status_code=404, detail=f"员工不存在: {', '.join(map(str, missing))}")
    return by_id


async def _linked_external_partner(
    db: AsyncSession,
    employee_id: int,
) -> Optional[SalesPartner]:
    return await db.scalar(
        select(SalesPartner).where(
            SalesPartner.employee_id == employee_id,
            SalesPartner.partner_type.in_(EXTERNAL_PARTNER_TYPES),
        ).order_by(SalesPartner.id)
    )


async def _assert_no_active_employee_ownership(
    db: AsyncSession,
    employee: Employees,
) -> None:
    """Fail closed until customer, task and delivery ownership has been handed over."""
    employee_name = str(employee.name or "").strip()
    id_or_legacy_name = or_(
        Customers.sales_employee_id == employee.id,
        and_(Customers.sales_employee_id.is_(None), Customers.sales_person == employee_name),
    )
    customer_count = int(await db.scalar(select(func.count(Customers.id)).where(id_or_legacy_name)) or 0)

    active_task_filter = or_(Tasks.status.is_(None), ~Tasks.status.in_(CLOSED_TASK_STATUSES))
    task_owner_filter = or_(
        Tasks.assignee_id == employee.id,
        and_(Tasks.assignee_id.is_(None), Tasks.assignee_name == employee_name),
    )
    task_count = int(await db.scalar(
        select(func.count(Tasks.id)).where(task_owner_filter, active_task_filter)
    ) or 0)

    active_service_task_filter = or_(
        Service_tasks.status.is_(None),
        ~Service_tasks.status.in_(CLOSED_TASK_STATUSES),
    )
    service_task_count = int(await db.scalar(
        select(func.count(Service_tasks.id)).where(
            Service_tasks.assignee_name == employee_name,
            active_service_task_filter,
        )
    ) or 0)

    active_progress_filter = or_(
        Service_progresses.service_stage.is_(None),
        ~Service_progresses.service_stage.in_(CLOSED_SERVICE_STAGES),
    )
    progress_owner_filter = or_(
        Service_progresses.sales_person == employee_name,
        Service_progresses.ops_person == employee_name,
        Service_progresses.design_person == employee_name,
        Service_progresses.issue_owner == employee_name,
    )
    progress_count = int(await db.scalar(
        select(func.count(Service_progresses.id)).where(progress_owner_filter, active_progress_filter)
    ) or 0)

    active_engagement_filter = ~CustomerEngagement.status.in_({"stopped", "completed"})
    engagement_count = int(await db.scalar(
        select(func.count(CustomerEngagement.id)).where(
            or_(
                CustomerEngagement.owner_employee_id == employee.id,
                CustomerEngagement.sales_employee_id == employee.id,
            ),
            active_engagement_filter,
        )
    ) or 0)

    ownership = {
        "客户": customer_count,
        "待办任务": task_count,
        "交付任务": service_task_count,
        "服务进度": progress_count,
        "在办项目": engagement_count,
    }
    remaining = [f"{label} {count}" for label, count in ownership.items() if count]
    if remaining:
        raise HTTPException(
            status_code=409,
            detail=f"员工「{employee.name}」仍有未交接的业务（{'、'.join(remaining)}），请先完成交接",
        )


async def _assert_super_admin_continuity(
    db: AsyncSession,
    *,
    updates: Optional[Dict[int, dict]] = None,
    deleted_ids: Optional[set[int]] = None,
) -> None:
    """Keep both a super-admin record and an active super-admin login after the request."""
    updates = updates or {}
    deleted_ids = deleted_ids or set()
    rows = list((await db.scalars(select(Employees))).all())
    before_roles = [row for row in rows if row.role == "super_admin"]
    before_active = [row for row in before_roles if row.status in ACTIVE_EMPLOYEE_STATUSES]
    if not before_roles:
        return

    remaining_roles = 0
    remaining_active = 0
    for row in rows:
        if row.id in deleted_ids:
            continue
        patch = updates.get(row.id, {})
        role = patch.get("role", row.role)
        status = patch.get("status", row.status)
        if role == "super_admin":
            remaining_roles += 1
            if status in ACTIVE_EMPLOYEE_STATUSES:
                remaining_active += 1

    if remaining_roles == 0:
        raise HTTPException(status_code=409, detail="不能删除或降级最后一个超级管理员")
    if before_active and remaining_active == 0:
        raise HTTPException(status_code=409, detail="必须保留至少一个可登录的超级管理员")


async def _preflight_employee_updates(
    db: AsyncSession,
    items: Sequence["EmployeesBatchUpdateItem"],
) -> list[tuple[Employees, dict, bool]]:
    by_id = await _load_employee_targets(db, [item.id for item in items])
    prepared: list[tuple[Employees, dict, bool]] = []
    continuity_updates: Dict[int, dict] = {}
    for item in items:
        employee = by_id[item.id]
        update = _employee_update_payload(item.updates)
        target_role = update.get("role", employee.role)
        linked_partner = await _linked_external_partner(db, employee.id)
        managed_as_partner = employee.role == "sales_partner" or linked_partner is not None
        if managed_as_partner and target_role != "sales_partner":
            raise HTTPException(
                status_code=409,
                detail="销售合伙人角色不能直接改为内部员工；请先停用账号并保留分润历史",
            )
        target_status = update.get("status", employee.status)
        if (
            target_status in OWNERSHIP_HANDOFF_STATUSES
            and employee.status not in OWNERSHIP_HANDOFF_STATUSES
        ):
            await _assert_no_active_employee_ownership(db, employee)
        continuity_updates[employee.id] = update
        prepared.append((employee, update, managed_as_partner or target_role == "sales_partner"))

    await _assert_super_admin_continuity(db, updates=continuity_updates)
    return prepared


async def _sync_sales_partner_profile(
    db: AsyncSession,
    employee: Employees,
    admin: UserResponse,
    *,
    status_changed: bool = False,
    force_deactivate: bool = False,
) -> SalesPartner:
    """Synchronize login/profile state while preserving commission history."""
    partner = await _ensure_sales_partner_profile(db, employee, admin)
    await db.flush()
    should_deactivate = force_deactivate or employee.status in TERMINAL_EMPLOYEE_STATUSES
    if should_deactivate:
        stopped_at = datetime.now(BUSINESS_TIMEZONE).date()
        if partner.status not in {"terminated", "settled"}:
            partner.status = "terminated"
            partner.stopped_at = stopped_at
            note = f"{stopped_at.isoformat()} terminated: 员工账号停用同步"
            partner.notes = "\n".join(filter(None, [partner.notes, note]))
            await transfer_partner_attributions_to_direct(
                db,
                partner_id=partner.id,
                stopped_at=stopped_at,
                actor_id=str(admin.id),
                actor_name=admin.name or admin.email,
            )
        elif partner.stopped_at is None:
            partner.stopped_at = stopped_at
    elif status_changed and employee.status in ACTIVE_EMPLOYEE_STATUSES:
        partner.status = "active"
        partner.stopped_at = None
    return partner


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
    status: Optional[EmployeeStatus] = None
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
    status: Optional[EmployeeStatus] = None
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


class EmployeeDirectoryResponse(BaseModel):
    """Non-sensitive employee fields used by assignee/owner selectors."""
    id: int
    name: str
    department: Optional[str] = None
    role: str
    supervisor: Optional[str] = None
    status: Optional[str] = None

    class Config:
        from_attributes = True


class EmployeeDirectoryListResponse(BaseModel):
    items: List[EmployeeDirectoryResponse]
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
    _admin: UserResponse = Depends(get_admin_user),
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


@router.get("/directory", response_model=EmployeeDirectoryListResponse)
async def query_employee_directory(
    query: str = Query(None, description="Directory query conditions (JSON string)"),
    sort: str = Query(None, description="Directory sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    db: AsyncSession = Depends(get_db),
):
    """Return only the non-sensitive fields needed by employee selectors."""
    allowed_fields = {"id", "name", "department", "role", "supervisor", "status"}
    query_dict = None
    if query:
        try:
            query_dict = json.loads(query)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid query JSON format")
        if not isinstance(query_dict, dict) or any(field not in allowed_fields for field in query_dict):
            raise HTTPException(status_code=400, detail="Directory query contains unsupported fields")

    if sort and sort.lstrip("-") not in allowed_fields:
        raise HTTPException(status_code=400, detail="Directory sort contains an unsupported field")

    service = EmployeesService(db)
    try:
        return await service.get_list(
            skip=skip,
            limit=limit,
            query_dict=query_dict,
            sort=sort,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error querying employee directory: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/all", response_model=EmployeesListResponse)
async def query_employeess_all(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    _admin: UserResponse = Depends(get_admin_user),
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
    _admin: UserResponse = Depends(get_admin_user),
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
        for index, item_data in enumerate(request.items):
            payload = item_data.model_dump()
            if not payload.get("user_id"):
                payload["user_id"] = (
                    payload.get("login_username")
                    or payload.get("email")
                    or payload.get("employee_code")
                    or f"emp_{int(datetime.utcnow().timestamp())}_{index}"
                )
            if not payload.get("status"):
                payload["status"] = "active"
            result = await service.create(payload, commit=False)
            if result:
                results.append(result)
        await db.commit()
        for result in results:
            await db.refresh(result)
        
        logger.info(f"Batch created {len(results)} employeess successfully")
        return results
    except HTTPException:
        await db.rollback()
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
        prepared = await _preflight_employee_updates(db, request.items)
        for employee, update_dict, is_sales_partner in prepared:
            status_changed = "status" in update_dict and update_dict["status"] != employee.status
            result = await service.update(employee.id, update_dict, commit=False)
            if not result:
                raise HTTPException(status_code=404, detail="Employees not found")
            if is_sales_partner:
                await _sync_sales_partner_profile(
                    db,
                    result,
                    _admin,
                    status_changed=status_changed,
                )
            results.append(result)
        await db.commit()
        for result in results:
            await db.refresh(result)

        logger.info(f"Batch updated {len(results)} employeess successfully")
        return results
    except HTTPException:
        await db.rollback()
        raise
    except ValueError as e:
        await db.rollback()
        logger.error(f"Validation error in batch update: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
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
        item = EmployeesBatchUpdateItem(id=id, updates=data)
        prepared = await _preflight_employee_updates(db, [item])
        existing, update_dict, is_sales_partner = prepared[0]
        status_changed = "status" in update_dict and update_dict["status"] != existing.status
        result = await service.update(id, update_dict, commit=False)
        if not result:
            logger.warning(f"Employees with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Employees not found")
        if is_sales_partner:
            await _sync_sales_partner_profile(
                db,
                result,
                _admin,
                status_changed=status_changed,
            )
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
    deactivated_count = 0

    try:
        targets = await _load_employee_targets(db, request.ids)
        actor_id = await _actor_employee_id(db, _admin)
        if actor_id is not None and actor_id in targets:
            raise HTTPException(status_code=409, detail="不能删除当前登录账号")
        for item_id in request.ids:
            await _assert_no_active_employee_ownership(db, targets[item_id])
        await _assert_super_admin_continuity(db, deleted_ids=set(request.ids))

        partner_targets = {
            item_id: await _linked_external_partner(db, item_id)
            for item_id in request.ids
        }
        for item_id in request.ids:
            employee = targets[item_id]
            if employee.role == "sales_partner" or partner_targets[item_id] is not None:
                employee.status = "disabled"
                employee.updated_at = datetime.utcnow()
                await _sync_sales_partner_profile(
                    db,
                    employee,
                    _admin,
                    force_deactivate=True,
                )
                deactivated_count += 1
                continue
            success = await service.delete(item_id, commit=False)
            if not success:
                raise HTTPException(status_code=404, detail="Employees not found")
            deleted_count += 1

        await db.commit()
        processed_count = deleted_count + deactivated_count
        logger.info(
            "Batch processed %s employees: %s deleted, %s sales partners deactivated",
            processed_count,
            deleted_count,
            deactivated_count,
        )
        return {
            "message": f"Successfully processed {processed_count} employeess",
            "deleted_count": deleted_count,
            "deactivated_count": deactivated_count,
        }
    except HTTPException:
        await db.rollback()
        raise
    except ValueError as e:
        await db.rollback()
        logger.error(f"Validation error in batch delete: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
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
        targets = await _load_employee_targets(db, [id])
        employee = targets[id]
        actor_id = await _actor_employee_id(db, _admin)
        if actor_id is not None and actor_id == id:
            raise HTTPException(status_code=409, detail="不能删除当前登录账号")
        await _assert_no_active_employee_ownership(db, employee)
        await _assert_super_admin_continuity(db, deleted_ids={id})

        linked_partner = await _linked_external_partner(db, id)
        if employee.role == "sales_partner" or linked_partner is not None:
            employee.status = "disabled"
            employee.updated_at = datetime.utcnow()
            await _sync_sales_partner_profile(
                db,
                employee,
                _admin,
                force_deactivate=True,
            )
            await db.commit()
            await db.refresh(employee)
            logger.info(f"Sales partner employee {id} deactivated instead of deleted")
            return {
                "message": "销售合伙人账号已停用，分润档案与历史记录已保留",
                "id": id,
                "deactivated": True,
            }

        success = await service.delete(id, commit=False)
        if not success:
            logger.warning(f"Employees with id {id} not found for deletion")
            raise HTTPException(status_code=404, detail="Employees not found")
        await db.commit()

        logger.info(f"Employees {id} deleted successfully")
        return {"message": "Employees deleted successfully", "id": id}
    except HTTPException:
        await db.rollback()
        raise
    except ValueError as e:
        await db.rollback()
        logger.error(f"Validation error deleting employees {id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting employees {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
