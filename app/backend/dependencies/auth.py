import hashlib
import logging
import os
from datetime import datetime
from typing import Optional

from core.auth import AccessTokenError, decode_access_token
from core.database import get_db
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from schemas.auth import UserResponse
from services.emp_auth import EmpAuthService, decode_access_token as decode_employee_access_token
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)
FINANCE_ROLES = {"admin", "super_admin", "finance"}
ACTIVE_EMPLOYEE_STATUSES = {"active", "probation"}
LEGACY_ROLE_ALIASES = {
    "boss": "super_admin",
    "owner": "super_admin",
    "superadmin": "super_admin",
    "超级管理员": "super_admin",
    "老板": "super_admin",
}


def normalize_system_role(role: str | None) -> str:
    """Canonicalize only documented legacy aliases at the authentication boundary."""
    normalized = str(role or "user").strip().lower()
    return LEGACY_ROLE_ALIASES.get(normalized, normalized)


def enforce_sales_partner_route(user: UserResponse, request: Request) -> UserResponse:
    """Keep external partner accounts on an explicit read-only API allowlist."""
    if normalize_system_role(user.role) != "sales_partner":
        return user
    path = request.url.path.rstrip("/") or "/"
    allowed = (
        request.method == "GET" and (
            path == "/api/v1/commissions/my-dashboard"
            or path == "/api/v1/app-config"
            or path.startswith("/api/v1/app-config/")
        )
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sales partner accounts can only access their own partner portal",
        )
    return user


def employee_status_enforcement_enabled() -> bool:
    """Fail closed by default; tests can explicitly opt out for isolated fixtures."""
    return (os.environ.get("ENFORCE_EMPLOYEE_STATUS", "true").strip().lower() in {"1", "true", "yes", "on"})


async def get_bearer_token(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
) -> str:
    """Extract bearer token from Authorization header."""
    if credentials and credentials.scheme.lower() == "bearer":
        return credentials.credentials

    logger.debug("Authentication required for request %s %s", request.method, request.url.path)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication credentials were not provided")


async def get_current_user(
    request: Request,
    token: str = Depends(get_bearer_token),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Dependency to get current authenticated user via JWT token.

    Supports both the legacy platform JWT and the newer employee JWT so the
    admin/configuration endpoints can work consistently with the current
    employee-login flow.
    """
    employee_payload = decode_employee_access_token(token)
    employee_id = employee_payload.get("emp_id") if employee_payload else None
    if employee_id:
        if employee_status_enforcement_enabled():
            employee = await EmpAuthService(db).get_employee_by_id(int(employee_id))
            if not employee or employee.get("status") not in ACTIVE_EMPLOYEE_STATUSES:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Employee account is inactive",
                )
            return enforce_sales_partner_route(UserResponse(
                id=str(employee["id"]),
                email=employee.get("email") or "",
                name=employee.get("name"),
                role=normalize_system_role(employee.get("role")),
                last_login=None,
            ), request)

        return enforce_sales_partner_route(UserResponse(
            id=str(employee_id),
            email=employee_payload.get("email", ""),
            name=employee_payload.get("name"),
            role=normalize_system_role(employee_payload.get("role")),
            last_login=None,
        ), request)

    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token")

        last_login_raw = payload.get("last_login")
        last_login = None
        if isinstance(last_login_raw, str):
            try:
                last_login = datetime.fromisoformat(last_login_raw)
            except ValueError:
                # Log user hash instead of actual user ID to avoid exposing sensitive information
                user_hash = hashlib.sha256(str(user_id).encode()).hexdigest()[:8] if user_id else "unknown"
                logger.debug("Failed to parse last_login for user hash: %s", user_hash)

        return enforce_sales_partner_route(UserResponse(
            id=user_id,
            email=payload.get("email", ""),
            name=payload.get("name"),
            role=normalize_system_role(payload.get("role")),
            last_login=last_login,
        ), request)
    except (AccessTokenError, AttributeError, ValueError) as exc:
        logger.debug("Legacy token validation unavailable, trying employee token: %s", type(exc).__name__)

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token")


async def get_admin_user(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
    """Dependency to ensure current user has admin role."""
    if current_user.role not in {"admin", "super_admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


async def get_finance_user(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
    """Dependency to ensure current user can access raw finance records."""
    if current_user.role not in FINANCE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Finance access required")
    return current_user
