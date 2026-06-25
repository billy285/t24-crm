import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.services.emp_auth import create_access_token


def _auth_headers(role: str) -> dict[str, str]:
    token = create_access_token({
        "emp_id": 4001,
        "email": f"{role}@example.com",
        "role": role,
        "name": role,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_service_board_and_ai_endpoints_require_login():
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        responses = [
            await ac.get("/api/v1/entities/service_progresses/all"),
            await ac.get("/api/v1/entities/service_tasks/all"),
            await ac.post(
                "/api/v1/aihub/gentxt",
                json={"messages": [{"role": "user", "content": "hello"}]},
            ),
            await ac.post(
                "/api/v1/aihub/genimg",
                json={"prompt": "simple product poster"},
            ),
        ]

    assert [response.status_code for response in responses] == [401, 401, 401, 401]


@pytest.mark.asyncio
async def test_monthly_deduction_reads_require_finance_role():
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        unauthenticated = await ac.get("/api/v1/deductions-monthly/default")
        sales = await ac.get("/api/v1/deductions-monthly/default", headers=_auth_headers("sales"))
        finance = await ac.get("/api/v1/deductions-monthly/default", headers=_auth_headers("finance"))

    assert unauthenticated.status_code == 401
    assert sales.status_code == 403
    assert finance.status_code == 200
    assert "rate" in finance.json()
