from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from models.ringcentral_connections import RingCentralConnections
from schemas.auth import UserResponse
from services.ringcentral import (
    authorization_url,
    connection_configured,
    encrypt_token,
    exchange_authorization_code,
    get_extension_profile,
    token_expiry,
    verify_oauth_state,
)


router = APIRouter(prefix="/api/ringcentral", tags=["ringcentral"])
SALES_ROLES = {"admin", "super_admin", "sales_manager", "sales"}


def _employee_id(user: UserResponse) -> int:
    try:
        return int(user.id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="当前账号未关联有效员工，无法连接 RingCentral。") from exc


def _ensure_sales_access(user: UserResponse) -> None:
    if str(user.role or "").strip().lower() not in SALES_ROLES:
        raise HTTPException(status_code=403, detail="无权连接 RingCentral 电话销售账号。")


def _status_payload(connection: Optional[RingCentralConnections]) -> dict:
    configured = connection_configured()
    if not connection:
        return {
            "configured": configured,
            "connected": False,
            "message": "可连接 RingCentral" if configured else "等待系统管理员完成服务器凭证配置",
        }
    return {
        "configured": configured,
        "connected": bool(connection.is_active),
        "extension_number": connection.extension_number,
        "connected_at": connection.created_at,
        "last_synced_at": connection.last_synced_at,
        "last_error": connection.last_error,
        "message": "RingCentral 已连接" if connection.is_active else "RingCentral 连接已停用",
    }


@router.get("/status")
async def ringcentral_status(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_sales_access(current_user)
    connection = (
        await db.execute(
            select(RingCentralConnections).where(RingCentralConnections.employee_id == _employee_id(current_user))
        )
    ).scalar_one_or_none()
    return _status_payload(connection)


@router.get("/connect")
async def ringcentral_connect_url(current_user: UserResponse = Depends(get_current_user)):
    _ensure_sales_access(current_user)
    if not connection_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="服务器尚未填写 RingCentral Client ID 和 Client Secret。请先完成服务器配置。",
        )
    return {"authorization_url": authorization_url(_employee_id(current_user))}


@router.get("/callback", include_in_schema=False)
async def ringcentral_callback(
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    if error:
        return RedirectResponse(url="/sales-workbench?ringcentral=cancelled", status_code=302)
    if not code or not state:
        return RedirectResponse(url="/sales-workbench?ringcentral=failed", status_code=302)

    employee_id = verify_oauth_state(state)
    token_payload = await exchange_authorization_code(code)
    profile = await get_extension_profile(str(token_payload.get("access_token") or ""))
    connection = (
        await db.execute(select(RingCentralConnections).where(RingCentralConnections.employee_id == employee_id))
    ).scalar_one_or_none()
    if not connection:
        connection = RingCentralConnections(employee_id=employee_id, access_token_encrypted="")
        db.add(connection)

    contact = profile.get("contact") or {}
    connection.employee_name = " ".join(part for part in [contact.get("firstName"), contact.get("lastName")] if part) or None
    connection.ringcentral_account_id = str((profile.get("account") or {}).get("id") or "") or None
    connection.ringcentral_extension_id = str(profile.get("id") or "") or None
    connection.extension_number = str(profile.get("extensionNumber") or "") or None
    connection.access_token_encrypted = encrypt_token(str(token_payload.get("access_token") or "")) or ""
    connection.refresh_token_encrypted = encrypt_token(token_payload.get("refresh_token"))
    connection.token_expires_at = token_expiry(token_payload)
    connection.scopes = str(token_payload.get("scope") or "")
    connection.is_active = True
    connection.last_error = None
    connection.last_synced_at = datetime.now(timezone.utc)
    await db.commit()
    return RedirectResponse(url="/sales-workbench?ringcentral=connected", status_code=302)


@router.post("/disconnect")
async def ringcentral_disconnect(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_sales_access(current_user)
    connection = (
        await db.execute(
            select(RingCentralConnections).where(RingCentralConnections.employee_id == _employee_id(current_user))
        )
    ).scalar_one_or_none()
    if not connection:
        return {"message": "当前没有已连接的 RingCentral 账号"}
    connection.is_active = False
    connection.last_error = "用户主动断开"
    await db.commit()
    return {"message": "RingCentral 已断开"}
