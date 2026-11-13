from datetime import date, datetime, timezone

import pytest

from backend.tests.test_management_decision_workflow import auth_headers, workflow_context

from models.customer_callbacks import Customer_callbacks
from models.customers import Customers
from models.finance_refunds import FinanceRefund
from models.management_decisions import CustomerEngagement, EngagementSourceLink
from models.payments import Payments
from models.subscriptions import Subscriptions
from models.tasks import Tasks
from services import business_intelligence as bi


DAY = date(2026, 11, 14)


def project(project_id, product, customer=17):
    return CustomerEngagement(id=project_id, customer_id=customer, business_line_id=product,
                              product_id=product, status="active_paid", paid_started_at=date(2026, 10, 1))


def base_rows(*projects):
    return {
        "projects": projects,
        "customer_by_id": {
            project.customer_id: Customers(id=project.customer_id, business_name=f"店 {project.customer_id}")
            for project in projects
        },
        "line_by_id": {}, "employee_by_id": {},
        "tasks": [], "service_tasks": [], "progresses": [], "callbacks": [],
        "payments": [], "subscriptions": [], "refunds": [],
    }


@pytest.mark.asyncio
async def test_different_projects_keep_their_own_money_expiry_and_refund():
    base = base_rows(project(10, 1), project(20, 2), project(30, 1, customer=18))
    base["payments"] = [
        Payments(id=41, customer_id=17, engagement_id=10, outstanding_amount=198, currency="USD"),
        Payments(id=42, customer_id=17, business_line_id=1, outstanding_amount=500, currency="CNY"),
        Payments(id=43, customer_id=17, engagement_id=30, outstanding_amount=999, currency="USD"),
        Payments(id=44, customer_id=17, engagement_id=10, business_line_id=2, outstanding_amount=7, currency="USD"),
        Payments(id=45, customer_id=17, outstanding_amount=3, currency="USD"),
    ]
    base["subscriptions"] = [Subscriptions(id=54, customer_id=17, status="active", end_date=DAY)]
    base["health_confirmed_sources"] = [
        ("subscription", 54, 20), ("payment", 45, 10), ("payment", 45, 20),
    ]
    base["refunds"] = [
        FinanceRefund(id=70, customer_id=17, payment_id=41, refund_date=DAY),
        FinanceRefund(id=71, customer_id=18, payment_id=41, refund_date=DAY),
    ]
    health = await bi.build_customer_health(None, base=base, today=DAY)
    items = {item["project_id"]: item for item in health["items"]}
    assert {key: item["score"] for key, item in items.items()} == {10: 60, 20: 90, 30: 100}
    message = items[10]["reasons"][0]["message"]
    assert "CNY 500.00" in message and "USD 198.00" in message
    assert items[20]["reasons"][0]["code"] == "subscription_due_soon"
    shared = {item["customer_id"]: item for item in health["customer_signals"]}
    assert "USD 1,009.00" in shared[17]["reasons"][0]["message"]
    assert shared[18]["reasons"][0]["code"] == "recent_refund"


@pytest.mark.asyncio
async def test_shared_signals_enter_scan_once_without_exposing_amount_or_scoring_their_own_followup(monkeypatch):
    base = base_rows(project(10, 1), project(20, 2), project(30, 1, customer=18))
    base["payments"] = [Payments(id=1, customer_id=17, outstanding_amount=198, currency="USD")]
    base["subscriptions"] = [Subscriptions(id=2, customer_id=17, status="active", end_date=date(2026, 11, 8))]
    base["callbacks"] = [
        Customer_callbacks(id=3, customer_id=17, status="pending", callback_date=date(2026, 11, 7)),
        Customer_callbacks(id=4, customer_id=18, status="pending", callback_date=date(2026, 11, 7)),
    ]
    base["tasks"] = [
        Tasks(id=7, customer_id=17, automation_issue_id=66, status="pending", due_date=date(2026, 11, 6)),
        Tasks(id=8, customer_id=17, automation_issue_id=67, status="pending", due_date=date(2026, 11, 6)),
    ]
    base["health_task_sources"] = {7: (17, 10, "customer_health_risk", None, None),
                                   8: (17, 20, "delivery_task_overdue", None, None)}

    async def read_base(db):
        return base

    monkeypatch.setattr(bi, "_base_rows", read_base)
    result = await bi.build_customer_health(None, today=DAY)
    assert {row["project_id"]: row["score"] for row in result["items"]} == {10: 100, 20: 92, 30: 90}
    assert [(row["customer_id"], row["score"]) for row in result["customer_signals"]] == [(17, 35)]
    anomalies = await bi.health_risk_anomalies(None, today=DAY)
    assert [(row["customer_id"], row["project_id"], row["severity"]) for row in anomalies] == [(17, None, "high")]
    assert "198" not in anomalies[0]["message"]


@pytest.mark.asyncio
async def test_owner_dashboard_reads_confirmed_sources_without_reassigning_records(workflow_context, monkeypatch):
    monkeypatch.setattr(bi, "_observation_day", lambda: date(2026, 11, 15))
    client, sessions = workflow_context
    async with sessions() as db:
        for code in ("A", "B"):
            db.add(CustomerEngagement(id=1 if code == "A" else 2, engagement_code=code, customer_id=11,
                                      business_line_id=1, product_id=1, status="active_paid", paid_started_at=date(2026, 10, 1)))
        payment = await db.get(Payments, 102)
        payment.outstanding_amount = 198
        await db.flush()
        db.add(EngagementSourceLink(engagement_id=2, source_type="payment", source_id=102,
                                    link_role="business_line:managed_service", confidence="confirmed"))
        db.add(Customer_callbacks(customer_id=11, status="pending", callback_date=DAY))
        await db.commit()

    url = "/api/v1/management-decisions/growth-dashboard?start_date=2026-11-01&end_date=2026-11-15"
    for role in ("sales", "finance", "admin"):
        denied = await client.get(url, headers=auth_headers(role, 7))
        assert denied.status_code == 403
    for end_date in ("2026-09-30", "2026-11-30"):
        report = f"/api/v1/management-decisions/growth-dashboard?start_date=2026-08-01&end_date={end_date}"
        response = await client.get(report, headers=auth_headers("super_admin", 1))
        assert response.status_code == 200, response.text
        dashboard = response.json()
        health = dashboard["customer_health"]
        assert dashboard["period"]["end_date"] == end_date
        assert health["updated_through"] == dashboard["team_capacity"]["observed_on"] == "2026-11-15"
        assert {row["project_id"]: row["score"] for row in health["items"]} == {1: 100, 2: 75}
        assert [(row["customer_id"], row["reasons"][0]["code"]) for row in health["customer_signals"]] == [
            (11, "overdue_callback")
        ]
    async with sessions() as db:
        assert (await db.get(Payments, 102)).engagement_id is None


@pytest.mark.asyncio
async def test_waits_for_operating_evidence_and_excludes_historical_projects_from_health(monkeypatch):
    projects = [project(key, 1) for key in range(1, 9)]
    for p, status in zip(projects, ("pending_setup", "trial", "active_paid", "trial", "trial", "completed", "stopped", "trial")):
        p.status = status
        p.paid_started_at = None
    base = base_rows(*projects)
    base["payments"] = [
        Payments(id=1, customer_id=17, engagement_id=4, amount_paid=198, payment_date=DAY, currency="USD"),
        Payments(id=2, customer_id=17, engagement_id=5, outstanding_amount=198, currency="USD"),
        Payments(id=3, customer_id=17, engagement_id=6, outstanding_amount=198, currency="USD"),
        Payments(id=4, customer_id=17, engagement_id=8, amount_paid=198, payment_date=date(2027, 1, 1)),
    ]
    async def read_base(db):
        return base

    monkeypatch.setattr(bi, "_base_rows", read_base)
    result = await bi.build_customer_health(None, today=DAY)
    assert {row["project_id"] for row in result["observing_projects"]} == {1, 2, 3, 8}
    assert {row["project_id"]: row["score"] for row in result["items"]} == {4: 100, 5: 75}
    assert result["summary"] == {"healthy": 1, "watch": 1}
    assert not result["customer_signals"]
    assert not await bi.health_risk_anomalies(None, today=DAY)


def test_beijing_observation_day_rolls_over_at_1600_utc():
    assert bi._observation_day(datetime(2026, 11, 13, 15, 59, tzinfo=timezone.utc)) == date(2026, 11, 13)
    assert bi._observation_day(datetime(2026, 11, 13, 16, 0, tzinfo=timezone.utc)) == date(2026, 11, 14)
