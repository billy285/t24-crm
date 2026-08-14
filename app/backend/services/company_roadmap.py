from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import json
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.ad_fund_settlements import AdFundSettlement
from models.commissions import CommissionEntry
from models.company_roadmap import (
    CashAccount,
    CashAccountBalance,
    CashAuditLog,
    CashPeriod,
    CashRestriction,
    CompanyStrategySettings,
    StrategyRecommendationDecision,
)
from models.finance_refunds import FinanceRefund
from models.employees import Employees
from models.management_decisions import BusinessLine, CustomerEngagement
from models.payroll import PayrollItems, PayrollSheets
from models.tasks import Tasks
from services.business_intelligence import build_growth_dashboard


DEFAULT_SETTINGS = {
    "settings_key": "company",
    "target_start_date": date(2026, 1, 1),
    "target_end_date": date(2030, 12, 31),
    "five_year_profit_target_cny": 20_000_000.0,
    "monthly_fixed_expense_cny": 30_000.0,
    "cash_reserve_months": 6,
    "default_usd_cny_rate": 6.7,
    "current_focus": "先建立真实现金底账并达到 6 个月安全储备，再决定新增投入。",
}

RESTRICTION_LABELS = {
    "client_ad_funds": "客户投流/代充值资金",
    "refund_payable": "待退客户款",
    "payroll_payable": "已确认未发工资",
    "commission_payable": "待付渠道分润",
    "tax_reserve": "税务预留",
    "accounts_payable": "已确认未付款项",
    "other_restricted": "其他受限资金",
}

ACTIVE_PROJECT_STATUSES = {
    "pending_setup", "trial", "active_paid", "at_risk", "paused", "pending_stop", "reactivated",
}


def money(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def actor_name(user: Any) -> str:
    return user.name or user.email or str(user.id)


def _recommendation_decision_payload(
    decision: Optional[StrategyRecommendationDecision],
    task: Optional[Tasks],
) -> Optional[dict[str, Any]]:
    if not decision:
        return None
    return {
        "status": decision.status,
        "decision_note": decision.decision_note,
        "next_review_date": decision.next_review_date,
        "task_id": decision.task_id,
        "task_status": task.status if task else None,
        "task_assignee_name": task.assignee_name if task else None,
        "task_completion_result": task.completion_result if task else None,
        "task_completed_at": task.completed_at if task else None,
        "decided_at": decision.decided_at,
        "decided_by_name": decision.decided_by_name,
    }


def settings_payload(row: Optional[CompanyStrategySettings]) -> dict[str, Any]:
    source = row or DEFAULT_SETTINGS
    value = lambda key: getattr(source, key) if row else source[key]
    monthly = money(value("monthly_fixed_expense_cny"))
    reserve_months = int(value("cash_reserve_months"))
    return {
        "configured": row is not None,
        "target_start_date": value("target_start_date"),
        "target_end_date": value("target_end_date"),
        "five_year_profit_target_cny": money(value("five_year_profit_target_cny")),
        "monthly_fixed_expense_cny": monthly,
        "cash_reserve_months": reserve_months,
        "cash_safety_target_cny": round(monthly * reserve_months, 2),
        "default_usd_cny_rate": round(float(value("default_usd_cny_rate")), 4),
        "current_focus": value("current_focus"),
        "updated_at": row.updated_at if row else None,
        "updated_by": row.updated_by if row else None,
    }


def _balance_payload(row: CashAccountBalance, account: CashAccount) -> dict[str, Any]:
    return {
        "id": row.id,
        "account_id": account.id,
        "account_name": row.account_name or account.name,
        "account_type": row.account_type or account.account_type,
        "masked_identifier": row.masked_identifier if row.masked_identifier is not None else account.masked_identifier,
        "currency": row.currency,
        "balance": money(row.balance),
        "confirmed_zero": bool(row.confirmed_zero),
        "rate_to_cny": round(float(row.rate_to_cny or 1), 4),
        "balance_cny": money(row.balance_cny),
    }


def _restriction_payload(row: CashRestriction) -> dict[str, Any]:
    return {
        "id": row.id,
        "category": row.category,
        "category_label": RESTRICTION_LABELS.get(row.category, row.category),
        "description": row.description,
        "currency": row.currency,
        "amount": money(row.amount),
        "rate_to_cny": round(float(row.rate_to_cny or 1), 4),
        "amount_cny": money(row.amount_cny),
        "source_ref": row.source_ref,
        "notes": row.notes,
    }


async def cash_period_payload(db: AsyncSession, period: CashPeriod) -> dict[str, Any]:
    balance_rows = (
        await db.execute(
            select(CashAccountBalance, CashAccount)
            .join(CashAccount, CashAccount.id == CashAccountBalance.account_id)
            .where(CashAccountBalance.period_id == period.id)
            .order_by(CashAccount.sort_order, CashAccount.id)
        )
    ).all()
    restrictions = (
        await db.execute(
            select(CashRestriction)
            .where(CashRestriction.period_id == period.id)
            .order_by(CashRestriction.category, CashRestriction.id)
        )
    ).scalars().all()
    balances = [_balance_payload(row, account) for row, account in balance_rows]
    restriction_items = [_restriction_payload(row) for row in restrictions]
    total_balance = round(sum(row["balance_cny"] for row in balances), 2)
    restricted = round(sum(row["amount_cny"] for row in restriction_items), 2)
    return {
        "id": period.id,
        "version": int(period.version or 1),
        "year_month": period.year_month,
        "snapshot_date": period.snapshot_date,
        "status": period.status,
        "usd_cny_rate": round(float(period.usd_cny_rate), 4),
        "notes": period.notes,
        "locked_at": period.locked_at,
        "locked_by": period.locked_by,
        "reopened_at": period.reopened_at,
        "reopened_by": period.reopened_by,
        "reopen_reason": period.reopen_reason,
        "balances": balances,
        "restrictions": restriction_items,
        "totals": {
            "account_balance_cny": total_balance,
            "restricted_cny": restricted,
            "free_cash_cny": round(total_balance - restricted, 2),
        },
    }


async def add_cash_audit(
    db: AsyncSession,
    period: CashPeriod,
    user: Any,
    action: str,
    *,
    reason: Optional[str] = None,
) -> None:
    snapshot = await cash_period_payload(db, period)
    db.add(CashAuditLog(
        period_id=period.id,
        action=action,
        actor_id=str(user.id),
        actor_name=actor_name(user),
        actor_role=str(user.role or ""),
        reason=reason,
        snapshot_json=json.dumps(snapshot, ensure_ascii=False, default=str),
    ))


async def build_restriction_suggestions(db: AsyncSession, rate: float) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str], float] = defaultdict(float)

    settlements = (
        await db.execute(
            select(AdFundSettlement)
            .where(AdFundSettlement.status == "closed")
            .order_by(AdFundSettlement.customer_id, AdFundSettlement.currency, AdFundSettlement.year_month.desc(), AdFundSettlement.id.desc())
        )
    ).scalars().all()
    latest: dict[tuple[int, str], AdFundSettlement] = {}
    for row in settlements:
        latest.setdefault((int(row.customer_id), str(row.currency or "USD").upper()), row)
    for row in latest.values():
        if money(row.closing_balance) > 0:
            grouped[("client_ad_funds", str(row.currency or "USD").upper())] += money(row.closing_balance)

    pending_refunds = (
        await db.execute(select(FinanceRefund).where(FinanceRefund.status.notin_(["completed", "cancelled", "rejected"])))
    ).scalars().all()
    for row in pending_refunds:
        grouped[("refund_payable", str(row.currency or "USD").upper())] += money(row.refund_amount)

    sheets = (
        await db.execute(select(PayrollSheets).where(PayrollSheets.status == "confirmed"))
    ).scalars().all()
    if sheets:
        sheet_by_id = {int(row.id): row for row in sheets}
        payroll_items = (
            await db.execute(
                select(PayrollItems).where(
                    PayrollItems.sheet_id.in_(sheet_by_id),
                    PayrollItems.payment_status != "paid",
                )
            )
        ).scalars().all()
        for item in payroll_items:
            additions = sum(money(getattr(item, key, 0)) for key in (
                "base_salary", "fixed_performance", "commission", "bonus", "allowance", "reimbursement",
            ))
            deductions = sum(money(getattr(item, key, 0)) for key in (
                "absence_deduction", "performance_deduction", "salary_advance_deduction", "other_deduction",
            ))
            currency = str(sheet_by_id[int(item.sheet_id)].currency or "CNY").upper()
            grouped[("payroll_payable", currency)] += round(additions - deductions, 2)

    commissions = (
        await db.execute(select(CommissionEntry).where(CommissionEntry.status.in_(["confirmed", "payable"])))
    ).scalars().all()
    for row in commissions:
        grouped[("commission_payable", str(row.currency or "USD").upper())] += money(row.commission_amount)

    for (category, currency), amount in sorted(grouped.items()):
        if amount <= 0:
            continue
        applied_rate = rate if currency == "USD" else 1.0
        suggestions.append({
            "category": category,
            "category_label": RESTRICTION_LABELS[category],
            "description": f"系统根据现有记录建议：{RESTRICTION_LABELS[category]}",
            "currency": currency,
            "amount": round(amount, 2),
            "rate_to_cny": round(applied_rate, 4),
            "amount_cny": round(amount * applied_rate, 2),
            "source_ref": f"system:{category}:{currency}",
            "is_suggestion": True,
        })
    return suggestions


def _month_count(start: date, end: date) -> int:
    return max(1, (end.year - start.year) * 12 + end.month - start.month + 1)


def _recent_completed_months(today: date, count: int = 3) -> list[str]:
    cursor = date(today.year, today.month, 1)
    months: list[str] = []
    for _ in range(count):
        cursor = date(cursor.year - 1, 12, 1) if cursor.month == 1 else date(cursor.year, cursor.month - 1, 1)
        months.append(cursor.strftime("%Y-%m"))
    return list(reversed(months))


def _profit_stability_evidence(profit_rows: list[dict[str, Any]], today: date) -> dict[str, Any]:
    required_months = _recent_completed_months(today)
    row_by_month = {str(row.get("year_month") or "")[:7]: row for row in profit_rows}
    missing_months = [month for month in required_months if month not in row_by_month]
    unlocked_months = [
        month for month in required_months
        if month in row_by_month and row_by_month[month].get("close_status") != "locked"
    ]
    policy_mismatch_months = [
        month for month in required_months
        if month in row_by_month and row_by_month[month].get("profit_policy_valid") is False
    ]
    missing_profit_months = [
        month for month in required_months
        if month in row_by_month and row_by_month[month].get("formal_profit_cny") is None
    ]
    non_positive_months = [
        month for month in required_months
        if month in row_by_month
        and row_by_month[month].get("formal_profit_cny") is not None
        and money(row_by_month[month].get("formal_profit_cny")) <= 0
    ]
    qualifying_months = [
        month for month in required_months
        if month in row_by_month
        and row_by_month[month].get("close_status") == "locked"
        and row_by_month[month].get("profit_policy_valid") is not False
        and row_by_month[month].get("formal_profit_cny") is not None
        and money(row_by_month[month].get("formal_profit_cny")) > 0
    ]
    ready = len(qualifying_months) == len(required_months)
    average_profit = (
        round(sum(money(row_by_month[month]["formal_profit_cny"]) for month in required_months) / len(required_months), 2)
        if ready else None
    )
    if ready:
        explanation = f"{', '.join(required_months)} 均已关账且各月正式经营利润为正。"
    else:
        blockers = []
        if missing_months:
            blockers.append(f"缺少月份：{', '.join(missing_months)}")
        if unlocked_months:
            blockers.append(f"未关账：{', '.join(unlocked_months)}")
        if policy_mismatch_months:
            blockers.append(f"需按新利润口径重新关账：{', '.join(policy_mismatch_months)}")
        if missing_profit_months:
            blockers.append(f"利润不可核算：{', '.join(missing_profit_months)}")
        if non_positive_months:
            blockers.append(f"利润未为正：{', '.join(non_positive_months)}")
        explanation = "；".join(blockers) or "最近三个已完成自然月尚未形成完整的正利润证据。"
    return {
        "required_months": required_months,
        "qualifying_months": qualifying_months,
        "qualifying_month_count": len(qualifying_months),
        "missing_months": missing_months,
        "unlocked_months": unlocked_months,
        "policy_mismatch_months": policy_mismatch_months,
        "missing_profit_months": missing_profit_months,
        "non_positive_months": non_positive_months,
        "average_profit_cny": average_profit,
        "is_stable": ready,
        "ready": ready,
        "explanation": explanation,
    }


def _current_recommendation(
    *,
    cash_period: Optional[dict[str, Any]],
    cash_target: float,
    three_month_average_profit: Optional[float],
    active_managed: int,
    os_paid: int,
    leading_os_name: str,
    risk_ratio: float,
    health_total: int,
    profit_sample_months: int,
    profit_stability_ready: bool,
    os_evidence_explanation: Optional[str],
    os_evidence_sufficient: bool,
    capacity_near_or_over: int,
    capacity_overdue_rate: float,
) -> dict[str, Any]:
    if not cash_period:
        return {
            "key": "establish_cash_baseline",
            "level": "critical",
            "title": "先确认公司真实可用现金",
            "why": "系统还没有经过确认的账户余额和受限资金，当前无法可靠判断能否招聘或追加研发投入。",
            "action": "录入各银行、支付平台和现金账户余额，再加入客户投流款、待退、待付工资、分润和税务预留。",
        }
    snapshot_date = cash_period.get("snapshot_date")
    if snapshot_date and (date.today() - snapshot_date).days > 35:
        return {
            "key": "refresh_cash_snapshot",
            "level": "critical",
            "title": "先更新已经过期的现金快照",
            "why": f"最近一次已确认余额停留在 {cash_period['year_month']}，已经不能可靠代表公司当前可用现金。",
            "action": "完成本月账户余额与受限资金核对并锁定，再判断招聘、研发或市场投入。",
        }
    free_cash = cash_period["totals"]["free_cash_cny"]
    if free_cash < cash_target:
        return {
            "key": "reach_cash_safety_line",
            "level": "critical",
            "title": "当前唯一重点：补足现金安全线",
            "why": f"当前可用现金约 ¥{free_cash:,.0f}，低于 ¥{cash_target:,.0f} 的安全目标。",
            "action": "暂停非必要扩编和双项目同时商业化，优先提高代运营回款、留存和月度净现金。",
        }
    if (
        three_month_average_profit is None
        or three_month_average_profit <= 0
        or profit_sample_months < 3
        or not profit_stability_ready
        or health_total == 0
        or active_managed == 0
        or risk_ratio >= 0.2
    ):
        return {
            "key": "stabilize_managed_service",
            "level": "warning",
            "title": "现金已过线，先稳定代运营基本盘",
            "why": "最近利润或客户健康尚未达到连续稳定标准，贸然扩大 OS 投入会增加现金波动。",
            "action": "连续 3 个月保持正利润，并把高风险客户占比降到 20% 以下后再进入 OS 付费验证。",
        }
    if os_paid < 3:
        evidence_note = "" if os_evidence_sufficient else f" 数据口径说明：{os_evidence_explanation}"
        return {
            "key": "validate_one_os",
            "level": "growth",
            "title": "只选择一个 OS 做付费验证",
            "why": f"代运营基本盘有 {active_managed} 个活跃项目；当前领先的{leading_os_name}只有 {os_paid} 个实收关联明确的不同客户。{evidence_note}",
            "action": "在餐饮 OS 与美业 OS 中只选一个，先取得 3 个真实付费客户及连续使用证据。",
        }
    if os_paid < 10:
        return {
            "key": "prove_os_repeatability",
            "level": "growth",
            "title": f"验证{leading_os_name}是否可以重复销售",
            "why": f"{leading_os_name}已有 {os_paid} 个实收关联明确的不同客户，可以开始验证获客成本、交付成本和留存是否可复制。",
            "action": "达到 10 个持续付费客户且不挤压代运营交付，再讨论专职销售或研发扩编。",
        }
    if capacity_near_or_over > 0 and capacity_overdue_rate >= 0.15:
        return {
            "key": "start_capacity_observation",
            "level": "warning",
            "title": "开始 4 周产能观察",
            "why": f"{leading_os_name}已有 {os_paid} 个实收客户；当前单次快照显示 {capacity_near_or_over} 位负责人达到产能预警线、任务逾期率 {capacity_overdue_rate:.0%}，但系统没有持久化的连续周证据。",
            "action": "从本周起每周固定记录人均项目量、逾期率和单位利润；取得完整 4 周证据后再评估流程调整或扩编，当前不形成招聘结论。",
        }
    return {
        "key": "scale_without_premature_hiring",
        "level": "growth",
        "title": "产品已过验证，先复制增长但暂不扩编",
        "why": f"{leading_os_name}已有 {os_paid} 个实收客户；当前快照未同时显示产能和逾期风险。",
        "action": "继续复用获客与交付流程；如单次快照触线，先开始 4 周固定观察，再根据持久证据评估是否扩编。",
    }


async def build_company_roadmap_overview(
    db: AsyncSession,
    *,
    selected_month: Optional[str] = None,
) -> dict[str, Any]:
    setting_row = (
        await db.execute(select(CompanyStrategySettings).where(CompanyStrategySettings.settings_key == "company"))
    ).scalar_one_or_none()
    settings = settings_payload(setting_row)

    accounts = (
        await db.execute(select(CashAccount).order_by(CashAccount.sort_order, CashAccount.id))
    ).scalars().all()
    periods = (
        await db.execute(select(CashPeriod).order_by(CashPeriod.year_month.desc()).limit(24))
    ).scalars().all()
    selected = None
    if selected_month:
        selected = next((row for row in periods if row.year_month == selected_month), None)
    elif periods:
        selected = periods[0]
    period = await cash_period_payload(db, selected) if selected else None
    # Drafts stay available for editing, but only a locked snapshot may drive
    # the owner's cash runway and investment recommendations.
    authoritative_row = next((row for row in periods if row.status == "locked"), None)
    authoritative_period = await cash_period_payload(db, authoritative_row) if authoritative_row else None
    suggested_rate = period["usd_cny_rate"] if period else settings["default_usd_cny_rate"]
    suggestions = await build_restriction_suggestions(db, suggested_rate)

    today = date.today()
    growth = await build_growth_dashboard(
        db,
        start_date=settings["target_start_date"],
        end_date=today,
    )
    profit_rows = growth["formal_monthly_profit"]["rows"]
    ready_profit_rows = [row for row in profit_rows if row.get("formal_profit_cny") is not None]
    completed_profit_rows = [
        row for row in ready_profit_rows
        if row["year_month"] < today.strftime("%Y-%m")
    ]
    completed_month_rows = [row for row in profit_rows if row["year_month"] < today.strftime("%Y-%m")]
    has_profit_data = any(
        row.get("close_status") == "locked"
        or abs(money(row.get("recognized_revenue_cny_equivalent"))) > 0.005
        or abs(money(row.get("total_cost_cny_equivalent"))) > 0.005
        for row in completed_month_rows
    )
    cumulative_profit = round(sum(money(row["formal_profit_cny"]) for row in completed_profit_rows), 2)
    profit_stability = _profit_stability_evidence(profit_rows, today)
    average_profit = profit_stability["average_profit_cny"]

    project_rows = (
        await db.execute(
            select(CustomerEngagement, BusinessLine)
            .join(BusinessLine, BusinessLine.id == CustomerEngagement.business_line_id)
            .where(CustomerEngagement.status.in_(ACTIVE_PROJECT_STATUSES))
        )
    ).all()
    active_managed = sum(1 for project, line in project_rows if line.code == "managed_service")
    active_restaurant_os = sum(1 for project, line in project_rows if line.code == "restaurant_os")
    active_beauty_os = sum(1 for project, line in project_rows if line.code == "beauty_os")
    os_payment_evidence = growth.get("os_paid_customer_evidence") or {
        "by_business_line": {},
        "data_sufficient": False,
        "explanation": "没有可用于核验 OS 实收关联的数据，阶段门槛保守按 0 计算。",
    }
    paid_restaurant_os = int((os_payment_evidence.get("by_business_line") or {}).get("restaurant_os") or 0)
    paid_beauty_os = int((os_payment_evidence.get("by_business_line") or {}).get("beauty_os") or 0)
    paid_os = max(paid_restaurant_os, paid_beauty_os)
    leading_os_code = "restaurant_os" if paid_restaurant_os >= paid_beauty_os else "beauty_os"
    leading_os_name = "餐饮 OS" if leading_os_code == "restaurant_os" else "美业 OS"

    capacity = growth["team_capacity"]
    capacity_summary = capacity.get("summary") or {}
    capacity_recommendations = capacity.get("recommendations") or []
    hiring_signal = next(
        (row for row in capacity_recommendations if row.get("level") in {"observe", "process", "stable"}),
        {"level": "stable", "title": "运营产能暂时可控", "message": "暂无扩编依据。"},
    )
    active_employees = (
        await db.execute(select(Employees).where(Employees.status.in_(["active", "probation"])))
    ).scalars().all()

    health = growth["customer_health"]
    health_total = len(health.get("items") or [])
    health_summary = health.get("summary") or {}
    high_risk = int(health_summary.get("risk", 0)) + int(health_summary.get("critical", 0))
    risk_ratio = round(high_risk / health_total, 4) if health_total else 0.0
    recommendation = _current_recommendation(
        cash_period=authoritative_period,
        cash_target=settings["cash_safety_target_cny"],
        three_month_average_profit=average_profit,
        active_managed=active_managed,
        os_paid=paid_os,
        leading_os_name=leading_os_name,
        risk_ratio=risk_ratio,
        health_total=health_total,
        profit_sample_months=int(profit_stability["qualifying_month_count"]),
        profit_stability_ready=bool(profit_stability["ready"]),
        os_evidence_explanation=os_payment_evidence.get("explanation"),
        os_evidence_sufficient=bool(os_payment_evidence.get("data_sufficient")),
        capacity_near_or_over=int(capacity_summary.get("near_or_over_capacity") or 0),
        capacity_overdue_rate=float(capacity_summary.get("overdue_rate") or 0),
    )
    decision = (
        await db.execute(
            select(StrategyRecommendationDecision).where(
                StrategyRecommendationDecision.recommendation_key == recommendation["key"]
            )
        )
    ).scalar_one_or_none()
    decision_task = await db.get(Tasks, decision.task_id) if decision and decision.task_id else None
    recommendation["decision"] = _recommendation_decision_payload(decision, decision_task)

    free_cash = authoritative_period["totals"]["free_cash_cny"] if authoritative_period else None
    cash_snapshot_age_days = (
        max((today - authoritative_period["snapshot_date"]).days, 0)
        if authoritative_period else None
    )
    runway = (
        round(free_cash / settings["monthly_fixed_expense_cny"], 1)
        if free_cash is not None and settings["monthly_fixed_expense_cny"] > 0 else None
    )
    target = settings["five_year_profit_target_cny"]
    remaining = max(target - cumulative_profit, 0)
    remaining_months = _month_count(today, settings["target_end_date"]) if today <= settings["target_end_date"] else 0
    required_monthly = round(remaining / remaining_months, 2) if remaining_months else remaining
    projection_base = average_profit or 0.0

    cash_baseline_done = authoritative_period is not None and (cash_snapshot_age_days or 0) <= 35
    cash_safety_done = cash_baseline_done and free_cash is not None and free_cash >= settings["cash_safety_target_cny"]
    agency_stability_done = (
        cash_safety_done
        and bool(profit_stability["ready"])
        and average_profit is not None
        and average_profit > 0
        and active_managed > 0
        and health_total > 0
        and risk_ratio < 0.2
    )
    os_validation_done = agency_stability_done and paid_os >= 3
    os_repeatability_done = os_validation_done and paid_os >= 10
    milestone_done = [cash_baseline_done, cash_safety_done, agency_stability_done, os_validation_done, os_repeatability_done]
    current_milestone = next((index for index, done in enumerate(milestone_done) if not done), None)
    milestone_status = lambda index: "completed" if milestone_done[index] else "current" if current_milestone == index else "pending"
    milestones = [
        {
            "key": "cash_baseline", "label": "现金底账",
            "status": milestone_status(0),
            "target": "完成最近 35 天内的已确认现金快照",
        },
        {
            "key": "cash_safety", "label": "现金安全",
            "status": milestone_status(1),
            "target": f"可用现金达到 ¥{settings['cash_safety_target_cny']:,.0f}",
        },
        {
            "key": "agency_stability", "label": "代运营稳定",
            "status": milestone_status(2),
            "target": "最近连续 3 个自然月均已关账且正利润，高风险项目低于 20%",
        },
        {
            "key": "os_validation", "label": "单一 OS 付费验证",
            "status": milestone_status(3),
            "target": "只选一个 OS，取得 3 个实收关联明确的不同客户",
        },
        {
            "key": "os_repeatability", "label": "OS 可复制增长",
            "status": milestone_status(4),
            "target": "同一 OS 达到 10 个实收关联明确的不同客户，再开始 4 周产能观察",
        },
    ]

    period_summaries = []
    for row in periods:
        item = await cash_period_payload(db, row)
        period_summaries.append({
            "year_month": item["year_month"],
            "snapshot_date": item["snapshot_date"],
            "status": item["status"],
            **item["totals"],
        })

    recorded_sources = {row.get("source_ref") for row in (period or {}).get("restrictions", []) if row.get("source_ref")}
    suggestion_total = round(sum(row["amount_cny"] for row in suggestions if row["source_ref"] not in recorded_sources), 2)
    total_target_months = _month_count(settings["target_start_date"], settings["target_end_date"])
    elapsed_target_months = min(max(
        (today.year - settings["target_start_date"].year) * 12 + today.month - settings["target_start_date"].month,
        0,
    ), total_target_months)
    expected_profit_to_date = round(target * elapsed_target_months / total_target_months, 2)
    pace_gap = round(cumulative_profit - expected_profit_to_date, 2)
    pace_tolerance = target * 0.01
    complete_profit_data = has_profit_data and len(completed_profit_rows) == len(completed_month_rows)
    return {
        "settings": settings,
        "accounts": [{
            "id": row.id,
            "name": row.name,
            "account_type": row.account_type,
            "currency": row.currency,
            "masked_identifier": row.masked_identifier,
            "is_active": bool(row.is_active),
            "sort_order": row.sort_order,
            "notes": row.notes,
        } for row in accounts],
        "cash_period": period,
        "cash_history": period_summaries,
        "restriction_categories": [{"value": key, "label": value} for key, value in RESTRICTION_LABELS.items()],
        "restriction_suggestions": [row for row in suggestions if row["source_ref"] not in recorded_sources],
        "unrecorded_suggestion_cny": suggestion_total,
        "cash_health": {
            "has_baseline": authoritative_period is not None,
            "as_of_month": authoritative_period["year_month"] if authoritative_period else None,
            "snapshot_status": authoritative_period["status"] if authoritative_period else None,
            "snapshot_age_days": cash_snapshot_age_days,
            "is_stale": cash_snapshot_age_days is not None and cash_snapshot_age_days > 35,
            "free_cash_cny": free_cash,
            "safety_target_cny": settings["cash_safety_target_cny"],
            "gap_to_safety_cny": round(max(settings["cash_safety_target_cny"] - (free_cash or 0), 0), 2) if free_cash is not None else None,
            "runway_months": runway,
            "level": "unknown" if free_cash is None else "stale" if cash_snapshot_age_days is not None and cash_snapshot_age_days > 35 else "danger" if runway < 3 else "warning" if runway < settings["cash_reserve_months"] else "safe",
            "projections": [
                {"days": days, "free_cash_cny": round((free_cash or 0) + projection_base * days / 30, 2), "based_on": "最近连续 3 个已完成、已关账且各自正利润月份的平均净利润"}
                for days in (30, 60, 90)
            ] if free_cash is not None and cash_snapshot_age_days is not None and cash_snapshot_age_days <= 35 and profit_stability["ready"] else [],
            "projection_reason": None if free_cash is not None and cash_snapshot_age_days is not None and cash_snapshot_age_days <= 35 and profit_stability["ready"] else "需要最近 35 天内的已确认现金快照，以及最近连续 3 个已关账且各自为正利润的自然月。",
        },
        "goal": {
            "target_cny": target,
            "recognized_profit_cny": cumulative_profit,
            "progress_ratio": round(cumulative_profit / target, 6) if target else 0,
            "remaining_cny": remaining,
            "remaining_months": remaining_months,
            "required_average_monthly_profit_cny": required_monthly,
            "ready_months": len(completed_profit_rows),
            "total_months": len(completed_month_rows),
            "has_profit_data": has_profit_data,
            "is_complete_data": complete_profit_data,
            "expected_profit_to_date_cny": expected_profit_to_date,
            "pace_gap_cny": pace_gap,
            "pace_status": "data_incomplete" if not complete_profit_data else "ahead" if pace_gap > pace_tolerance else "behind" if pace_gap < -pace_tolerance else "on_track",
        },
        "operating_signals": {
            "three_month_average_profit_cny": average_profit,
            "profit_sample_months": int(profit_stability["qualifying_month_count"]),
            "profit_stability": profit_stability,
            "active_managed_service_projects": active_managed,
            "active_os_projects": active_restaurant_os + active_beauty_os,
            "paid_os_projects": paid_restaurant_os + paid_beauty_os,
            "paid_restaurant_os_projects": paid_restaurant_os,
            "paid_beauty_os_projects": paid_beauty_os,
            "paid_os_customers": paid_restaurant_os + paid_beauty_os,
            "paid_restaurant_os_customers": paid_restaurant_os,
            "paid_beauty_os_customers": paid_beauty_os,
            "leading_os_paid_customers": paid_os,
            "os_payment_evidence": os_payment_evidence,
            "leading_os_code": leading_os_code,
            "leading_os_name": leading_os_name,
            "high_risk_project_count": high_risk,
            "health_project_count": health_total,
            "high_risk_ratio": risk_ratio,
            "active_employee_count": len(active_employees),
            "team_capacity": {
                "active_projects": int(capacity_summary.get("active_projects") or 0),
                "unassigned_projects": int(capacity_summary.get("unassigned_projects") or 0),
                "near_or_over_capacity": int(capacity_summary.get("near_or_over_capacity") or 0),
                "overdue_rate": float(capacity_summary.get("overdue_rate") or 0),
                "hiring_level": hiring_signal.get("level"),
                "hiring_title": hiring_signal.get("title"),
                "hiring_message": hiring_signal.get("message"),
                "history_persisted": bool(capacity_summary.get("history_persisted")),
                "history_weeks": int(capacity_summary.get("history_weeks") or 0),
                "observation_required_weeks": int(capacity_summary.get("observation_required_weeks") or 4),
                "hiring_gate_ready": bool(capacity_summary.get("hiring_gate_ready")),
            },
        },
        "milestones": milestones,
        "recommendation": recommendation,
        "definitions": {
            "free_cash": "可用现金 = 各账户余额折合人民币 - 客户投流款 - 待退客户款 - 已确认未发工资 - 待付分润 - 税务预留 - 其他已确认受限资金。",
            "profit_vs_cash": "利润回答经营是否赚钱；可用现金回答公司现在能否安全支出。两者不互相替代。",
            "data_boundary": "账户余额和受限资金需由老板或财务确认；系统建议只供核对，不会自动写入正式现金快照。",
        },
    }
