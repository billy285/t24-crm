# @File: routers/emp_auth_tokens.py
# @Desc: Issue HttpOnly refresh cookie, refresh access token, and logout (clear cookie)
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Header
from pydantic import BaseModel

from services.security_tokens import (
    create_refresh_token,
    verify_refresh_token,
    REFRESH_TOKEN_EXPIRE_DAYS,
)

# Employee auth imports
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from services.emp_auth import (
    EmpAuthService,
    decode_access_token as decode_emp_token,
    create_access_token as create_emp_access_token,
)

router = APIRouter(prefix="/api/v1/emp-auth", tags=["emp-auth"])

class SetRefreshRequest(BaseModel):
    remember_me: bool = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 1800  # 30 min default

SECURE_COOKIE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
SAMESITE = os.environ.get("COOKIE_SAMESITE", "lax").capitalize()  # Lax|None|Strict
COOKIE_PATH = os.environ.get("COOKIE_PATH", "/")
COOKIE_NAME = os.environ.get("EMP_REFRESH_COOKIE", "emp_refresh_token")

@router.post("/set_refresh")
async def set_refresh_cookie(
    data: SetRefreshRequest,
    response: Response,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Issue a refresh token cookie after successful employee login.
    Accepts Authorization: Bearer {employeeToken} and extracts emp_id.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    emp_token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_emp_token(emp_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid employee token")

    emp_id = payload.get("emp_id")
    if not emp_id:
        raise HTTPException(status_code=401, detail="Invalid employee token payload")

    # Validate employee exists (optional but safer)
    service = EmpAuthService(db)
    emp = await service.get_employee_by_id(emp_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Subject is the employee id; cookie config from env
    refresh_token = create_refresh_token(subject=str(emp_id))
    max_age = REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600 if data.remember_me else None

    response.set_cookie(
        key=COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        samesite=SAMESITE,
        secure=SECURE_COOKIE,
        path=COOKIE_PATH,
        max_age=max_age,
    )
    return {"success": True}

@router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Use HttpOnly refresh cookie to mint a NEW employee access token that works with /api/v1/emp-auth/me.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")

    try:
        payload = verify_refresh_token(token)
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        # sub is the emp_id we set when issuing the cookie
        emp_id = int(sub)
        service = EmpAuthService(db)
        emp = await service.get_employee_by_id(emp_id)
        if not emp:
            raise HTTPException(status_code=404, detail="Employee not found")

        claims = {
            "emp_id": emp["id"],
            "email": emp.get("email"),
            "role": emp.get("role"),
            "name": emp.get("name"),
        }
        access = create_emp_access_token(claims)
        return TokenResponse(access_token=access)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

@router.post("/logout")
async def logout(response: Response):
    """Clear the refresh token cookie."""
    response.delete_cookie(key=COOKIE_NAME, path=COOKIE_PATH)
    return {"success": True}
