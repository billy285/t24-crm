import asyncio
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import db_manager, get_db
from dependencies.auth import get_current_user
from models.employees import Employees
from models.ringcentral_call_records import RingCentralCallRecords
from models.ringcentral_connections import RingCentralConnections
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from schemas.auth import UserResponse
from services.ringcentral import (
    authorization_url,
    connection_configured,
    create_telephony_subscription,
    decrypt_token,
    encrypt_token,
    exchange_authorization_code,
    fetch_extension_call_log,
    get_extension_profile,
    refresh_access_token,
    renew_telephony_subscription,
    token_expiry,
    token_needs_refresh,
    verify_oauth_state,
    webhook_verification_token,
)
from services.ringcentral_sync import process_telephony_event, upsert_call_log_record


router = APIRouter(prefix="/api/ringcentral", tags=["ringcentral"])
SALES_ROLES = {"admin", "super_admin", "sales_manager", "sales"}
_refresh_locks: dict[int, asyncio.Lock] = {}


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
            "degraded": False,
            "needs_reconnect": False,
            "message": "可连接 RingCentral" if configured else "等待系统管理员完成服务器凭证配置",
        }
    degraded = bool(connection.is_active and connection.last_error)
    return {
        "configured": configured,
        "connected": bool(connection.is_active),
        "degraded": degraded,
        "needs_reconnect": not bool(connection.is_active),
        "extension_number": connection.extension_number,
        "connected_at": connection.created_at,
        "last_synced_at": connection.last_synced_at,
        "last_error": connection.last_error,
        "webhook_status": connection.webhook_subscription_status,
        "webhook_expires_at": connection.webhook_expires_at,
        "last_event_at": connection.last_event_at,
        "message": (
            "RingCentral 已连接，网络恢复后将自动重试"
            if degraded
            else "RingCentral 已连接"
            if connection.is_active
            else "RingCentral 授权已失效，请重新连接"
        ),
    }


def _access_token(connection: RingCentralConnections) -> str:
    token = decrypt_token(connection.access_token_encrypted)
    if not token:
        raise HTTPException(status_code=401, detail="RingCentral 授权缺少访问令牌，请重新连接账号。")
    return token


def _parse_provider_time(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def _hydrate_call_log_later(employee_id: int, telephony_session_id: str | None) -> None:
    await asyncio.sleep(20)
    if not db_manager.async_session_maker:
        return
    async with db_manager.async_session_maker() as db:
        connection = (
            await db.execute(select(RingCentralConnections).where(RingCentralConnections.employee_id == employee_id))
        ).scalar_one_or_none()
        if not connection or not connection.is_active:
            return
        connection = await _refresh_connection_if_needed(employee_id, connection, db)
        if not connection or not connection.is_active:
            return
        try:
            records = await fetch_extension_call_log(
                _access_token(connection),
                date_from=datetime.now(timezone.utc) - timedelta(days=1),
                telephony_session_id=telephony_session_id,
            )
            for record in records:
                await upsert_call_log_record(db, connection, record)
            await db.commit()
        except HTTPException as exc:
            connection.last_error = str(exc.detail)
            await db.commit()


async def _process_webhook_event(payload: dict, event_uuid: str | None) -> None:
    if not db_manager.async_session_maker:
        await db_manager.ensure_initialized()
    if not db_manager.async_session_maker:
        return
    async with db_manager.async_session_maker() as db:
        call, terminal = await process_telephony_event(db, payload, event_uuid=event_uuid)
        await db.commit()
        if call and terminal:
            await _hydrate_call_log_later(call.sales_employee_id, call.telephony_session_id)


async def _refresh_connection_if_needed(
    employee_id: int,
    connection: Optional[RingCentralConnections],
    db: AsyncSession,
) -> Optional[RingCentralConnections]:
    if not connection or not connection.is_active or not token_needs_refresh(connection.token_expires_at):
        return connection

    lock = _refresh_locks.setdefault(employee_id, asyncio.Lock())
    async with lock:
        # A concurrent status request may already have refreshed the token while
        # this request was waiting for the employee-specific lock.
        connection = (
            await db.execute(
                select(RingCentralConnections).where(RingCentralConnections.employee_id == employee_id)
            )
        ).scalar_one_or_none()
        if not connection or not connection.is_active or not token_needs_refresh(connection.token_expires_at):
            return connection

        refresh_token = decrypt_token(connection.refresh_token_encrypted)
        if not refresh_token:
            connection.is_active = False
            connection.last_error = "授权缺少刷新令牌，请重新连接"
            await db.commit()
            return connection

        try:
            payload = await refresh_access_token(refresh_token)
        except HTTPException as exc:
            connection.last_error = str(exc.detail)
            if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                connection.is_active = False
            await db.commit()
            return connection

        new_access_token = str(payload.get("access_token") or "")
        if not new_access_token:
            connection.last_error = "RingCentral 刷新响应缺少访问令牌，系统稍后重试"
            await db.commit()
            return connection

        connection.access_token_encrypted = encrypt_token(new_access_token) or ""
        rotated_refresh_token = str(payload.get("refresh_token") or "").strip()
        if rotated_refresh_token:
            connection.refresh_token_encrypted = encrypt_token(rotated_refresh_token)
        connection.token_expires_at = token_expiry(payload)
        connection.scopes = str(payload.get("scope") or connection.scopes or "")
        connection.is_active = True
        connection.last_error = None
        connection.last_synced_at = datetime.now(timezone.utc)
        await db.commit()
        return connection


@router.get("/status")
async def ringcentral_status(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_sales_access(current_user)
    employee_id = _employee_id(current_user)
    connection = (
        await db.execute(
            select(RingCentralConnections).where(RingCentralConnections.employee_id == employee_id)
        )
    ).scalar_one_or_none()
    connection = await _refresh_connection_if_needed(employee_id, connection, db)
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


@router.post("/webhook", include_in_schema=False)
async def ringcentral_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    validation_token: Optional[str] = Header(default=None, alias="Validation-Token"),
    verification_token: Optional[str] = Header(default=None, alias="Verification-Token"),
):
    # RingCentral validates a new webhook before sending events. This response
    # must stay tiny and fast and must echo the supplied validation token.
    if validation_token:
        return Response(status_code=200, media_type="application/json", headers={"Validation-Token": validation_token})
    expected_token = webhook_verification_token()
    environment = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()
    if not expected_token and environment in {"prod", "production"}:
        raise HTTPException(status_code=503, detail="RingCentral webhook verification is not configured")
    if expected_token and not hmac.compare_digest(verification_token or "", expected_token):
        raise HTTPException(status_code=401, detail="RingCentral webhook verification failed")
    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid RingCentral webhook payload") from exc
    event_uuid = str(payload.get("uuid") or request.headers.get("X-RingCentral-Event-Id") or "").strip() or None
    background_tasks.add_task(_process_webhook_event, payload, event_uuid)
    return JSONResponse({"accepted": True}, status_code=200)


@router.post("/subscription/ensure")
async def ensure_ringcentral_subscription(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_sales_access(current_user)
    employee_id = _employee_id(current_user)
    connection = (
        await db.execute(select(RingCentralConnections).where(RingCentralConnections.employee_id == employee_id))
    ).scalar_one_or_none()
    connection = await _refresh_connection_if_needed(employee_id, connection, db)
    if not connection or not connection.is_active:
        raise HTTPException(status_code=409, detail="请先连接 RingCentral 账号。")
    if not connection.ringcentral_account_id or not connection.ringcentral_extension_id:
        raise HTTPException(status_code=409, detail="RingCentral 账号缺少账户或分机信息，请重新连接。")
    try:
        if connection.webhook_subscription_id:
            try:
                payload = await renew_telephony_subscription(_access_token(connection), connection.webhook_subscription_id)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                connection.webhook_subscription_id = None
                payload = await create_telephony_subscription(
                    _access_token(connection),
                    account_id=connection.ringcentral_account_id,
                    extension_id=connection.ringcentral_extension_id,
                )
        else:
            payload = await create_telephony_subscription(
                _access_token(connection),
                account_id=connection.ringcentral_account_id,
                extension_id=connection.ringcentral_extension_id,
            )
    except HTTPException as exc:
        connection.webhook_subscription_status = "error"
        connection.last_error = str(exc.detail)
        await db.commit()
        raise
    connection.webhook_subscription_id = str(payload.get("id") or connection.webhook_subscription_id or "") or None
    connection.webhook_subscription_status = str(payload.get("status") or "active").lower()
    connection.webhook_expires_at = _parse_provider_time(payload.get("expirationTime"))
    connection.last_error = None
    await db.commit()
    return _status_payload(connection)


@router.post("/sync")
async def sync_ringcentral_call_log(
    days: int = Query(default=2, ge=1, le=30),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_sales_access(current_user)
    employee_id = _employee_id(current_user)
    connection = (
        await db.execute(select(RingCentralConnections).where(RingCentralConnections.employee_id == employee_id))
    ).scalar_one_or_none()
    connection = await _refresh_connection_if_needed(employee_id, connection, db)
    if not connection or not connection.is_active:
        raise HTTPException(status_code=409, detail="请先连接 RingCentral 账号。")
    records = await fetch_extension_call_log(
        _access_token(connection), date_from=datetime.now(timezone.utc) - timedelta(days=days)
    )
    synced = 0
    for record in records:
        if await upsert_call_log_record(db, connection, record):
            synced += 1
    connection.last_error = None
    await db.commit()
    return {"synced": synced, "last_synced_at": connection.last_synced_at}


@router.get("/calls/recent")
async def recent_ringcentral_call(
    task_id: int = Query(..., ge=1),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_sales_access(current_user)
    task = await db.get(SalesDailyDialTasks, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="每日任务不存在")
    role = str(current_user.role or "").strip().lower()
    if role == "sales" and task.sales_employee_id != _employee_id(current_user):
        raise HTTPException(status_code=403, detail="只能查看本人任务的通话状态")
    item = (
        await db.execute(
            select(RingCentralCallRecords)
            .where(RingCentralCallRecords.task_id == task_id)
            .order_by(RingCentralCallRecords.started_at.desc(), RingCentralCallRecords.id.desc())
        )
    ).scalars().first()
    if not item:
        return {"available": False, "sync_status": "waiting"}
    return {
        "available": True,
        "sync_status": item.sync_status,
        "provider_status": item.provider_status,
        "provider_result": item.provider_result,
        "connected": item.connected,
        "duration_seconds": item.duration_seconds,
        "started_at": item.started_at,
        "ended_at": item.ended_at,
        "sales_employee_id": item.sales_employee_id,
        "sales_employee_name": item.sales_employee_name,
    }


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
    crm_employee_name = (
        await db.execute(select(Employees.name).where(Employees.id == employee_id))
    ).scalar_one_or_none()
    connection.employee_name = crm_employee_name or " ".join(
        part for part in [contact.get("firstName"), contact.get("lastName")] if part
    ) or None
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
    if connection.ringcentral_account_id and connection.ringcentral_extension_id:
        try:
            subscription = await create_telephony_subscription(
                str(token_payload.get("access_token") or ""),
                account_id=connection.ringcentral_account_id,
                extension_id=connection.ringcentral_extension_id,
            )
            connection.webhook_subscription_id = str(subscription.get("id") or "") or None
            connection.webhook_subscription_status = str(subscription.get("status") or "active").lower()
            connection.webhook_expires_at = _parse_provider_time(subscription.get("expirationTime"))
        except HTTPException as exc:
            # OAuth is still useful for manual backfill even when the developer
            # app has not yet been granted webhook subscription permission.
            connection.webhook_subscription_status = "permission_required"
            connection.last_error = f"账号已连接，但实时通话同步尚未启用：{exc.detail}"
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
