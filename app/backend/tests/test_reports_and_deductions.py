import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app


@pytest.mark.asyncio
async def test_list_deductions_and_default():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r1 = await ac.get("/api/v1/deductions-monthly")
        assert r1.status_code == 200
        r2 = await ac.get("/api/v1/deductions-monthly/default")
        assert r2.status_code == 200
        assert "rate" in r2.json()


@pytest.mark.asyncio
async def test_export_profit_monthly_csv_and_xlsx():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r1 = await ac.get("/api/v1/reports/profit-monthly.csv")
        assert r1.status_code == 200
        assert "text/csv" in r1.headers.get("content-type", "")
        r2 = await ac.get("/api/v1/reports/profit-monthly.xlsx")
        assert r2.status_code == 200
        assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in r2.headers.get("content-type", "")
