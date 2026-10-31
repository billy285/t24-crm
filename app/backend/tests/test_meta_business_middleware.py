"""Actual application middleware plus real Meta router, without lifespan or IO."""
import logging
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.routing import Route

from core.database import get_db
from dependencies.auth import get_current_user
from services import meta_business as service, meta_business_provider as provider
from test_google_business import OWNER

PREFIX = "/api/v1/meta-business"


@pytest_asyncio.fixture
async def actual_meta_app(monkeypatch):
    from backend import main
    app = main.app
    class Database:
        async def rollback(self): pass
    async def database(): yield Database()
    async def actor(): return OWNER
    original = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = database; app.dependency_overrides[get_current_user] = actor
    monkeypatch.setattr(main, "SLOW_REQUEST_SECONDS", 0)
    path = "/api/v1/__synthetic_meta_header_control"
    async def control(request): return JSONResponse({"control": True}, headers={"Referrer-Policy": "same-origin", "X-Synthetic": "unchanged"})
    route = Route(path, control, methods=["GET"]); app.router.routes.insert(0, route)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://t24-crm.com", follow_redirects=False) as client:
        try: yield SimpleNamespace(client=client, control=path, main=main)
        finally:
            app.router.routes.remove(route)
            app.dependency_overrides.clear(); app.dependency_overrides.update(original)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["connected", "http_error", "provider_error"])
async def test_actual_main_callback_303_preserves_no_referrer_and_never_logs_query(actual_meta_app, monkeypatch, caplog, outcome):
    async def callback(db, state, cookie, code):
        assert state == "SYNTHETIC-SECRET-STATE" and code == "SYNTHETIC-SECRET-CODE"
        if outcome == "http_error": raise HTTPException(400, "Synthetic safe failure")
        if outcome == "provider_error": raise provider.ProviderError("provider_unavailable")
        return True
    monkeypatch.setattr(service, "oauth_callback", callback)
    with caplog.at_level(logging.WARNING):
        response = await actual_meta_app.client.get(PREFIX + "/oauth/callback", params={"state": "SYNTHETIC-SECRET-STATE", "code": "SYNTHETIC-SECRET-CODE"})
    assert response.status_code == 303
    assert response.headers["location"] == "/media-ops?meta=" + ("connected" if outcome == "connected" else "failed")
    assert response.headers["referrer-policy"] == "no-referrer" and "no-store" in response.headers["cache-control"]
    assert response.headers["content-security-policy"] == actual_meta_app.main.CONTENT_SECURITY_POLICY
    performance = [r.getMessage() for r in caplog.records if r.name == "performance"]
    assert performance and all("SYNTHETIC-SECRET" not in value for value in performance)
    assert all("SYNTHETIC-SECRET" not in value for value in response.headers.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [200, 403, 422])
async def test_actual_main_meta_success_denial_and_validation_keep_private_policy(actual_meta_app, monkeypatch, code):
    async def status(db, user):
        if code == 403: raise HTTPException(403, "Synthetic safe denial")
        return {"phase": "connection", "publishing_implemented": False}
    monkeypatch.setattr(service, "status", status)
    if code == 422:
        response = await actual_meta_app.client.post(PREFIX + "/oauth/start", json={"confirmed": "SYNTHETIC-SECRET-VALIDATION"})
    else: response = await actual_meta_app.client.get(PREFIX + "/status")
    assert response.status_code == code and response.headers["referrer-policy"] == "no-referrer"
    assert "no-store" in response.headers["cache-control"] and "SYNTHETIC-SECRET-VALIDATION" not in response.text


@pytest.mark.asyncio
async def test_actual_main_unrelated_route_policy_and_csp_remain_unchanged(actual_meta_app):
    response = await actual_meta_app.client.get(actual_meta_app.control)
    assert response.status_code == 200 and response.json() == {"control": True}
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["x-synthetic"] == "unchanged"
    assert response.headers["content-security-policy"] == actual_meta_app.main.CONTENT_SECURITY_POLICY
