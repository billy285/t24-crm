import base64

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
