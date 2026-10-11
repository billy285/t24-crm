"""An explicit employee allowlist, independent of configurable CRM permissions."""
import os
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user, normalize_system_role
from models.employees import Employees
from schemas.auth import UserResponse
from services.emp_auth import EmpAuthService, decode_access_token
from services.employee_sessions import require_employee_session


@dataclass(frozen=True)
class PrivateOwner:
    employee_id: str


def configured_owner_ids() -> frozenset[str]:
    raw = (os.environ.get("PRIVATE_WORKSPACE_OWNER_IDS") or "").strip()
    values = [value.strip() for value in raw.split(",") if value.strip()]
    # A malformed deployment setting never falls back to all administrators.
    if not values or any(not value.isdecimal() or not 0 < int(value) <= 2_147_483_647 for value in values):
        return frozenset()
    return frozenset(str(int(value)) for value in values)


async def valid_private_owner(employee_id: str, business_db: AsyncSession) -> bool:
    if employee_id not in configured_owner_ids() or not employee_id.isdecimal():
        return False
    employee = (await business_db.execute(
        select(Employees.id, Employees.status, Employees.role).where(Employees.id == int(employee_id))
    )).one_or_none()
    return bool(employee and employee.status in {"active", "probation"}
                and normalize_system_role(employee.role) == "super_admin")


async def revalidate_private_owner(request: Request, employee_id: str) -> bool:
    """Recheck the initiating session after each private bank network wait.

    The request's identity transaction may predate a logout, password change or
    offboarding. Use the standalone service's physically readonly session factory
    and require a persistent employee session even if legacy test flags opt out.
    Never reuse the CRM request transaction or open a writable fallback session.
    """
    if employee_id not in configured_owner_ids() or not employee_id.isdecimal():
        return False
    authorization = request.headers.get("Authorization", "")
    token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    payload = decode_access_token(token) if token else None
    if (not payload or payload.get("token_type") != "employee_access" or
            str(payload.get("emp_id") or "") != employee_id or
            not isinstance(payload.get("sid"), str) or not payload["sid"] or
            type(payload.get("exp")) not in {int, float} or not payload["exp"] > time.time()):
        return False
    sessions = getattr(request.app.state, "private_business_sessions", None)
    if sessions is None:
        return False
    try:
        async with sessions() as business_db:
            await business_db.rollback()
            current_user = await get_current_user(request, token=token, db=business_db)
            if str(current_user.id) != employee_id:
                return False
            employee = await EmpAuthService(business_db).get_employee_by_id(int(employee_id))
            if not employee or employee.get("status") not in {"active", "probation"}:
                return False
            # A nonempty sid makes this check mandatory irrespective of the
            # general session_enforcement_enabled test opt-out.
            await require_employee_session(business_db, employee, payload)
            allowed = await valid_private_owner(employee_id, business_db)
            return allowed and payload["exp"] > time.time()
    except Exception:
        # Database/authentication failure cannot authorize a private connector.
        return False


async def private_access_allowed(
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    business_db: AsyncSession = Depends(get_db),
) -> bool:
    # A legacy platform JWT with a numeric subject must not impersonate an employee.
    authorization = request.headers.get("Authorization", "")
    token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    payload = decode_access_token(token) if token else None
    employee_id = str(current_user.id)
    if not payload or payload.get("token_type") != "employee_access":
        return False
    if str(payload.get("emp_id") or "") != employee_id:
        return False
    return await valid_private_owner(employee_id, business_db)


async def require_private_owner(
    allowed: bool = Depends(private_access_allowed),
    current_user: UserResponse = Depends(get_current_user),
) -> PrivateOwner:
    if not allowed:
        raise HTTPException(status_code=403, detail="此私人工作空间仅限指定老板账号访问")
    return PrivateOwner(employee_id=str(current_user.id))
