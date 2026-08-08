import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.services.emp_auth import create_access_token


def _partner_headers() -> dict[str, str]:
    token = create_access_token({
        "emp_id": 9901,
        "email": "partner@example.com",
        "role": "sales_partner",
        "name": "Partner",
    })
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_sales_partner_api_allowlist_blocks_internal_business_entities():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        customers = await ac.get("/api/v1/entities/customers", headers=_partner_headers())
        deals = await ac.get("/api/v1/entities/deals", headers=_partner_headers())
        finance = await ac.get("/api/v1/entities/payments", headers=_partner_headers())
        config = await ac.get("/api/v1/app-config", headers=_partner_headers())

    assert [customers.status_code, deals.status_code, finance.status_code] == [403, 403, 403]
    assert config.status_code == 200
