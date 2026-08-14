from datetime import date, datetime, timezone
import json
from types import SimpleNamespace

import pytest

from services.business_intelligence import (
    build_formal_monthly_profit,
    build_os_paid_customer_evidence,
    build_team_capacity,
)
from services.company_roadmap import (
    _current_recommendation,
    _profit_stability_evidence,
    _recommendation_decision_payload,
)


def _profit_base(**overrides):
    base = {
        "exchange_rates": [],
        "profit_closes": [],
        "payroll_sheets": [],
        "payroll_items": [],
        "payments": [],
        "refunds": [],
        "settlements": [],
        "expenses": [],
        "commissions": [],
        "company_expenses": [],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_formal_profit_ignores_paid_payroll_and_deducts_finance_wage_expense_once():
    finance_wage = SimpleNamespace(
        expense_month="2026-02",
        expense_date=None,
        created_at=None,
        category="工资",
        category_name="工资",
        notes="二月工资",
        currency="CNY",
        amount=600,
    )
    result = await build_formal_monthly_profit(
        None,
        start_date=date(2026, 2, 1),
        end_date=date(2026, 2, 28),
        base=_profit_base(
            company_expenses=[finance_wage],
            # Sentinels intentionally have no payroll attributes. Formal profit
            # must not inspect or depend on the independent payroll ledger.
            payroll_sheets=[object()],
            payroll_items=[object()],
        ),
    )

    row = result["rows"][0]
    assert row["formal_profit_cny"] == -600
    assert row["total_cost_cny_equivalent"] == 600
    assert row["payroll_cost_cny"] == 600
    assert row["payroll_source"] == "company_expense"
    assert result["data_quality"]["payroll_accounting_source"] == "company_expenses_only"


@pytest.mark.asyncio
async def test_legacy_locked_payroll_snapshot_requires_reclose_and_does_not_drive_profit():
    legacy_close = SimpleNamespace(
        year_month="2026-02",
        status="locked",
        snapshot_json=json.dumps({
            "year_month": "2026-02",
            "formal_profit_cny": -1000,
            "payroll_cost_cny": 1000,
            "payroll_source": "paid_payroll",
        }),
        locked_by="Owner",
        locked_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )
    result = await build_formal_monthly_profit(
        None,
        start_date=date(2026, 2, 1),
        end_date=date(2026, 2, 28),
        base=_profit_base(profit_closes=[legacy_close]),
    )

    row = result["rows"][0]
    assert row["formal_profit_cny"] == 0
    assert row["payroll_cost_cny"] == 0
    assert row["close_status"] == "locked"
    assert row["reopen_required"] is True
    assert row["profit_policy_valid"] is False
    assert "重新打开" in row["close_policy_issue"]

    stability = _profit_stability_evidence([row], date(2026, 3, 14))
    assert stability["ready"] is False
    assert stability["policy_mismatch_months"] == ["2026-02"]


def test_profit_stability_requires_exact_recent_calendar_months_locked_and_each_positive():
    today = date(2026, 8, 14)
    rows = [
        {"year_month": "2026-05", "close_status": "locked", "formal_profit_cny": 100},
        {"year_month": "2026-06", "close_status": "locked", "formal_profit_cny": 100},
        # The three-month average remains positive, but one losing month must
        # keep the milestone closed.
        {"year_month": "2026-07", "close_status": "locked", "formal_profit_cny": -50},
    ]
    losing = _profit_stability_evidence(rows, today)
    assert losing["required_months"] == ["2026-05", "2026-06", "2026-07"]
    assert losing["ready"] is False
    assert losing["non_positive_months"] == ["2026-07"]
    assert losing["average_profit_cny"] is None

    rows[-1]["formal_profit_cny"] = 50
    rows[1]["close_status"] = "open"
    unlocked = _profit_stability_evidence(rows, today)
    assert unlocked["ready"] is False
    assert unlocked["unlocked_months"] == ["2026-06"]

    rows[1]["close_status"] = "locked"
    ready = _profit_stability_evidence(rows, today)
    assert ready["ready"] is True
    assert ready["is_stable"] is True
    assert ready["qualifying_months"] == ["2026-05", "2026-06", "2026-07"]
    assert ready["average_profit_cny"] == 83.33


def test_os_stage_counts_linked_receipts_by_business_line_and_distinct_customer():
    restaurant = SimpleNamespace(id=1, code="restaurant_os")
    beauty = SimpleNamespace(id=2, code="beauty_os")
    projects = [
        SimpleNamespace(id=101, customer_id=1, business_line_id=1, status="active_paid"),
        SimpleNamespace(id=102, customer_id=1, business_line_id=1, status="active_paid"),
        SimpleNamespace(id=103, customer_id=2, business_line_id=1, status="reactivated"),
        SimpleNamespace(id=201, customer_id=3, business_line_id=2, status="active_paid"),
        SimpleNamespace(id=202, customer_id=4, business_line_id=2, status="active_paid"),
        SimpleNamespace(id=203, customer_id=5, business_line_id=2, status="active_paid"),
    ]

    def receipt(payment_id, customer_id, engagement_id, business_line_id):
        return SimpleNamespace(
            id=payment_id,
            customer_id=customer_id,
            engagement_id=engagement_id,
            business_line_id=business_line_id,
            amount_paid=100,
            management_amount=100,
            ads_recharge_amount=0,
            income_type="subscription",
            payment_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

    evidence = build_os_paid_customer_evidence({
        "line_by_id": {1: restaurant, 2: beauty},
        "projects": projects,
        "payments": [
            receipt(1, 1, 101, 1),
            receipt(2, 1, 102, 1),  # same customer must not count twice
            receipt(3, 2, 103, 1),
            receipt(4, 3, 201, 2),
            receipt(5, 4, None, 2),  # OS-tagged but not linked: conservative zero
            receipt(6, 999, 103, 1),  # linked project/customer conflict
            receipt(7, 5, 203, 2),  # fully refunded: no longer a real receipt
        ],
        "refunds": [SimpleNamespace(payment_id=7, refund_amount=100)],
    })

    assert evidence["by_business_line"] == {"beauty_os": 1, "restaurant_os": 2}
    assert evidence["unverified_active_paid_customers"] == {"beauty_os": 2, "restaurant_os": 0}
    assert evidence["excluded_unlinked_receipts"] == 1
    assert evidence["excluded_mismatched_receipts"] == 1
    assert evidence["excluded_fully_refunded_receipts"] == 1
    assert evidence["data_sufficient"] is False
    assert "不能保守计入" in evidence["explanation"]


def test_recommendation_decision_exposes_task_progress_and_handles_missing_task():
    decided_at = datetime(2026, 8, 14, tzinfo=timezone.utc)
    completed_at = datetime(2026, 8, 15, tzinfo=timezone.utc)
    decision = SimpleNamespace(
        status="completed",
        decision_note="已执行",
        next_review_date=date(2026, 8, 31),
        task_id=42,
        decided_at=decided_at,
        decided_by_name="Owner",
    )
    task = SimpleNamespace(
        status="completed",
        assignee_name="Ops",
        completion_result="结果已复核",
        completed_at=completed_at,
    )

    payload = _recommendation_decision_payload(decision, task)
    assert payload["task_status"] == "completed"
    assert payload["task_assignee_name"] == "Ops"
    assert payload["task_completion_result"] == "结果已复核"
    assert payload["task_completed_at"] == completed_at

    missing_task = _recommendation_decision_payload(decision, None)
    assert missing_task["task_id"] == 42
    assert missing_task["task_status"] is None
    assert missing_task["task_assignee_name"] is None
    assert missing_task["task_completion_result"] is None
    assert missing_task["task_completed_at"] is None


@pytest.mark.asyncio
async def test_capacity_snapshot_starts_observation_instead_of_recommending_hire(monkeypatch):
    import services.sales_lead_cycle as sales_lead_cycle

    async def fake_sales_overview(_db):
        return {"estimated_pool_days": 30}

    monkeypatch.setattr(sales_lead_cycle, "automation_overview", fake_sales_overview)
    employee = SimpleNamespace(id=1, name="Ops", role="ops", status="active")
    project = SimpleNamespace(id=1, owner_employee_id=1, status="active_paid")
    overdue = SimpleNamespace(
        status="pending",
        assignee_id=1,
        assignee_name="Ops",
        due_date=date(2000, 1, 1),
    )
    result = await build_team_capacity(
        None,
        project_capacity_target=1,
        capacity_warning_ratio=0.85,
        base={
            "projects": [project],
            "tasks": [overdue],
            "service_tasks": [],
            "employee_by_id": {1: employee},
        },
    )

    recommendation = result["recommendations"][0]
    assert recommendation["level"] == "observe"
    assert recommendation["title"] == "开始 4 周产能观察"
    assert "单次快照" in recommendation["message"]
    assert result["summary"]["history_persisted"] is False
    assert result["summary"]["hiring_gate_ready"] is False

    roadmap_recommendation = _current_recommendation(
        cash_period={"snapshot_date": date.today(), "year_month": date.today().strftime("%Y-%m"), "totals": {"free_cash_cny": 1_000_000}},
        cash_target=100_000,
        three_month_average_profit=10_000,
        active_managed=1,
        os_paid=10,
        leading_os_name="餐饮 OS",
        risk_ratio=0,
        health_total=1,
        profit_sample_months=3,
        profit_stability_ready=True,
        os_evidence_explanation=None,
        os_evidence_sufficient=True,
        capacity_near_or_over=1,
        capacity_overdue_rate=0.2,
    )
    assert roadmap_recommendation["key"] == "start_capacity_observation"
    assert roadmap_recommendation["title"] == "开始 4 周产能观察"
    assert "没有持久化的连续周证据" in roadmap_recommendation["why"]


@pytest.mark.asyncio
async def test_future_strategy_start_returns_empty_profit_period_instead_of_crashing():
    result = await build_formal_monthly_profit(
        None,
        start_date=date(2027, 1, 1),
        end_date=date(2026, 8, 14),
        base=_profit_base(),
    )

    assert result["rows"] == []
    assert result["summary"] == {
        "label": "2027-01-01 至 2026-08-14",
        "start_month": None,
        "end_month": None,
        "month_count": 0,
        "ready_month_count": 0,
        "locked_month_count": 0,
        "recognized_revenue_cny": None,
        "cash_revenue_cny": None,
        "total_cost_cny": None,
        "operating_profit_cny": None,
        "cash_profit_cny": None,
        "operating_margin": None,
        "status": "no_period",
    }
