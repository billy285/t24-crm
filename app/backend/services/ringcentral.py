import base64
import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status

from core.mask_crypto import decrypt_text, encrypt_text


RINGCENTRAL_SERVER_URL = "https://platform.ringcentral.com"
RINGCENTRAL_DEFAULT_REDIRECT_URI = "https://t24-crm.com/api/ringcentral/callback"
RINGCENTRAL_DEFAULT_WEBHOOK_URI = "https://t24-crm.com/api/ringcentral/webhook"
STATE_TTL_SECONDS = 15 * 60
logger = logging.getLogger(__name__)


def _provider_reason(response: httpx.Response) -> str:
    try:
        payload = response.json()
        reason = str(
            payload.get("error_description") or payload.get("error") or payload.get("message") or ""
        ).strip()
    except (ValueError, TypeError):
        reason = ""
    return reason[:180] if reason else f"HTTP {response.status_code}"


def _basic_authorization(client_id: str, client_secret: str) -> str:
    encoded = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def _credential_value(name: str) -> str:
    raw_value = os.getenv(name) or ""
    value = raw_value.strip()
    invalid_placeholder = value.startswith(("你的 ", "your ", "YOUR "))
    if not value or "\n" in raw_value or "\r" in raw_value or len(value) > 256 or invalid_placeholder:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RingCentral 应用凭证格式异常，请重新复制 Client ID 和 Client Secret 的单行值。",
        )
    return value


def _required_env(name: str) -> str:
    return _credential_value(name)


def connection_configured() -> bool:
    try:
        _credential_value("RINGCENTRAL_CLIENT_ID")
        _credential_value("RINGCENTRAL_CLIENT_SECRET")
    except HTTPException:
        return False
    return True


def redirect_uri() -> str:
    return (os.getenv("RINGCENTRAL_REDIRECT_URI") or RINGCENTRAL_DEFAULT_REDIRECT_URI).strip()


def webhook_uri() -> str:
    return (os.getenv("RINGCENTRAL_WEBHOOK_URL") or RINGCENTRAL_DEFAULT_WEBHOOK_URI).strip()


def webhook_verification_token() -> str:
    return (os.getenv("RINGCENTRAL_WEBHOOK_VERIFICATION_TOKEN") or "").strip()


def _state_key() -> bytes:
    raw = (os.getenv("JWT_SECRET_KEY") or os.getenv("MASK_KEY") or "").strip()
    if not raw:
        raise HTTPException(status_code=503, detail="服务器缺少授权状态签名配置，暂不能连接 RingCentral。")
    return raw.encode("utf-8")


def _b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_oauth_state(employee_id: int) -> str:
    payload = {"employee_id": employee_id, "issued_at": int(time.time()), "nonce": secrets.token_urlsafe(12)}
    body = _b64_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _b64_encode(hmac.new(_state_key(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def verify_oauth_state(value: str) -> int:
    try:
        body, supplied_signature = value.split(".", 1)
        expected_signature = _b64_encode(hmac.new(_state_key(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ValueError("signature")
        payload = json.loads(_b64_decode(body))
        employee_id = int(payload["employee_id"])
        if int(time.time()) - int(payload["issued_at"]) > STATE_TTL_SECONDS:
            raise ValueError("expired")
        return employee_id
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="RingCentral 授权链接已失效，请回到工作台重新连接。") from exc


def authorization_url(employee_id: int) -> str:
    client_id = _required_env("RINGCENTRAL_CLIENT_ID")
    params = {
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "client_id": client_id,
        "state": create_oauth_state(employee_id),
    }
    return f"{RINGCENTRAL_SERVER_URL}/restapi/oauth/authorize?{urlencode(params)}"


async def exchange_authorization_code(code: str) -> Dict[str, Any]:
    client_id = _required_env("RINGCENTRAL_CLIENT_ID")
    client_secret = _required_env("RINGCENTRAL_CLIENT_SECRET")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{RINGCENTRAL_SERVER_URL}/restapi/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "redirect_uri": redirect_uri(),
            },
            headers={"Accept": "application/json", "Authorization": _basic_authorization(client_id, client_secret)},
        )
    if response.is_error:
        # RingCentral's OAuth response tells us whether the app credentials,
        # callback URL, or one-time authorization code needs correction. Only
        # surface the provider error fields, never request credentials.
        provider_reason = _provider_reason(response)
        logger.warning("RingCentral OAuth token exchange failed: status=%s reason=%s", response.status_code, provider_reason)
        raise HTTPException(
            status_code=502,
            detail=(
                f"RingCentral 授权交换失败：{provider_reason}。"
                "请确认 Client ID、Client Secret 与回调地址完全一致后，再从工作台重新连接。"
            ),
        )
    return response.json()


async def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    client_id = _required_env("RINGCENTRAL_CLIENT_ID")
    client_secret = _required_env("RINGCENTRAL_CLIENT_SECRET")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="RingCentral 缺少刷新令牌，请重新连接账号。")

    response: httpx.Response | None = None
    async with httpx.AsyncClient(timeout=20) as client:
        for attempt in range(2):
            try:
                response = await client.post(
                    f"{RINGCENTRAL_SERVER_URL}/restapi/oauth/token",
                    data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                    headers={
                        "Accept": "application/json",
                        "Authorization": _basic_authorization(client_id, client_secret),
                    },
                )
            except httpx.TransportError as exc:
                if attempt == 0:
                    await asyncio.sleep(0.25)
                    continue
                logger.warning("RingCentral token refresh transport error: %s", type(exc).__name__)
                raise HTTPException(status_code=502, detail="RingCentral 网络暂时不可用，系统稍后会自动重试。") from exc

            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 0:
                    await asyncio.sleep(0.25)
                    continue
            break

    if response is None:
        raise HTTPException(status_code=502, detail="RingCentral 刷新令牌时没有收到响应。")
    if response.is_error:
        reason = _provider_reason(response)
        logger.warning("RingCentral token refresh failed: status=%s reason=%s", response.status_code, reason)
        if response.status_code in {400, 401, 403}:
            raise HTTPException(status_code=401, detail=f"RingCentral 授权已失效：{reason}，请重新连接账号。")
        raise HTTPException(status_code=502, detail=f"RingCentral 暂时无法刷新授权：{reason}。")
    return response.json()


async def get_extension_profile(access_token: str) -> Dict[str, Any]:
    response: httpx.Response | None = None
    async with httpx.AsyncClient(timeout=20) as client:
        for attempt in range(2):
            try:
                response = await client.get(
                    f"{RINGCENTRAL_SERVER_URL}/restapi/v1.0/account/~/extension/~",
                    headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                )
            except httpx.TransportError as exc:
                if attempt == 0:
                    await asyncio.sleep(0.25)
                    continue
                raise HTTPException(status_code=502, detail="读取 RingCentral 分机时网络暂时不可用。") from exc
            if (response.status_code == 429 or response.status_code >= 500) and attempt == 0:
                await asyncio.sleep(0.25)
                continue
            break
    if response is None:
        raise HTTPException(status_code=502, detail="读取 RingCentral 分机时没有收到响应。")
    if response.is_error:
        raise HTTPException(status_code=502, detail="无法读取 RingCentral 分机信息，请重新连接账号。")
    return response.json()


async def _authorized_json_request(
    method: str,
    path: str,
    access_token: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    response: httpx.Response | None = None
    async with httpx.AsyncClient(timeout=20) as client:
        for attempt in range(2):
            try:
                response = await client.request(
                    method,
                    f"{RINGCENTRAL_SERVER_URL}{path}",
                    params=params,
                    json=payload,
                    headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                )
            except httpx.TransportError as exc:
                if attempt == 0:
                    await asyncio.sleep(0.25)
                    continue
                raise HTTPException(status_code=502, detail="RingCentral 网络暂时不可用。") from exc
            if (response.status_code == 429 or response.status_code >= 500) and attempt == 0:
                await asyncio.sleep(0.25)
                continue
            break
    if response is None:
        raise HTTPException(status_code=502, detail="RingCentral 没有返回响应。")
    if response.is_error:
        reason = _provider_reason(response)
        code = 401 if response.status_code in {401, 403} else 404 if response.status_code == 404 else 502
        raise HTTPException(status_code=code, detail=f"RingCentral 请求失败：{reason}。")
    return response.json()


async def fetch_extension_call_log(
    access_token: str,
    *,
    date_from: datetime,
    telephony_session_id: str | None = None,
) -> list[Dict[str, Any]]:
    payload = await _authorized_json_request(
        "GET",
        "/restapi/v1.0/account/~/extension/~/call-log",
        access_token,
        params={
            "view": "Detailed",
            "dateFrom": date_from.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "perPage": 100,
        },
    )
    records = list(payload.get("records") or [])
    if telephony_session_id:
        records = [
            record for record in records
            if str(record.get("telephonySessionId") or "") == str(telephony_session_id)
        ]
    return records


async def create_telephony_subscription(
    access_token: str,
    *,
    account_id: str,
    extension_id: str,
) -> Dict[str, Any]:
    delivery_mode: Dict[str, Any] = {
        "transportType": "WebHook",
        "address": webhook_uri(),
    }
    verification_token = webhook_verification_token()
    environment = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()
    if not verification_token and environment in {"prod", "production"}:
        raise HTTPException(
            status_code=503,
            detail="服务器缺少 RingCentral webhook verification token，暂不能启用实时通话同步。",
        )
    if verification_token:
        delivery_mode["verificationToken"] = verification_token
    return await _authorized_json_request(
        "POST",
        "/restapi/v1.0/subscription",
        access_token,
        payload={
            "eventFilters": [
                f"/restapi/v1.0/account/{account_id}/extension/{extension_id}/telephony/sessions"
            ],
            "deliveryMode": delivery_mode,
            "expiresIn": 604800,
        },
    )


async def renew_telephony_subscription(access_token: str, subscription_id: str) -> Dict[str, Any]:
    return await _authorized_json_request(
        "POST",
        f"/restapi/v1.0/subscription/{subscription_id}/renew",
        access_token,
        payload={"expiresIn": 604800},
    )


def token_expiry(token_payload: Dict[str, Any]) -> datetime:
    seconds = max(int(token_payload.get("expires_in") or 0) - 60, 0)
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def token_needs_refresh(expires_at: datetime | None, leeway_seconds: int = 5 * 60) -> bool:
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc) + timedelta(seconds=leeway_seconds)


def encrypt_token(value: str | None) -> str | None:
    return encrypt_text(value) if value else None


def decrypt_token(value: str | None) -> str | None:
    return decrypt_text(value) if value else None
