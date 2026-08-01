import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.routers.expenses import reject_ad_fund_customer_expense
from backend.services.emp_auth import create_access_token


def _auth_headers(role: str) -> dict[str, str]:
    token = create_access_token({
        "emp_id": 3001,
        "email": f"{role}@example.com",
        "role": role,
        "name": role,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("expense_type", ["website_fee", "domain_fee", "hosting_fee", "design_fee", "other"])
def test_customer_expense_keeps_non_ad_cost_types(expense_type: str):
    reject_ad_fund_customer_expense(expense_type)


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


@pytest.mark.asyncio
async def test_customer_expense_rejects_ad_spend_and_points_to_monthly_settlement():
    transport = ASGITransport(app=app)
    headers = _auth_headers("admin")

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        create_response = await ac.post(
            "/api/v1/entities/expenses",
            json={"expense_type": "ads_fee", "amount": 100},
            headers=headers,
        )
        batch_response = await ac.post(
            "/api/v1/entities/expenses/batch",
            json={"items": [{"expense_type": "ads_fee", "amount": 100}]},
            headers=headers,
        )
        update_response = await ac.put(
            "/api/v1/entities/expenses/1",
            json={"expense_type": "ads_fee"},
            headers=headers,
        )

    assert [create_response.status_code, batch_response.status_code, update_response.status_code] == [400, 400, 400]
    for response in (create_response, batch_response, update_response):
        assert response.json()["detail"] == "投流成本请在投流月结中录入，客户支出仅用于网站、域名、服务器等客户专属成本"
