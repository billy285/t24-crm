import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status

from core.mask_crypto import decrypt_text, encrypt_text


RINGCENTRAL_SERVER_URL = "https://platform.ringcentral.com"
RINGCENTRAL_DEFAULT_REDIRECT_URI = "https://t24-crm.com/api/ringcentral/callback"
STATE_TTL_SECONDS = 15 * 60
logger = logging.getLogger(__name__)


def _required_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RingCentral 尚未完成服务器配置，请由系统管理员设置应用凭证后再连接。",
        )
    return value


def connection_configured() -> bool:
    return bool((os.getenv("RINGCENTRAL_CLIENT_ID") or "").strip() and (os.getenv("RINGCENTRAL_CLIENT_SECRET") or "").strip())


def redirect_uri() -> str:
    return (os.getenv("RINGCENTRAL_REDIRECT_URI") or RINGCENTRAL_DEFAULT_REDIRECT_URI).strip()


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
    basic_credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{RINGCENTRAL_SERVER_URL}/restapi/oauth/token",
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri()},
            headers={"Accept": "application/json", "Authorization": f"Basic {basic_credentials}"},
        )
    if response.is_error:
        # RingCentral's OAuth response tells us whether the app credentials,
        # callback URL, or one-time authorization code needs correction. Only
        # surface the provider error fields, never request credentials.
        provider_reason = ""
        try:
            payload = response.json()
            provider_reason = str(
                payload.get("error_description") or payload.get("error") or payload.get("message") or ""
            ).strip()
        except (ValueError, TypeError):
            provider_reason = ""
        if provider_reason:
            provider_reason = provider_reason[:180]
        else:
            provider_reason = f"HTTP {response.status_code}"
        logger.warning("RingCentral OAuth token exchange failed: status=%s reason=%s", response.status_code, provider_reason)
        raise HTTPException(
            status_code=502,
            detail=(
                f"RingCentral 授权交换失败：{provider_reason}。"
                "请确认 Client ID、Client Secret 与回调地址完全一致后，再从工作台重新连接。"
            ),
        )
    return response.json()


async def get_extension_profile(access_token: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"{RINGCENTRAL_SERVER_URL}/restapi/v1.0/account/~/extension/~",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
    if response.is_error:
        raise HTTPException(status_code=502, detail="无法读取 RingCentral 分机信息，请重新连接账号。")
    return response.json()


def token_expiry(token_payload: Dict[str, Any]) -> datetime:
    seconds = max(int(token_payload.get("expires_in") or 0) - 60, 0)
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def encrypt_token(value: str | None) -> str | None:
    return encrypt_text(value) if value else None


def decrypt_token(value: str | None) -> str | None:
    return decrypt_text(value) if value else None
