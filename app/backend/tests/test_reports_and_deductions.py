import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.main import app
from backend.routers.reports_export import _aggregate_monthly, _apply_deductions, _coerce_date
from backend.services.emp_auth import create_access_token


def _auth_headers(role: str = "finance") -> dict[str, str]:
    token = create_access_token({
        "emp_id": 1001,
        "email": f"{role}@example.com",
        "role": role,
        "name": role,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_list_deductions_and_default():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r1 = await ac.get("/api/v1/deductions-monthly", headers=_auth_headers("finance"))
        assert r1.status_code == 200
        r2 = await ac.get("/api/v1/deductions-monthly/default", headers=_auth_headers("finance"))
        assert r2.status_code == 200
        assert "rate" in r2.json()


@pytest.mark.asyncio
async def test_export_profit_monthly_csv_and_xlsx():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r1 = await ac.get("/api/v1/reports/profit-monthly.csv", headers=_auth_headers("finance"))
        assert r1.status_code == 200
        assert "text/csv" in r1.headers.get("content-type", "")
        r2 = await ac.get("/api/v1/reports/profit-monthly.xlsx", headers=_auth_headers("finance"))
        assert r2.status_code == 200
        assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in r2.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_profit_reports_require_finance_report_access():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        unauthenticated = await ac.get("/api/v1/reports/profit-monthly.csv")
        assert unauthenticated.status_code == 401

        unauthorized = await ac.get(
            "/api/v1/reports/profit-monthly.json?start=2026-06-01&end=2026-06-30",
            headers=_auth_headers("sales"),
        )
        assert unauthorized.status_code == 403


def test_apply_deductions_treats_ad_recharge_as_client_funds():
    rows = _apply_deductions(
        {
            "USD": {
                "2026-06": {
                    "revenue_gross": 3000.0,
                    "management_revenue": 1000.0,
                    "ads_recharge_revenue": 2000.0,
                    "cost": 2000.0,
                }
            }
        },
        ["2026-06"],
        {"2026-06": 0.15},
        0.15,
        None,
    )

    assert rows == [{
        "month": "2026-06",
        "currency_or_base": "USD",
        "gross_receipts": "3000.00",
        "refund_amount": "0.00",
        "net_receipts": "3000.00",
        "service_revenue": "3000.00",
        "ads_client_funds": "2000.00",
        "recognized_ad_spread": "0.00",
        "deduction_rate": "0.0500",
        "deduction_amount": "150.00",
        "stripe_platform_fee": "0.00",
        "channel_commission": "0.00",
        "cost": "2000.00",
        "profit": "850.00",
        "notes": "management_fee 15%; ads recharge held as client funds",
    }]


@pytest.mark.asyncio
async def test_aggregate_monthly_separates_customer_costs_and_operating_currencies():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE payments (
                    id INTEGER PRIMARY KEY,
                    customer_id INTEGER,
                    customer_name TEXT,
                    income_type TEXT,
                    amount_paid REAL,
                    payment_date TEXT
                )
            """))
            await conn.execute(text("""
                CREATE TABLE expenses (
                    customer_id INTEGER,
                    customer_name TEXT,
                    expense_type TEXT,
                    amount REAL,
                    expense_month TEXT,
                    created_at TEXT
                )
            """))
            await conn.execute(text("""
                CREATE TABLE company_expenses (
                    amount REAL,
                    currency TEXT,
                    expense_month TEXT,
                    created_at TEXT
                )
            """))
            await conn.execute(text("""
                CREATE TABLE commission_entries (
                    service_month TEXT,
                    currency TEXT,
                    commission_amount REAL,
                    status TEXT
                )
            """))
            await conn.execute(text("""
                INSERT INTO payments (id, customer_id, customer_name, income_type, amount_paid, payment_date)
                VALUES
                  (1, 1, 'A Cafe', 'management_fee', 1000, '2026-06-10'),
                  (2, 1, 'A Cafe', 'ads_fee', 2000, '2026-06-10')
            """))
            await conn.execute(text("""
                INSERT INTO expenses (customer_id, customer_name, expense_type, amount, expense_month, created_at)
                VALUES (1, 'A Cafe', 'website_fee', 250, '2026-06', '2026-06-15')
            """))
            await conn.execute(text("""
                INSERT INTO company_expenses (amount, currency, expense_month, created_at)
                VALUES
                  (100, 'USD', '2026-06', '2026-06-15'),
                  (500, 'CNY', '2026-06', '2026-06-15'),
                  (300, NULL, '2026-06', '2026-06-15')
            """))
            await conn.execute(text("""
                INSERT INTO commission_entries (service_month, currency, commission_amount, status)
                VALUES
                  ('2026-06', 'USD', 200, 'confirmed'),
                  ('2026-06', 'USD', 50, 'payable'),
                  ('2026-06', 'USD', 25, 'paid'),
                  ('2026-06', 'USD', 500, 'pending_confirmation')
            """))

        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as db:
            data, months = await _aggregate_monthly(db, "2026-06-01", "2026-06-30")

        assert months == ["2026-06"]
        assert data["USD"]["2026-06"]["revenue_gross"] == 1000.0
        assert data["USD"]["2026-06"]["management_revenue"] == 1000.0
        assert data["USD"]["2026-06"]["ads_recharge_revenue"] == 2000.0
        assert data["USD"]["2026-06"]["channel_commission"] == 275.0
        assert data["USD"]["2026-06"]["cost"] == 625.0
        assert data["CNY"]["2026-06"]["revenue_gross"] == 0.0
        assert data["CNY"]["2026-06"]["cost"] == 800.0

        rows = _apply_deductions(data, months, {"2026-06": 0.15}, 0.15, None)
        usd_row = next(row for row in rows if row["currency_or_base"] == "USD")
        cny_row = next(row for row in rows if row["currency_or_base"] == "CNY")

        assert usd_row["channel_commission"] == "275.00"
        assert usd_row["cost"] == "625.00"
        assert usd_row["stripe_platform_fee"] == "0.00"
        assert usd_row["profit"] == "225.00"
        assert usd_row["notes"] == "management_fee 15%; ads recharge held as client funds"
        assert cny_row["cost"] == "800.00"
        assert cny_row["stripe_platform_fee"] == "0.00"
        assert cny_row["profit"] == "-800.00"
    finally:
        await engine.dispose()


def test_coerce_date_supports_iso_date_strings():
    parsed = _coerce_date("2026-06-15T10:30:00")
    assert parsed is not None
    assert parsed.isoformat() == "2026-06-15"
