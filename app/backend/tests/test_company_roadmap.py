from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.services.emp_auth import create_access_token
from core.database import Base, get_db
from models.ad_fund_settlements import AdFundSettlement
from models.commissions import CommissionAgreement, CommissionEntry, CustomerCommissionAttribution, SalesPartner
from models.customers import Customers
from models.management_decisions import BusinessLine, CustomerEngagement, ProductCatalog


def auth_headers(role: str, employee_id: int) -> dict[str, str]:
    token = create_access_token({
        "emp_id": employee_id,
        "email": f"{employee_id}@test.local",
        "role": role,
        "name": role,
    })
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def roadmap_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    now = datetime(2026, 8, 12, tzinfo=timezone.utc)
    async with sessions() as session:
        session.add_all([
            BusinessLine(id=1, code="managed_service", name="代运营", is_recurring=True, is_active=True),
            ProductCatalog(id=1, business_line_id=1, code="managed", name="代运营", billing_kind="recurring", default_currency="USD", is_active=True),
            Customers(id=1, customer_code="C-0001", business_name="The Q", contact_name="Owner", phone="555-0101", status="closed"),
            CustomerEngagement(
                id=1,
                customer_id=1,
                business_line_id=1,
                product_id=1,
                engagement_code="ENG-1",
                status="active_paid",
                paid_started_at=now,
                currency="USD",
            ),
            AdFundSettlement(
                id=1,
                customer_id=1,
                customer_name="The Q",
                year_month="2026-07",
                currency="USD",
                opening_balance=0,
                funds_received=6000,
                actual_ad_spend=2555.4,
                customer_refund_amount=0,
                recognized_spread_amount=444.6,
                adjustment_amount=0,
                closing_balance=3000,
                status="closed",
                recorded_by="admin",
                created_at=now,
                updated_at=now,
                user_id="1",
            ),
            SalesPartner(id=1, partner_code="P-1", name="Annie", partner_type="sales_partner", status="active", joined_at=date(2026, 1, 1)),
            CommissionAgreement(id=1, partner_id=1, version=1, first_order_rate=0.5, renewal_rate=0.1, activity_decay_json="{}", effective_from=date(2026, 1, 1), status="active"),
            CustomerCommissionAttribution(id=1, customer_id=1, partner_id=1, attribution_role="primary", effective_from=date(2026, 1, 1), is_active=True),
            CommissionEntry(
                id=1,
                partner_id=1,
                agreement_id=1,
                attribution_id=1,
                customer_id=1,
                engagement_id=1,
                payment_id=1,
                entry_type="renewal",
                status="payable",
                service_month="2026-08",
                occurred_at=now,
                currency="USD",
                gross_receipt_amount=1000,
                eligible_service_amount=1000,
                contract_rate=0.1,
                inactivity_months=0,
                activity_multiplier=1,
                commission_amount=100,
                snapshot_json="{}",
                idempotency_key="commission-1",
            ),
        ])
        await session.commit()

    async def override_db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_roadmap_is_finance_only_and_does_not_seed_estimated_cash(roadmap_client: AsyncClient):
    denied = await roadmap_client.get("/api/v1/company-roadmap/overview", headers=auth_headers("ops", 5))
    assert denied.status_code == 403
    finance_allowed = await roadmap_client.get(
        "/api/v1/company-roadmap/overview", headers=auth_headers("finance", 6),
    )
    assert finance_allowed.status_code == 200
    finance_cannot_change_strategy = await roadmap_client.put(
        "/api/v1/company-roadmap/settings",
        headers=auth_headers("finance", 6),
        json={
            "target_start_date": "2026-01-01",
            "target_end_date": "2030-12-31",
            "five_year_profit_target_cny": 20_000_000,
            "monthly_fixed_expense_cny": 30_000,
            "cash_reserve_months": 6,
            "default_usd_cny_rate": 6.7,
            "current_focus": "test",
        },
    )
    assert finance_cannot_change_strategy.status_code == 403

    response = await roadmap_client.get("/api/v1/company-roadmap/overview", headers=auth_headers("admin", 1))
    assert response.status_code == 200
    payload = response.json()
    assert payload["settings"]["five_year_profit_target_cny"] == 20_000_000
    assert payload["settings"]["cash_safety_target_cny"] == 180_000
    assert payload["cash_period"] is None
    assert payload["cash_health"]["free_cash_cny"] is None
    assert payload["recommendation"]["key"] == "establish_cash_baseline"
    assert payload["goal"]["has_profit_data"] is False
    assert payload["goal"]["is_complete_data"] is False
    assert payload["goal"]["pace_status"] == "data_incomplete"
    assert payload["operating_signals"]["profit_sample_months"] == 0
    assert payload["operating_signals"]["three_month_average_profit_cny"] is None
    assert payload["cash_health"]["projections"] == []
    assert payload["operating_signals"]["paid_restaurant_os_projects"] == 0
    assert payload["operating_signals"]["paid_beauty_os_projects"] == 0
    assert payload["operating_signals"]["team_capacity"]["active_projects"] == 1
    assert [row["status"] for row in payload["milestones"]] == ["current", "pending", "pending", "pending", "pending"]

    future = await roadmap_client.put(
        "/api/v1/company-roadmap/cash-periods/2026-09",
        headers=auth_headers("admin", 1),
        json={"snapshot_date": "2026-09-01", "usd_cny_rate": 6.7, "balances": [], "restrictions": []},
    )
    assert future.status_code == 400


@pytest.mark.asyncio
async def test_cash_snapshot_calculates_free_cash_and_locks_with_audit(roadmap_client: AsyncClient):
    headers = auth_headers("admin", 1)
    cny_account = await roadmap_client.post(
        "/api/v1/company-roadmap/cash-accounts",
        headers=headers,
        json={"name": "公司人民币账户", "account_type": "bank", "currency": "CNY"},
    )
    usd_account = await roadmap_client.post(
        "/api/v1/company-roadmap/cash-accounts",
        headers=headers,
        json={"name": "公司美元账户", "account_type": "bank", "currency": "USD"},
    )
    assert cny_account.status_code == 201
    assert usd_account.status_code == 201
    unsafe_account = await roadmap_client.post(
        "/api/v1/company-roadmap/cash-accounts",
        headers=headers,
        json={
            "name": "不应保存完整账号",
            "account_type": "bank",
            "currency": "CNY",
            "masked_identifier": "6222021234567890",
        },
    )
    assert unsafe_account.status_code == 422

    overview = (await roadmap_client.get("/api/v1/company-roadmap/overview", headers=headers)).json()
    suggestions = overview["restriction_suggestions"]
    assert {(row["category"], row["amount"]) for row in suggestions} == {
        ("client_ad_funds", 3000.0),
        ("commission_payable", 100.0),
    }

    saved = await roadmap_client.put(
        "/api/v1/company-roadmap/cash-periods/2026-08",
        headers=headers,
        json={
            "snapshot_date": "2026-08-12",
            "usd_cny_rate": 6.7,
            "notes": "首次真实余额确认",
            "balances": [
                {"account_id": cny_account.json()["id"], "balance": 20_000},
                {"account_id": usd_account.json()["id"], "balance": 10_000},
            ],
            "restrictions": suggestions,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["totals"] == {
        "account_balance_cny": 87_000.0,
        "restricted_cny": 20_770.0,
        "free_cash_cny": 66_230.0,
    }
    draft_overview = (await roadmap_client.get(
        "/api/v1/company-roadmap/overview?month=2026-08", headers=headers,
    )).json()
    assert draft_overview["cash_period"]["status"] == "draft"
    assert draft_overview["cash_health"]["free_cash_cny"] is None
    assert draft_overview["recommendation"]["key"] == "establish_cash_baseline"

    missing_suggestions = await roadmap_client.put(
        "/api/v1/company-roadmap/cash-periods/2026-08",
        headers=headers,
        json={
            "snapshot_date": "2026-08-12",
            "usd_cny_rate": 6.7,
            "balances": [
                {"account_id": cny_account.json()["id"], "balance": 20_000},
                {"account_id": usd_account.json()["id"], "balance": 10_000},
            ],
            "restrictions": [],
        },
    )
    assert missing_suggestions.status_code == 200
    rejected_lock = await roadmap_client.post(
        "/api/v1/company-roadmap/cash-periods/2026-08/transition",
        headers=headers,
        json={"action": "lock"},
    )
    assert rejected_lock.status_code == 409
    assert "系统受限资金建议未加入" in rejected_lock.json()["detail"]
    restored = await roadmap_client.put(
        "/api/v1/company-roadmap/cash-periods/2026-08",
        headers=headers,
        json={
            "snapshot_date": "2026-08-12",
            "usd_cny_rate": 6.7,
            "notes": "首次真实余额确认",
            "balances": [
                {"account_id": cny_account.json()["id"], "balance": 20_000},
                {"account_id": usd_account.json()["id"], "balance": 10_000},
            ],
            "restrictions": suggestions,
        },
    )
    assert restored.status_code == 200

    locked = await roadmap_client.post(
        "/api/v1/company-roadmap/cash-periods/2026-08/transition",
        headers=headers,
        json={"action": "lock"},
    )
    assert locked.status_code == 200
    assert locked.json()["status"] == "locked"
    locked_overview = (await roadmap_client.get(
        "/api/v1/company-roadmap/overview?month=2026-08", headers=headers,
    )).json()
    assert locked_overview["cash_health"]["free_cash_cny"] == 66_230.0
    assert locked_overview["cash_health"]["as_of_month"] == "2026-08"
    assert locked_overview["recommendation"]["key"] == "reach_cash_safety_line"
    assert [row["status"] for row in locked_overview["milestones"]] == ["completed", "current", "pending", "pending", "pending"]

    decision = await roadmap_client.post(
        "/api/v1/company-roadmap/recommendations/reach_cash_safety_line/decision",
        headers=headers,
        json={
            "status": "accepted",
            "decision_note": "本月优先补足现金安全线",
            "next_review_date": "2026-08-31",
            "create_task": True,
        },
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["task_id"] is not None
    decided_overview = (await roadmap_client.get(
        "/api/v1/company-roadmap/overview?month=2026-08", headers=headers,
    )).json()
    assert decided_overview["recommendation"]["decision"]["status"] == "accepted"
    assert decided_overview["recommendation"]["decision"]["task_id"] == decision.json()["task_id"]

    blocked = await roadmap_client.put(
        "/api/v1/company-roadmap/cash-periods/2026-08",
        headers=headers,
        json={"snapshot_date": "2026-08-12", "usd_cny_rate": 6.7, "balances": [], "restrictions": []},
    )
    assert blocked.status_code == 409

    reopened = await roadmap_client.post(
        "/api/v1/company-roadmap/cash-periods/2026-08/transition",
        headers=headers,
        json={"action": "reopen", "reason": "银行补录一笔在途款"},
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "draft"
    audit = await roadmap_client.get("/api/v1/company-roadmap/cash-periods/2026-08/audit", headers=headers)
    assert audit.status_code == 200
    assert [row["action"] for row in audit.json()] == ["reopen", "lock", "saved", "saved", "saved"]

    historical = await roadmap_client.put(
        "/api/v1/company-roadmap/cash-periods/2026-06",
        headers=headers,
        json={
            "snapshot_date": "2026-06-30",
            "usd_cny_rate": 6.7,
            "balances": [{"account_id": cny_account.json()["id"], "balance": 200_000}],
            "restrictions": [],
        },
    )
    assert historical.status_code == 200
    historical_lock = await roadmap_client.post(
        "/api/v1/company-roadmap/cash-periods/2026-06/transition",
        headers=headers,
        json={"action": "lock"},
    )
    assert historical_lock.status_code == 200
    stale_overview = (await roadmap_client.get(
        "/api/v1/company-roadmap/overview?month=2026-06", headers=headers,
    )).json()
    assert stale_overview["cash_health"]["is_stale"] is True
    assert stale_overview["cash_health"]["level"] == "stale"
    assert stale_overview["cash_health"]["projections"] == []
    assert stale_overview["recommendation"]["key"] == "refresh_cash_snapshot"
