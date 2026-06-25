import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.services.emp_auth import create_access_token


def _auth_headers(role: str) -> dict[str, str]:
    token = create_access_token({
        "emp_id": 3001,
        "email": f"{role}@example.com",
        "role": role,
        "name": role,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_raw_finance_endpoints_reject_non_finance_roles():
    transport = ASGITransport(app=app)
    headers = _auth_headers("sales")

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        responses = [
            await ac.get("/api/v1/entities/payments/all", headers=headers),
            await ac.get("/api/v1/entities/expenses/all", headers=headers),
            await ac.get("/api/v1/entities/company_expenses/all", headers=headers),
            await ac.post(
                "/api/v1/entities/payments",
                json={"customer_id": 1, "amount_due": 100, "amount_paid": 100},
                headers=headers,
            ),
            await ac.post(
                "/api/v1/entities/expenses",
                json={"expense_type": "website_fee", "amount": 100},
                headers=headers,
            ),
            await ac.post(
                "/api/v1/entities/company_expenses",
                json={"category": "ai_tools", "amount": 100},
                headers=headers,
            ),
        ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403, 403, 403]


@pytest.mark.asyncio
async def test_raw_finance_endpoints_require_login():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        responses = [
            await ac.get("/api/v1/entities/payments/all"),
            await ac.get("/api/v1/entities/expenses/all"),
            await ac.get("/api/v1/entities/company_expenses/all"),
        ]

    assert [response.status_code for response in responses] == [401, 401, 401]
