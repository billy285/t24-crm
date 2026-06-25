import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.services.emp_auth import create_access_token


def _auth_headers(role: str) -> dict[str, str]:
    token = create_access_token({
        "emp_id": 5001,
        "email": f"{role}@example.com",
        "role": role,
        "name": role,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_expense_category_write_endpoints_require_finance_role():
    transport = ASGITransport(app=app)
    headers = _auth_headers("sales")
    category_payload = {
        "category_key": "ai_tools",
        "category_name": "AI工具",
        "category_type": "company",
        "is_active": True,
    }

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        responses = [
            await ac.post("/api/v1/entities/expense_categories", json=category_payload, headers=headers),
            await ac.post("/api/v1/entities/expense_categories/batch", json={"items": [category_payload]}, headers=headers),
            await ac.put("/api/v1/entities/expense_categories/1", json={"category_name": "Changed"}, headers=headers),
            await ac.put(
                "/api/v1/entities/expense_categories/batch",
                json={"items": [{"id": 1, "updates": {"category_name": "Changed"}}]},
                headers=headers,
            ),
            await ac.delete("/api/v1/entities/expense_categories/1", headers=headers),
            await ac.request("DELETE", "/api/v1/entities/expense_categories/batch", json={"ids": [1]}, headers=headers),
        ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403, 403, 403]


@pytest.mark.asyncio
async def test_expense_category_write_endpoints_require_login():
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/entities/expense_categories",
            json={"category_key": "ai_tools", "category_name": "AI工具"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_operation_log_mutation_endpoints_require_admin_role():
    transport = ASGITransport(app=app)
    headers = _auth_headers("sales")

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        responses = [
            await ac.put("/api/v1/entities/operation_logs/1", json={"action_detail": "Changed"}, headers=headers),
            await ac.put(
                "/api/v1/entities/operation_logs/batch",
                json={"items": [{"id": 1, "updates": {"action_detail": "Changed"}}]},
                headers=headers,
            ),
            await ac.delete("/api/v1/entities/operation_logs/1", headers=headers),
            await ac.request("DELETE", "/api/v1/entities/operation_logs/batch", json={"ids": [1]}, headers=headers),
        ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]


@pytest.mark.asyncio
async def test_operation_log_mutation_endpoints_require_login():
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.put("/api/v1/entities/operation_logs/1", json={"action_detail": "Changed"})

    assert response.status_code == 401
