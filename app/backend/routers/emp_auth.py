import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from services.emp_auth import (
    EmpAuthService,
    create_access_token,
    decode_access_token,
    verify_password,
)
from services.login_rate_limit import login_rate_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/emp-auth", tags=["employee-auth"])
ACTIVE_EMPLOYEE_STATUSES = {"active", "probation"}


# ---------- Schemas ----------
class LoginRequest(BaseModel):
    email: str
    password: str


class EmployeeInfo(BaseModel):
    id: int
    name: str
    role: str
    email: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None


class LoginResponse(BaseModel):
    token: str
    employee: EmployeeInfo


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class SetPasswordRequest(BaseModel):
    employee_id: int
    new_password: str


# ---------- Helper ----------
def _get_token_payload(authorization: Optional[str]):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = authorization.replace("Bearer ", "")
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return payload


async def _get_active_employee(payload: dict, db: AsyncSession) -> dict:
    emp_id = payload.get("emp_id")
    if not emp_id:
        raise HTTPException(status_code=401, detail="无效的登录凭证")

    employee = await EmpAuthService(db).get_employee_by_id(emp_id)
    if not employee or employee.get("status") not in ACTIVE_EMPLOYEE_STATUSES:
        raise HTTPException(status_code=401, detail="账号已被停用")
    return employee


# ---------- Routes ----------
@router.post("/login", response_model=LoginResponse)
async def employee_login(
    data: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Employee login with email and password."""
    client_ip = request.client.host if request.client else "unknown"
    if os.getenv("TRUST_PROXY_HEADERS", "").strip().lower() in {"1", "true", "yes", "on"}:
        forwarded_ip = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded_ip:
            client_ip = forwarded_ip
    rate_limit_keys = login_rate_limiter.keys(client_ip, data.email)
    retry_after = login_rate_limiter.retry_after(rate_limit_keys)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="登录尝试过多，请稍后再试",
            headers={"Retry-After": str(retry_after)},
        )

    service = EmpAuthService(db)
    emp = await service.authenticate(data.email, data.password)

    if not emp:
        retry_after = login_rate_limiter.record_failure(rate_limit_keys)
        headers = {"Retry-After": str(retry_after)} if retry_after else None
        if retry_after:
            raise HTTPException(status_code=429, detail="登录尝试过多，请稍后再试", headers=headers)
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    if emp["status"] not in ("active", "probation"):
        login_rate_limiter.record_failure(rate_limit_keys)
        raise HTTPException(status_code=403, detail="账号已被停用，请联系管理员")

    login_rate_limiter.clear(rate_limit_keys)

    token = create_access_token({
        "emp_id": emp["id"],
        "email": emp["email"],
        "role": emp["role"],
        "name": emp["name"],
    })

    return LoginResponse(
        token=token,
        employee=EmployeeInfo(
            id=emp["id"],
            name=emp["name"],
            role=emp["role"],
            email=emp["email"],
            phone=emp["phone"],
            status=emp["status"],
        ),
    )


@router.get("/me", response_model=EmployeeInfo)
async def get_current_employee(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Get current logged-in employee info."""
    payload = _get_token_payload(authorization)
    emp = await _get_active_employee(payload, db)

    return EmployeeInfo(
        id=emp["id"],
        name=emp["name"],
        role=emp["role"],
        email=emp["email"],
        phone=emp["phone"],
        status=emp["status"],
    )


@router.post("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Change employee password."""
    payload = _get_token_payload(authorization)
    emp = await _get_active_employee(payload, db)
    emp_id = emp["id"]
    service = EmpAuthService(db)

    if not emp["password"] or not verify_password(data.current_password, emp["password"]):
        raise HTTPException(status_code=400, detail="当前密码错误")

    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="新密码至少8个字符")

    success = await service.update_password(emp_id, data.new_password)
    if not success:
        raise HTTPException(status_code=500, detail="密码修改失败")

    return {"message": "密码修改成功"}


@router.post("/set-password")
async def set_employee_password(
    data: SetPasswordRequest,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Admin sets password for an employee."""
    payload = _get_token_payload(authorization)
    caller = await _get_active_employee(payload, db)
    caller_role = caller.get("role", "")
    if caller_role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="无权限操作")

    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="密码至少8个字符")

    service = EmpAuthService(db)
    success = await service.update_password(data.employee_id, data.new_password)
    if not success:
        raise HTTPException(status_code=404, detail="员工不存在")

    return {"message": "密码设置成功"}


@router.post("/init-admin")
async def init_admin(db: AsyncSession = Depends(get_db)):
    """Initialize a configured admin account if explicitly enabled."""
    import os

    if os.environ.get("ALLOW_INIT_ADMIN", "").lower() != "true":
        raise HTTPException(status_code=403, detail="初始化管理员接口已禁用")
    if not os.environ.get("DEFAULT_ADMIN_PASSWORD"):
        raise HTTPException(status_code=400, detail="请先设置 DEFAULT_ADMIN_PASSWORD")

    service = EmpAuthService(db)
    await service.ensure_default_admin()
    return {"message": "Configured admin initialization checked"}
