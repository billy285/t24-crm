"""Actual app middleware privacy checks with synthetic responses, no lifespan."""
import asyncio
from collections import deque
import logging
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from starlette.responses import JSONResponse
from starlette.routing import Route

from core.database import get_db
from routers import media_publication_images as route
from services import media_publication_images as images

TOKEN = "SyntheticSecretImageCapabilityToken0000000000"
PUBLIC = "/api/v1/media-publication-images/delivery/" + TOKEN + ".png"


@pytest_asyncio.fixture
async def actual_app(monkeypatch):
    from backend import main
    app = main.app
    async def database(): yield object()
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = database
    monkeypatch.setattr(main, "SLOW_REQUEST_SECONDS", 0)
    monkeypatch.setattr(route, "_public_times", deque(maxlen=120))
    control_path = "/api/v1/__synthetic_image_security_header_control"
    async def control(request):
        return JSONResponse({"synthetic": True}, headers={"Referrer-Policy": "same-origin", "X-Synthetic": "preserved"})
    control_route = Route(control_path, control, methods=["GET"])
    app.router.routes.insert(0, control_route)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=True), base_url="https://crm.example.test") as client:
        try: yield SimpleNamespace(app=app, client=client, control_path=control_path)
        finally:
            app.router.routes.remove(control_route)
            app.dependency_overrides.clear(); app.dependency_overrides.update(previous)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("result", ["success", "not_found", "rate_limited", "db_error"])
async def test_actual_middleware_never_logs_capability_and_keeps_strict_image_headers(actual_app, monkeypatch, caplog, method, result):
    async def fake_delivery(db, token):
        assert token == TOKEN
        # Yield to exercise main's timing and actual middleware chain.
        await asyncio.sleep(.001)
        if result == "not_found": raise HTTPException(404, "SYNTHETIC_NOT_FOUND")
        if result == "db_error":
            raise OperationalError("SELECT * FROM media_publication_images WHERE delivery_token=?", (TOKEN,), RuntimeError("Synthetic token-bearing database failure " + TOKEN))
        return b"\x89PNG\r\n\x1a\nSYNTHETIC-CANONICAL-BYTES"
    monkeypatch.setattr(images, "public_delivery", fake_delivery)
    if result == "rate_limited":
        now = route.time.monotonic()
        route._public_times.extend([now] * 8)
    with caplog.at_level(logging.WARNING):
        response = await actual_app.client.request(method, PUBLIC)
    expected = {"success": 200, "not_found": 404, "rate_limited": 429, "db_error": 503}[result]
    assert response.status_code == expected
    assert TOKEN not in response.text and TOKEN not in caplog.text
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    # Main's existing API cache middleware may strengthen this to its standard
    # no-store/no-cache/max-age=0 policy; exact text need not be weakened.
    assert "no-store" in response.headers["cache-control"].split(", ")
    assert "SELECT * FROM media_publication_images" not in caplog.text
    if method == "HEAD": assert response.content == b""
    if result != "success": assert response.content == b""
    records = [record.getMessage() for record in caplog.records if record.name == "performance"]
    assert records and all(TOKEN not in text for text in records)


@pytest.mark.asyncio
async def test_actual_main_retains_unrelated_response_policy_and_performance_path(actual_app, caplog):
    with caplog.at_level(logging.WARNING):
        response = await actual_app.client.get(actual_app.control_path)
    assert response.status_code == 200 and response.json() == {"synthetic": True}
    assert response.headers["x-synthetic"] == "preserved"
    # This is the pre-existing main policy, deliberately not extended elsewhere.
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    records = [record.getMessage() for record in caplog.records if record.name == "performance"]
    assert records and any(actual_app.control_path in value for value in records)


@pytest.mark.asyncio
async def test_unexpected_public_error_releases_response_slot_for_later_requests(actual_app, monkeypatch):
    calls = [0]
    async def fake(db, token):
        calls[0] += 1
        if calls[0] <= 4: raise RuntimeError("SYNTHETIC_SECRET_EXCEPTION_" + TOKEN)
        return b"synthetic image"
    monkeypatch.setattr(images, "public_delivery", fake)
    results = [await actual_app.client.get(PUBLIC) for _ in range(5)]
    assert [result.status_code for result in results] == [503] * 4 + [200]


@pytest.mark.asyncio
async def test_public_request_cancellation_propagates_and_releases_its_slot(actual_app, monkeypatch):
    entered = asyncio.Event(); release = asyncio.Event(); first = [True]
    async def fake(db, token):
        if first[0]:
            first[0] = False; entered.set(); await release.wait()
        return b"synthetic image"
    monkeypatch.setattr(images, "public_delivery", fake)
    pending = asyncio.create_task(actual_app.client.get(PUBLIC))
    await asyncio.wait_for(entered.wait(), 1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError): await pending
    release.set()
    assert (await asyncio.wait_for(actual_app.client.get(PUBLIC), 1)).status_code == 200
