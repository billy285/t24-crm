"""An explicit employee allowlist, independent of configurable CRM permissions."""
import os
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user, normalize_system_role
from models.employees import Employees
from schemas.auth import UserResponse
from services.emp_auth import decode_access_token


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
