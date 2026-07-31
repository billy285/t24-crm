import pytest
from httpx import ASGITransport, AsyncClient

from backend import main


@pytest.mark.asyncio
async def test_health_is_lightweight_and_includes_operational_headers():
    transport = ASGITransport(app=main.app)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "t24-crm"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["strict-transport-security"].startswith("max-age=")
    assert response.headers["x-request-id"]
    assert response.headers["server-timing"].startswith("app;dur=")


@pytest.mark.asyncio
async def test_readiness_fails_closed_when_database_is_unavailable(monkeypatch):
    async def unhealthy_database():
        return False

    monkeypatch.setattr(main, "check_database_health", unhealthy_database)
    transport = ASGITransport(app=main.app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unhealthy", "service": "database"}


@pytest.mark.asyncio
async def test_readiness_succeeds_when_database_is_available(monkeypatch):
    async def healthy_database():
        return True

    monkeypatch.setattr(main, "check_database_health", healthy_database)
    transport = ASGITransport(app=main.app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "service": "t24-crm"}
