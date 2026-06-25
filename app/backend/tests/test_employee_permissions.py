import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.services.emp_auth import create_access_token


def _auth_headers(role: str) -> dict[str, str]:
    token = create_access_token({
        "emp_id": 2001,
        "email": f"{role}@example.com",
        "role": role,
        "name": role,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_employee_write_endpoints_require_admin_role():
    transport = ASGITransport(app=app)
    headers = _auth_headers("sales")
    employee_payload = {
        "name": "Test Employee",
        "role": "sales",
        "email": "test.employee@example.com",
        "status": "active",
    }

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        responses = [
            await ac.post("/api/v1/entities/employees", json=employee_payload, headers=headers),
            await ac.post("/api/v1/entities/employees/batch", json={"items": [employee_payload]}, headers=headers),
            await ac.put("/api/v1/entities/employees/1", json={"name": "Changed"}, headers=headers),
            await ac.put("/api/v1/entities/employees/batch", json={"items": [{"id": 1, "updates": {"name": "Changed"}}]}, headers=headers),
            await ac.delete("/api/v1/entities/employees/1", headers=headers),
            await ac.request("DELETE", "/api/v1/entities/employees/batch", json={"ids": [1]}, headers=headers),
        ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403, 403, 403]


@pytest.mark.asyncio
async def test_employee_write_endpoints_require_login():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/entities/employees",
            json={"name": "No Auth", "role": "sales"},
        )

    assert response.status_code == 401
