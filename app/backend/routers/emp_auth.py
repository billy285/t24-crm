import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from services.emp_auth import (
    EmpAuthService,
    create_access_token,
    decode_access_token,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/emp-auth", tags=["employee-auth"])


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


# ---------- Routes ----------
@router.post("/login", response_model=LoginResponse)
async def employee_login(
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Employee login with email and password."""
    service = EmpAuthService(db)
    emp = await service.authenticate(data.email, data.password)

    if not emp:
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    if emp["status"] not in ("active", "probation"):
        raise HTTPException(status_code=403, detail="账号已被停用，请联系管理员")

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
    emp_id = payload.get("emp_id")
    if not emp_id:
        raise HTTPException(status_code=401, detail="无效的登录凭证")

    service = EmpAuthService(db)
    emp = await service.get_employee_by_id(emp_id)
    if not emp:
        raise HTTPException(status_code=404, detail="员工不存在")

    if emp["status"] not in ("active", "probation"):
        raise HTTPException(status_code=403, detail="账号已被停用")

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
    emp_id = payload.get("emp_id")

    service = EmpAuthService(db)
    emp = await service.get_employee_by_id(emp_id)
    if not emp:
        raise HTTPException(status_code=404, detail="员工不存在")

    if not emp["password"] or not verify_password(data.current_password, emp["password"]):
        raise HTTPException(status_code=400, detail="当前密码错误")

    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少6个字符")

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
    caller_role = payload.get("role", "")
    if caller_role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="无权限操作")

    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6个字符")

    service = EmpAuthService(db)
    success = await service.update_password(data.employee_id, data.new_password)
    if not success:
        raise HTTPException(status_code=404, detail="员工不存在")

    return {"message": "密码设置成功"}


@router.post("/init-admin")
async def init_admin(db: AsyncSession = Depends(get_db)):
    """Initialize default admin account if not exists."""
    import os

    if os.environ.get("ALLOW_INIT_ADMIN", "").lower() != "true":
        raise HTTPException(status_code=403, detail="初始化管理员接口已禁用")

    service = EmpAuthService(db)
    await service.ensure_default_admin()
    return {"message": "Default admin initialized"}
