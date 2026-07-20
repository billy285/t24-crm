import base64
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import HTTPException

from services import ringcentral


@pytest.mark.asyncio
async def test_exchange_authorization_code_sends_basic_auth_and_client_id(monkeypatch):
    monkeypatch.setenv("RINGCENTRAL_CLIENT_ID", "client-id")
    monkeypatch.setenv("RINGCENTRAL_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("RINGCENTRAL_REDIRECT_URI", "https://t24-crm.com/api/ringcentral/callback")
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})

    transport = httpx.MockTransport(handler)

    class TestClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=transport, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(ringcentral.httpx, "AsyncClient", TestClient)
    payload = await ringcentral.exchange_authorization_code("one-time-code")

    expected = base64.b64encode(b"client-id:client-secret").decode("ascii")
    assert captured["authorization"] == f"Basic {expected}"
    assert "client_id=client-id" in captured["body"]
    assert "grant_type=authorization_code" in captured["body"]
    assert payload["access_token"] == "token"


def test_malformed_ringcentral_secret_is_not_configured(monkeypatch):
    monkeypatch.setenv("RINGCENTRAL_CLIENT_ID", "client-id")
    monkeypatch.setenv("RINGCENTRAL_CLIENT_SECRET", "x" * 773)

    assert ringcentral.connection_configured() is False

    with pytest.raises(HTTPException) as exc_info:
        ringcentral._required_env("RINGCENTRAL_CLIENT_SECRET")

    assert exc_info.value.status_code == 503
    assert "凭证格式异常" in exc_info.value.detail


@pytest.mark.asyncio
async def test_refresh_access_token_uses_basic_auth_and_rotated_refresh_token(monkeypatch):
    monkeypatch.setenv("RINGCENTRAL_CLIENT_ID", "client-id")
    monkeypatch.setenv("RINGCENTRAL_CLIENT_SECRET", "client-secret")
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"access_token": "new-token", "refresh_token": "rotated-token", "expires_in": 3600})

    transport = httpx.MockTransport(handler)

    class TestClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=transport, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(ringcentral.httpx, "AsyncClient", TestClient)
    payload = await ringcentral.refresh_access_token("old-refresh-token")

    expected = base64.b64encode(b"client-id:client-secret").decode("ascii")
    assert captured["authorization"] == f"Basic {expected}"
    assert "grant_type=refresh_token" in captured["body"]
    assert "refresh_token=old-refresh-token" in captured["body"]
    assert payload["access_token"] == "new-token"
    assert payload["refresh_token"] == "rotated-token"


@pytest.mark.asyncio
async def test_refresh_access_token_retries_transient_provider_failure(monkeypatch):
    monkeypatch.setenv("RINGCENTRAL_CLIENT_ID", "client-id")
    monkeypatch.setenv("RINGCENTRAL_CLIENT_SECRET", "client-secret")
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"message": "temporarily unavailable"})
        return httpx.Response(200, json={"access_token": "new-token", "expires_in": 3600})

    async def no_sleep(_seconds):
        return None

    transport = httpx.MockTransport(handler)

    class TestClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=transport, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(ringcentral.httpx, "AsyncClient", TestClient)
    monkeypatch.setattr(ringcentral.asyncio, "sleep", no_sleep)

    payload = await ringcentral.refresh_access_token("refresh-token")

    assert attempts == 2
    assert payload["access_token"] == "new-token"


def test_token_needs_refresh_uses_expiry_leeway():
    now = datetime.now(timezone.utc)

    assert ringcentral.token_needs_refresh(now + timedelta(minutes=2)) is True
    assert ringcentral.token_needs_refresh(now + timedelta(minutes=20)) is False
    assert ringcentral.token_needs_refresh((now + timedelta(minutes=2)).replace(tzinfo=None)) is True
    assert ringcentral.token_needs_refresh(None) is True
