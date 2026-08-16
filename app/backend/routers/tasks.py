import json
import logging
from dataclasses import dataclass
from typing import Any, FrozenSet, List, Optional, Tuple

from datetime import datetime, date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from models.employees import Employees
from models.tasks import Tasks
from routers.app_config import DEFAULT_APP_CONFIGS
from schemas.auth import UserResponse
from services.tasks import TasksService

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entities/tasks", tags=["tasks"], dependencies=[Depends(get_current_user)])

TASK_PAGE = "/tasks"
TASK_ROLE_ALIASES = {
    "administrator": "admin",
    "system_admin": "admin",
    "operations": "ops",
    "operation": "ops",
    "designer": "design",
}
ACTIVE_TASK_EMPLOYEE_STATUSES = {"active", "probation"}


@dataclass(frozen=True)
class TaskScopeMember:
    employee_id: Optional[int]
    name: str


@dataclass(frozen=True)
class TaskAccessPolicy:
    role: str
    data_scope: str
    pages: FrozenSet[str]
    buttons: FrozenSet[str]
    members: Tuple[TaskScopeMember, ...]
    current_member: TaskScopeMember

    @property
    def unrestricted(self) -> bool:
        return self.data_scope == "all"

    @property
    def employee_ids(self) -> List[int]:
        return sorted({member.employee_id for member in self.members if member.employee_id is not None})

    @property
    def employee_names(self) -> List[str]:
        return sorted({member.name for member in self.members if member.name})


def _task_role(user: UserResponse) -> str:
    raw = str(user.role or "").strip().lower()
    return TASK_ROLE_ALIASES.get(raw, raw)


async def _load_task_role_config(db: AsyncSession, role: str) -> dict[str, Any]:
    defaults = DEFAULT_APP_CONFIGS["role_permissions"].get(role) or {}
    stored_permissions: dict[str, Any] = {}
    try:
        row = (await db.execute(
            text("SELECT value_json FROM app_settings WHERE config_key = 'role_permissions'")
        )).first()
        if row:
            parsed = json.loads(row[0])
            if isinstance(parsed, dict):
                stored_permissions = parsed
    except (OperationalError, ProgrammingError, json.JSONDecodeError, TypeError):
        # Fresh/local databases may not have app_settings until configuration is
        # first opened. Reads stay fail-safe by using the checked-in defaults;
        # this endpoint never creates or repairs schema.
        await db.rollback()

    stored = stored_permissions.get(role)
    if not isinstance(stored, dict):
        stored = {}
    return {
        "pages": stored.get("pages") if isinstance(stored.get("pages"), list) else defaults.get("pages", []),
        "buttons": stored.get("buttons") if isinstance(stored.get("buttons"), list) else defaults.get("buttons", []),
        "dataScope": stored.get("dataScope") or defaults.get("dataScope", "self"),
    }


async def _resolve_current_employee(db: AsyncSession, user: UserResponse) -> Optional[Employees]:
    conditions = []
    try:
        conditions.append(Employees.id == int(user.id))
    except (TypeError, ValueError):
        pass
    if user.id:
        conditions.append(Employees.user_id == str(user.id))
    if user.email:
        conditions.append(Employees.email == str(user.email).strip().lower())
    if user.name:
        conditions.append(Employees.name == str(user.name).strip())
    if not conditions:
        return None

    rows = (await db.execute(select(Employees).where(or_(*conditions)))).scalars().all()
    if not rows:
        return None

    try:
        numeric_id = int(user.id)
    except (TypeError, ValueError):
        numeric_id = None

    def match_priority(employee: Employees) -> tuple[int, int]:
        if numeric_id is not None and employee.id == numeric_id:
            return (0, employee.id)
        if user.id and employee.user_id == str(user.id):
            return (1, employee.id)
        if user.email and str(employee.email or "").strip().lower() == str(user.email).strip().lower():
            return (2, employee.id)
        return (3, employee.id)

    return sorted(rows, key=match_priority)[0]


async def _task_access_policy(db: AsyncSession, user: UserResponse) -> TaskAccessPolicy:
    role = _task_role(user)
    config = await _load_task_role_config(db, role)
    raw_scope = str(config.get("dataScope") or "self").strip().lower()
    data_scope = "all" if raw_scope == "all" else "team" if raw_scope in {"team", "department"} else "self"
    current_employee = await _resolve_current_employee(db, user)

    fallback_id: Optional[int]
    try:
        fallback_id = int(user.id)
    except (TypeError, ValueError):
        fallback_id = None
    current_member = TaskScopeMember(
        employee_id=current_employee.id if current_employee else fallback_id,
        name=str((current_employee.name if current_employee else user.name) or "").strip(),
    )

    members: dict[tuple[Optional[int], str], TaskScopeMember] = {
        (current_member.employee_id, current_member.name): current_member,
    }
    if data_scope == "team" and current_employee:
        team_conditions = [Employees.id == current_employee.id]
        if current_employee.name:
            team_conditions.append(Employees.supervisor == current_employee.name)
        # The existing permission contract calls this scope "department".
        # Preserve that behavior while also supporting the clearer "team"
        # value for direct-report-only configurations.
        if raw_scope == "department" and current_employee.department:
            team_conditions.append(Employees.department == current_employee.department)
        team_rows = (await db.execute(
            select(Employees).where(
                Employees.status.in_(ACTIVE_TASK_EMPLOYEE_STATUSES),
                or_(*team_conditions),
            )
        )).scalars().all()
        for employee in team_rows:
            member = TaskScopeMember(employee_id=employee.id, name=str(employee.name or "").strip())
            members[(member.employee_id, member.name)] = member

    return TaskAccessPolicy(
        role=role,
        data_scope=data_scope,
        pages=frozenset(str(item) for item in config.get("pages", [])),
        buttons=frozenset(str(item) for item in config.get("buttons", [])),
        members=tuple(members.values()),
        current_member=current_member,
    )


def _ensure_task_page(policy: TaskAccessPolicy) -> None:
    if TASK_PAGE not in policy.pages:
        raise HTTPException(status_code=403, detail="Task page access required")


def _ensure_task_button(policy: TaskAccessPolicy, permission: str) -> None:
    _ensure_task_page(policy)
    if permission not in policy.buttons:
        raise HTTPException(status_code=403, detail=f"{permission} permission required")


def _parse_collaborators(value: Any) -> List[str]:
    return sorted({item.strip() for item in str(value or "").replace("，", ",").split(",") if item.strip()})


def _member_matches(policy: TaskAccessPolicy, employee_id: Any, name: Any) -> bool:
    try:
        normalized_id = int(employee_id) if employee_id is not None else None
    except (TypeError, ValueError):
        return False
    normalized_name = str(name or "").strip()
    return any(
        (normalized_id is None or member.employee_id == normalized_id)
        and (not normalized_name or member.name == normalized_name)
        for member in policy.members
    )


def _prepare_task_write(
    data: dict[str, Any],
    policy: TaskAccessPolicy,
    *,
    creating: bool,
    existing: Optional[Tasks] = None,
) -> dict[str, Any]:
    prepared = dict(data)
    if policy.unrestricted:
        return prepared

    assignee_changed = creating or "assignee_id" in prepared or "assignee_name" in prepared
    if assignee_changed:
        assignee_id = prepared.get("assignee_id", getattr(existing, "assignee_id", None))
        assignee_name = prepared.get("assignee_name", getattr(existing, "assignee_name", None))
        if creating and assignee_id is None and not str(assignee_name or "").strip():
            assignee_id = policy.current_member.employee_id
            assignee_name = policy.current_member.name
            prepared["assignee_id"] = assignee_id
            prepared["assignee_name"] = assignee_name
        if assignee_id is None and not str(assignee_name or "").strip():
            raise HTTPException(status_code=403, detail="Scoped task must have an in-scope assignee")
        if not _member_matches(policy, assignee_id, assignee_name):
            raise HTTPException(status_code=403, detail="Task assignee is outside your data scope")

    if creating or "collaborator_names" in prepared:
        collaborators = _parse_collaborators(prepared.get("collaborator_names", getattr(existing, "collaborator_names", None)))
        allowed_names = set(policy.employee_names)
        if any(name not in allowed_names for name in collaborators):
            raise HTTPException(status_code=403, detail="Task collaborator is outside your data scope")

    return prepared


async def _get_scoped_task(
    service: TasksService,
    task_id: int,
    policy: TaskAccessPolicy,
) -> Tasks:
    item = await service.get_by_id(
        task_id,
        unrestricted=policy.unrestricted,
        employee_ids=policy.employee_ids,
        employee_names=policy.employee_names,
    )
    if item:
        return item
    if await service.get_by_id(task_id):
        raise HTTPException(status_code=403, detail="Task is outside your data scope")
    raise HTTPException(status_code=404, detail="Tasks not found")


# ---------- Pydantic Schemas ----------
class TasksData(BaseModel):
    """Entity data schema (for create/update)"""
    title: str
    customer_id: Optional[int] = None
    opportunity_id: Optional[int] = None
    customer_name: Optional[str] = None
    assignee_id: Optional[int] = None
    assignee_name: Optional[str] = None
    collaborator_names: Optional[str] = None
    task_type: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[datetime] = None
    notes: Optional[str] = None
    attachment_link: Optional[str] = None
    source_type: Optional[str] = None
    completion_result: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TasksUpdateData(BaseModel):
    """Update entity data (partial updates allowed)"""
    title: Optional[str] = None
    customer_id: Optional[int] = None
    opportunity_id: Optional[int] = None
    customer_name: Optional[str] = None
    assignee_id: Optional[int] = None
    assignee_name: Optional[str] = None
    collaborator_names: Optional[str] = None
    task_type: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[datetime] = None
    notes: Optional[str] = None
    attachment_link: Optional[str] = None
    source_type: Optional[str] = None
    completion_result: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TasksResponse(BaseModel):
    """Entity response schema"""
    id: int
    title: str
    customer_id: Optional[int] = None
    opportunity_id: Optional[int] = None
    customer_name: Optional[str] = None
    assignee_id: Optional[int] = None
    assignee_name: Optional[str] = None
    collaborator_names: Optional[str] = None
    task_type: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[datetime] = None
    notes: Optional[str] = None
    attachment_link: Optional[str] = None
    source_type: Optional[str] = None
    automation_issue_id: Optional[int] = None
    completion_result: Optional[str] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TasksListResponse(BaseModel):
    """List response schema"""
    items: List[TasksResponse]
    total: int
    skip: int
    limit: int


class TaskAssigneeOption(BaseModel):
    id: int
    name: str
    department: Optional[str] = None
    supervisor: Optional[str] = None


class TaskAssigneeOptionsResponse(BaseModel):
    items: List[TaskAssigneeOption]
    data_scope: str


class TasksBatchCreateRequest(BaseModel):
    """Batch create request"""
    items: List[TasksData]


class TasksBatchUpdateItem(BaseModel):
    """Batch update item"""
    id: int
    updates: TasksUpdateData


class TasksBatchUpdateRequest(BaseModel):
    """Batch update request"""
    items: List[TasksBatchUpdateItem]


class TasksBatchDeleteRequest(BaseModel):
    """Batch delete request"""
    ids: List[int]


# ---------- Routes ----------
@router.get("", response_model=TasksListResponse)
async def query_taskss(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Query taskss with filtering, sorting, and pagination"""
    logger.debug(f"Querying taskss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")
    
    service = TasksService(db)
    try:
        policy = await _task_access_policy(db, current_user)
        _ensure_task_page(policy)
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
            unrestricted=policy.unrestricted,
            employee_ids=policy.employee_ids,
            employee_names=policy.employee_names,
        )
        logger.debug(f"Found {result['total']} taskss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying taskss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/all", response_model=TasksListResponse)
async def query_taskss_all(
    query: str = Query(None, description="Query conditions (JSON string)"),
    sort: str = Query(None, description="Sort field (prefix with '-' for descending)"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=2000, description="Max number of records to return"),
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Historical alias retained for compatibility. It uses the same server-side
    # scope as the canonical collection endpoint and is never an auth bypass.
    logger.debug(f"Querying taskss: query={query}, sort={sort}, skip={skip}, limit={limit}, fields={fields}")

    service = TasksService(db)
    try:
        policy = await _task_access_policy(db, current_user)
        _ensure_task_page(policy)
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
            unrestricted=policy.unrestricted,
            employee_ids=policy.employee_ids,
            employee_names=policy.employee_names,
        )
        logger.debug(f"Found {result['total']} taskss")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying taskss: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/assignee-options", response_model=TaskAssigneeOptionsResponse)
async def get_task_assignee_options(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return only fields needed by the task form, already constrained to its scope."""
    policy = await _task_access_policy(db, current_user)
    _ensure_task_page(policy)
    if not ({"task_create", "task_edit"} & policy.buttons):
        raise HTTPException(status_code=403, detail="Task form access required")

    query = select(Employees).where(Employees.status.in_(ACTIVE_TASK_EMPLOYEE_STATUSES))
    if not policy.unrestricted:
        if not policy.employee_ids:
            return TaskAssigneeOptionsResponse(items=[], data_scope=policy.data_scope)
        query = query.where(Employees.id.in_(policy.employee_ids))
    rows = (await db.execute(query.order_by(Employees.name, Employees.id))).scalars().all()
    return TaskAssigneeOptionsResponse(
        items=[
            TaskAssigneeOption(
                id=row.id,
                name=row.name,
                department=row.department,
                supervisor=row.supervisor,
            )
            for row in rows
        ],
        data_scope=policy.data_scope,
    )


@router.get("/{id}", response_model=TasksResponse)
async def get_tasks(
    id: int,
    fields: str = Query(None, description="Comma-separated list of fields to return"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single tasks by ID"""
    logger.debug(f"Fetching tasks with id: {id}, fields={fields}")
    
    service = TasksService(db)
    try:
        policy = await _task_access_policy(db, current_user)
        _ensure_task_page(policy)
        return await _get_scoped_task(service, id, policy)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching tasks {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("", response_model=TasksResponse, status_code=201)
async def create_tasks(
    data: TasksData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new tasks"""
    logger.debug(f"Creating new tasks with data: {data}")
    
    service = TasksService(db)
    try:
        policy = await _task_access_policy(db, current_user)
        _ensure_task_button(policy, "task_create")
        create_data = _prepare_task_write(data.model_dump(), policy, creating=True)
        result = await service.create(create_data)
        if not result:
            raise HTTPException(status_code=400, detail="Failed to create tasks")
        
        logger.info(f"Tasks created successfully with id: {result.id}")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error creating tasks: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating tasks: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/batch", response_model=List[TasksResponse], status_code=201)
async def create_taskss_batch(
    request: TasksBatchCreateRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create multiple taskss in a single request"""
    logger.debug(f"Batch creating {len(request.items)} taskss")
    
    service = TasksService(db)
    results = []
    
    try:
        policy = await _task_access_policy(db, current_user)
        _ensure_task_button(policy, "task_create")
        prepared_items = [
            _prepare_task_write(item_data.model_dump(), policy, creating=True)
            for item_data in request.items
        ]
        for item_data in prepared_items:
            result = await service.create(item_data)
            if result:
                results.append(result)
        
        logger.info(f"Batch created {len(results)} taskss successfully")
        return results
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch create: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch create failed: {str(e)}")


@router.put("/batch", response_model=List[TasksResponse])
async def update_taskss_batch(
    request: TasksBatchUpdateRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update multiple taskss in a single request"""
    logger.debug(f"Batch updating {len(request.items)} taskss")
    
    service = TasksService(db)
    results = []
    
    try:
        policy = await _task_access_policy(db, current_user)
        _ensure_task_button(policy, "task_edit")
        prepared_items = []
        for item in request.items:
            existing = await _get_scoped_task(service, item.id, policy)
            update_dict = {k: v for k, v in item.updates.model_dump().items() if v is not None}
            prepared_items.append((item.id, _prepare_task_write(
                update_dict,
                policy,
                creating=False,
                existing=existing,
            )))
        for item_id, update_dict in prepared_items:
            result = await service.update(
                item_id,
                update_dict,
                unrestricted=policy.unrestricted,
                employee_ids=policy.employee_ids,
                employee_names=policy.employee_names,
            )
            if result:
                results.append(result)
        
        logger.info(f"Batch updated {len(results)} taskss successfully")
        return results
    except HTTPException:
        raise
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch update: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")


@router.put("/{id}", response_model=TasksResponse)
async def update_tasks(
    id: int,
    data: TasksUpdateData,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing tasks"""
    logger.debug(f"Updating tasks {id} with data: {data}")

    service = TasksService(db)
    try:
        policy = await _task_access_policy(db, current_user)
        _ensure_task_button(policy, "task_edit")
        existing = await _get_scoped_task(service, id, policy)
        # Only include non-None values for partial updates
        update_dict = {k: v for k, v in data.model_dump().items() if v is not None}
        update_dict = _prepare_task_write(update_dict, policy, creating=False, existing=existing)
        result = await service.update(
            id,
            update_dict,
            unrestricted=policy.unrestricted,
            employee_ids=policy.employee_ids,
            employee_names=policy.employee_names,
        )
        if not result:
            logger.warning(f"Tasks with id {id} not found for update")
            raise HTTPException(status_code=404, detail="Tasks not found")
        
        logger.info(f"Tasks {id} updated successfully")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error updating tasks {id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating tasks {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/batch")
async def delete_taskss_batch(
    request: TasksBatchDeleteRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple taskss by their IDs"""
    logger.debug(f"Batch deleting {len(request.ids)} taskss")
    
    service = TasksService(db)
    deleted_count = 0
    
    try:
        policy = await _task_access_policy(db, current_user)
        _ensure_task_button(policy, "task_delete")
        for item_id in request.ids:
            await _get_scoped_task(service, item_id, policy)
        for item_id in request.ids:
            success = await service.delete(
                item_id,
                unrestricted=policy.unrestricted,
                employee_ids=policy.employee_ids,
                employee_names=policy.employee_names,
            )
            if success:
                deleted_count += 1
        
        logger.info(f"Batch deleted {deleted_count} taskss successfully")
        return {"message": f"Successfully deleted {deleted_count} taskss", "deleted_count": deleted_count}
    except HTTPException:
        raise
    except ValueError as e:
        await db.rollback()
        logger.error(f"Validation error batch deleting tasks: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in batch delete: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


@router.delete("/{id}")
async def delete_tasks(
    id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single tasks by ID"""
    logger.debug(f"Deleting tasks with id: {id}")
    
    service = TasksService(db)
    try:
        policy = await _task_access_policy(db, current_user)
        _ensure_task_button(policy, "task_delete")
        await _get_scoped_task(service, id, policy)
        success = await service.delete(
            id,
            unrestricted=policy.unrestricted,
            employee_ids=policy.employee_ids,
            employee_names=policy.employee_names,
        )
        if not success:
            logger.warning(f"Tasks with id {id} not found for deletion")
            raise HTTPException(status_code=404, detail="Tasks not found")
        
        logger.info(f"Tasks {id} deleted successfully")
        return {"message": "Tasks deleted successfully", "id": id}
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error deleting tasks {id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting tasks {id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
