from __future__ import annotations

from collections import Counter, defaultdict
import calendar
from datetime import date, datetime, timedelta, timezone
import json
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.ad_fund_settlements import AdFundSettlement
from models.commissions import CommissionEntry
from models.customer_callbacks import Customer_callbacks
from models.company_expenses import Company_expenses
from models.customers import Customers
from models.employees import Employees
from models.expenses import Expenses
from models.finance_refunds import FinanceRefund
from models.finance_exchange_rates import MonthlyExchangeRate
from models.finance_profit_closes import MonthlyProfitClose
from models.management_decisions import BusinessLine, CustomerEngagement, ProductCatalog
from models.payments import Payments
from models.payroll import PayrollItems, PayrollSheets
from models.service_progresses import Service_progresses
from models.service_tasks import Service_tasks
from models.subscriptions import Subscriptions
from models.tasks import Tasks


ACTIVE_PROJECT_STATUSES = {"pending_setup", "trial", "active_paid", "at_risk", "paused", "pending_stop", "reactivated"}
OPEN_TASK_STATUSES = {"pending", "in_progress", "waiting_client", "internal_waiting", "delayed"}
FINAL_COMMISSION_STATUSES = {"confirmed", "payable", "paid"}
PASS_THROUGH_EXPENSE_MARKERS = {"ad", "ads", "advertising", "投流", "广告", "代充值"}
PAYROLL_EXPENSE_MARKERS = {"salary", "payroll", "工资", "薪资"}


def _money(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _day(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def _currency(value: Any) -> str:
    return str(value or "USD").upper()


def _in_period(value: Any, start_date: date, end_date: date) -> bool:
    actual = _day(value)
    return bool(actual and start_date <= actual <= end_date)


def _months_between(start: Optional[date], end: date) -> int:
    if not start:
        return 1
    return max(1, (end.year - start.year) * 12 + end.month - start.month + 1)


def _month_ranges(start_date: date, end_date: date) -> list[tuple[str, date, date]]:
    rows = []
    cursor = date(start_date.year, start_date.month, 1)
    last = date(end_date.year, end_date.month, 1)
    while cursor <= last:
        month_end = date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1])
        rows.append((cursor.strftime("%Y-%m"), max(cursor, start_date), min(month_end, end_date)))
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
    return rows


def _month_after(value: date) -> date:
    return date(value.year + (value.month == 12), 1 if value.month == 12 else value.month + 1, 1)


def _payment_recognition_amount(payment: Payments, month_start: date, month_end: date) -> tuple[float, bool]:
    """Allocate service revenue over [coverage_start, coverage_end); fall back to the receipt month."""
    service_amount = _service_amount(payment)
    coverage_start = _day(payment.coverage_start)
    coverage_end = _day(payment.coverage_end)
    if coverage_start and coverage_end and coverage_end > coverage_start:
        overlap_start = max(coverage_start, month_start)
        overlap_end = min(coverage_end, month_end + timedelta(days=1))
        overlap_days = max(0, (overlap_end - overlap_start).days)
        total_days = (coverage_end - coverage_start).days
        return round(service_amount * overlap_days / total_days, 2) if overlap_days else 0.0, True
    return (service_amount if _in_period(payment.payment_date, month_start, month_end) else 0.0), False


def _service_amount(payment: Payments) -> float:
    paid = max(_money(payment.amount_paid), 0)
    if payment.management_amount is not None:
        return min(max(_money(payment.management_amount), 0), paid)
    ads = max(_money(payment.ads_recharge_amount), 0)
    if str(payment.income_type or "").lower() == "ads_fee":
        return 0.0
    return max(paid - ads, 0)


def _is_pass_through_expense(expense: Expenses) -> bool:
    haystack = " ".join(str(value or "").lower() for value in (
        expense.expense_category, expense.expense_type, expense.notes,
    ))
    return any(marker in haystack for marker in PASS_THROUGH_EXPENSE_MARKERS)


def _is_payroll_company_expense(expense: Company_expenses) -> bool:
    haystack = " ".join(str(value or "").lower() for value in (expense.category, expense.category_name, expense.notes))
    return any(marker in haystack for marker in PAYROLL_EXPENSE_MARKERS)


def _payroll_net(item: PayrollItems) -> float:
    additions = sum(_money(getattr(item, name, 0)) for name in (
        "base_salary", "fixed_performance", "commission", "bonus", "allowance", "reimbursement",
    ))
    deductions = sum(_money(getattr(item, name, 0)) for name in (
        "absence_deduction", "performance_deduction", "salary_advance_deduction", "other_deduction",
    ))
    return round(additions - deductions, 2)


async def _base_rows(db: AsyncSession) -> dict[str, Any]:
    projects = (await db.execute(select(CustomerEngagement))).scalars().all()
    customers = (await db.execute(select(Customers))).scalars().all()
    lines = (await db.execute(select(BusinessLine))).scalars().all()
    products = (await db.execute(select(ProductCatalog))).scalars().all()
    employees = (await db.execute(select(Employees))).scalars().all()
    payments = (await db.execute(select(Payments))).scalars().all()
    refunds = (await db.execute(select(FinanceRefund).where(FinanceRefund.status == "completed"))).scalars().all()
    settlements = (await db.execute(select(AdFundSettlement).where(AdFundSettlement.status == "closed"))).scalars().all()
    expenses = (await db.execute(select(Expenses))).scalars().all()
    commissions = (await db.execute(select(CommissionEntry).where(CommissionEntry.status.in_(FINAL_COMMISSION_STATUSES)))).scalars().all()
    subscriptions = (await db.execute(select(Subscriptions))).scalars().all()
    tasks = (await db.execute(select(Tasks))).scalars().all()
    service_tasks = (await db.execute(select(Service_tasks))).scalars().all()
    progresses = (await db.execute(select(Service_progresses))).scalars().all()
    callbacks = (await db.execute(select(Customer_callbacks))).scalars().all()
    company_expenses = (await db.execute(select(Company_expenses))).scalars().all()
    exchange_rates = (await db.execute(select(MonthlyExchangeRate))).scalars().all()
    profit_closes = (await db.execute(select(MonthlyProfitClose))).scalars().all()
    payroll_sheets = (await db.execute(select(PayrollSheets))).scalars().all()
    payroll_items = (await db.execute(select(PayrollItems))).scalars().all()
    return {
        "projects": projects,
        "customers": customers,
        "customer_by_id": {int(row.id): row for row in customers},
        "line_by_id": {int(row.id): row for row in lines},
        "product_by_id": {int(row.id): row for row in products},
        "employee_by_id": {int(row.id): row for row in employees},
        "employee_by_name": {str(row.name).strip(): row for row in employees if row.name},
        "payments": payments, "refunds": refunds, "settlements": settlements, "expenses": expenses,
        "commissions": commissions, "subscriptions": subscriptions, "tasks": tasks,
        "service_tasks": service_tasks, "progresses": progresses, "callbacks": callbacks,
        "company_expenses": company_expenses, "exchange_rates": exchange_rates,
        "profit_closes": profit_closes,
        "payroll_sheets": payroll_sheets, "payroll_items": payroll_items,
    }


def _project_assignment(projects: list[CustomerEngagement]) -> tuple[dict[int, CustomerEngagement], dict[int, list[CustomerEngagement]]]:
    by_id = {int(row.id): row for row in projects}
    by_customer: dict[int, list[CustomerEngagement]] = defaultdict(list)
    for row in projects:
        by_customer[int(row.customer_id)].append(row)
    return by_id, by_customer


def _resolve_project(
    project_id: Optional[int],
    customer_id: int,
    project_by_id: dict[int, CustomerEngagement],
    projects_by_customer: dict[int, list[CustomerEngagement]],
) -> tuple[Optional[CustomerEngagement], str]:
    if project_id and int(project_id) in project_by_id:
        return project_by_id[int(project_id)], "direct"
    candidates = projects_by_customer.get(int(customer_id), [])
    if len(candidates) == 1:
        return candidates[0], "single_project_inferred"
    return None, "unallocated"


async def build_unit_economics(
    db: AsyncSession,
    *,
    start_date: date,
    end_date: date,
    base: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    base = base or await _base_rows(db)
    projects: list[CustomerEngagement] = base["projects"]
    project_by_id, projects_by_customer = _project_assignment(projects)
    components = (
        "service_revenue", "ad_spread", "service_refunds", "stripe_fee_burden",
        "customer_cost", "channel_commission",
    )
    ledgers: dict[int, dict[str, Counter]] = {
        int(row.id): {name: Counter() for name in components} for row in projects
    }
    confidence: dict[int, Counter] = {int(row.id): Counter() for row in projects}
    unallocated: dict[str, Counter] = {"customer_cost": Counter(), "ad_spread": Counter(), "service_refunds": Counter()}

    payments = base["payments"] if "payments" in base else (await db.execute(select(Payments))).scalars().all()
    payment_by_id = {int(row.id): row for row in payments}
    for payment in payments:
        if not _in_period(payment.payment_date, start_date, end_date):
            continue
        project, source = _resolve_project(payment.engagement_id, int(payment.customer_id), project_by_id, projects_by_customer)
        if not project:
            continue
        currency = _currency(payment.currency or project.currency)
        ledgers[int(project.id)]["service_revenue"][currency] += _service_amount(payment)
        ledgers[int(project.id)]["stripe_fee_burden"][currency] += max(_money(payment.stripe_fee_amount), 0)
        confidence[int(project.id)][source] += 1

    refunds = base["refunds"] if "refunds" in base else (await db.execute(select(FinanceRefund).where(FinanceRefund.status == "completed"))).scalars().all()
    for refund in refunds:
        if not _in_period(refund.refund_date, start_date, end_date):
            continue
        payment = payment_by_id.get(int(refund.payment_id))
        project, source = _resolve_project(
            payment.engagement_id if payment else None,
            int(refund.customer_id), project_by_id, projects_by_customer,
        )
        currency = _currency(refund.currency)
        if not project:
            unallocated["service_refunds"][currency] += _money(refund.refund_amount)
            continue
        paid = max(_money(payment.amount_paid) if payment else 0, 0)
        service_ratio = min(1.0, _service_amount(payment) / paid) if payment and paid else 1.0
        ledgers[int(project.id)]["service_refunds"][currency] += _money(refund.refund_amount) * service_ratio
        ledgers[int(project.id)]["stripe_fee_burden"][currency] -= max(_money(refund.stripe_fee_refunded_amount), 0)
        confidence[int(project.id)][source] += 1

    settlements = base["settlements"] if "settlements" in base else (await db.execute(select(AdFundSettlement).where(AdFundSettlement.status == "closed"))).scalars().all()
    for settlement in settlements:
        month_day = _day(f"{str(settlement.year_month)[:7]}-01")
        if not month_day or not (start_date.replace(day=1) <= month_day <= end_date.replace(day=1)):
            continue
        project, source = _resolve_project(None, int(settlement.customer_id), project_by_id, projects_by_customer)
        currency = _currency(settlement.currency)
        if not project:
            unallocated["ad_spread"][currency] += _money(settlement.recognized_spread_amount)
            continue
        ledgers[int(project.id)]["ad_spread"][currency] += _money(settlement.recognized_spread_amount)
        confidence[int(project.id)][source] += 1

    expenses = base["expenses"] if "expenses" in base else (await db.execute(select(Expenses))).scalars().all()
    for expense in expenses:
        if not _in_period(expense.expense_date or expense.payment_date, start_date, end_date) or _is_pass_through_expense(expense):
            continue
        currency = _currency(expense.currency)
        project, source = _resolve_project(None, int(expense.customer_id or 0), project_by_id, projects_by_customer)
        if not project:
            unallocated["customer_cost"][currency] += _money(expense.amount)
            continue
        ledgers[int(project.id)]["customer_cost"][currency] += _money(expense.amount)
        confidence[int(project.id)][source] += 1

    commissions = base["commissions"] if "commissions" in base else (await db.execute(select(CommissionEntry).where(CommissionEntry.status.in_(FINAL_COMMISSION_STATUSES)))).scalars().all()
    for entry in commissions:
        if not _in_period(entry.occurred_at, start_date, end_date):
            continue
        project, source = _resolve_project(entry.engagement_id, int(entry.customer_id), project_by_id, projects_by_customer)
        if not project:
            continue
        ledgers[int(project.id)]["channel_commission"][_currency(entry.currency)] += _money(entry.commission_amount)
        confidence[int(project.id)][source] += 1

    rows: list[dict[str, Any]] = []
    totals: dict[str, Counter] = {name: Counter() for name in (*components, "contribution_profit")}
    for project in projects:
        customer = base["customer_by_id"].get(int(project.customer_id))
        line = base["line_by_id"].get(int(project.business_line_id))
        product = base["product_by_id"].get(int(project.product_id))
        currencies = set().union(*(set(ledgers[int(project.id)][name]) for name in components)) or {_currency(project.currency)}
        metrics = []
        for currency in sorted(currencies):
            values = {name: round(ledgers[int(project.id)][name][currency], 2) for name in components}
            contribution = round(
                values["service_revenue"] + values["ad_spread"] - values["service_refunds"]
                - values["stripe_fee_burden"] - values["customer_cost"] - values["channel_commission"], 2,
            )
            recognized = values["service_revenue"] + values["ad_spread"]
            values.update({
                "currency": currency,
                "contribution_profit": contribution,
                "contribution_margin": round(contribution / recognized, 4) if recognized else None,
                "monthly_contribution": round(contribution / _months_between(_day(project.paid_started_at), end_date), 2),
            })
            metrics.append(values)
            for name in components:
                totals[name][currency] += values[name]
            totals["contribution_profit"][currency] += contribution
        confidence_level = "direct" if confidence[int(project.id)]["direct"] else (
            "single_project_inferred" if confidence[int(project.id)]["single_project_inferred"] else "no_finance_data"
        )
        rows.append({
            "project_id": int(project.id), "customer_id": int(project.customer_id),
            "customer_name": customer.business_name if customer else f"客户 #{project.customer_id}",
            "customer_code": customer.customer_code if customer else None,
            "business_line": line.name if line else "未分类", "business_line_code": line.code if line else "unknown",
            "product_name": project.package_name or (product.name if product else "未命名项目"),
            "status": project.status, "confidence": confidence_level, "metrics": metrics,
        })
    rows.sort(key=lambda row: sum(item["contribution_profit"] for item in row["metrics"]), reverse=True)
    line_rollup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        for metric in row["metrics"]:
            key = (row["business_line_code"], metric["currency"])
            bucket = line_rollup.setdefault(key, {
                "business_line_code": row["business_line_code"], "business_line": row["business_line"],
                "currency": metric["currency"], "project_ids": set(), "recognized_revenue": 0.0,
                "contribution_profit": 0.0,
            })
            bucket["project_ids"].add(row["project_id"])
            bucket["recognized_revenue"] += metric["service_revenue"] + metric["ad_spread"]
            bucket["contribution_profit"] += metric["contribution_profit"]
    business_lines = []
    for bucket in line_rollup.values():
        project_count = len(bucket.pop("project_ids"))
        revenue = round(bucket["recognized_revenue"], 2)
        contribution = round(bucket["contribution_profit"], 2)
        bucket.update({
            "project_count": project_count, "recognized_revenue": revenue, "contribution_profit": contribution,
            "average_project_contribution": round(contribution / project_count, 2) if project_count else 0,
            "contribution_margin": round(contribution / revenue, 4) if revenue else None,
        })
        business_lines.append(bucket)
    business_lines.sort(key=lambda row: (row["business_line"], row["currency"]))
    return {
        "definition": "可核算贡献利润 = 服务收入 + 已关账投流差价 - 服务退款 - Stripe净手续费 - 可归属客户成本 - 已确认渠道分润",
        "guardrails": ["投流代充值不计营业收入", "工资独立核算，不进入本模型", "USD/CNY 分币种展示，不使用临时汇率", "多项目客户未绑定的成本保留为待分摊"],
        "totals": {currency: {name: round(counter[currency], 2) for name, counter in totals.items()} for currency in sorted(set().union(*(set(counter) for counter in totals.values())))},
        "unallocated": {name: dict(counter) for name, counter in unallocated.items()},
        "projects": rows,
        "business_lines": business_lines,
        "coverage": {
            "direct_projects": sum(row["confidence"] == "direct" for row in rows),
            "inferred_projects": sum(row["confidence"] == "single_project_inferred" for row in rows),
            "projects_without_finance_data": sum(row["confidence"] == "no_finance_data" for row in rows),
        },
    }


async def build_customer_health(
    db: AsyncSession,
    *,
    today: Optional[date] = None,
    base: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    today = today or datetime.now(timezone.utc).date()
    base = base or await _base_rows(db)
    projects: list[CustomerEngagement] = base["projects"]
    subscriptions = base["subscriptions"]
    payments = base["payments"]
    refunds = base["refunds"]
    tasks = base["tasks"]
    service_tasks = base["service_tasks"]
    progresses = base["progresses"]
    callbacks = base["callbacks"]

    by_customer = lambda rows: defaultdict(list, {
        key: [row for row in rows if int(getattr(row, "customer_id", 0) or 0) == key]
        for key in {int(getattr(row, "customer_id", 0) or 0) for row in rows}
    })
    sub_by_customer, pay_by_customer, refund_by_customer = map(by_customer, (subscriptions, payments, refunds))
    task_by_customer, service_by_customer, progress_by_customer, callback_by_customer = map(by_customer, (tasks, service_tasks, progresses, callbacks))
    items = []
    for project in projects:
        customer_id = int(project.customer_id)
        score, reasons = 100, []
        def deduct(points: int, code: str, message: str) -> None:
            nonlocal score
            score -= points
            reasons.append({"code": code, "points": points, "message": message})

        if project.status in {"at_risk", "pending_stop"}:
            deduct(35, "project_status_risk", "项目已被标记为有风险或待停止")
        elif project.status in {"paused", "pending_setup"}:
            deduct(15, "project_status_watch", "项目暂停或尚未完成开通")
        outstanding = sum(max(_money(row.outstanding_amount), 0) for row in pay_by_customer[customer_id])
        if outstanding > 0.01:
            deduct(25, "outstanding_receivable", f"仍有应收款未收齐（{outstanding:,.2f}，币种需在财务明细核对）")
        related_subscriptions = [row for row in sub_by_customer[customer_id] if not row.engagement_id or int(row.engagement_id) == int(project.id)]
        expired = [row for row in related_subscriptions if row.status not in {"stopped", "cancelled"} and _day(row.end_date) and _day(row.end_date) < today]
        soon = [row for row in related_subscriptions if row.status not in {"stopped", "cancelled"} and _day(row.end_date) and 0 <= (_day(row.end_date) - today).days <= 14]
        if expired:
            deduct(30, "subscription_expired", f"有 {len(expired)} 个套餐已到期但未闭环")
        elif soon:
            deduct(10, "subscription_due_soon", f"有 {len(soon)} 个套餐将在 14 天内到期")
        recent_refunds = [row for row in refund_by_customer[customer_id] if _day(row.refund_date) and 0 <= (today - _day(row.refund_date)).days <= 90]
        if recent_refunds:
            deduct(15, "recent_refund", f"近 90 天发生 {len(recent_refunds)} 笔退款")
        overdue_tasks = [row for row in task_by_customer[customer_id] if row.status in OPEN_TASK_STATUSES and _day(row.due_date) and _day(row.due_date) < today]
        if overdue_tasks:
            deduct(min(20, 5 + len(overdue_tasks) * 3), "overdue_tasks", f"有 {len(overdue_tasks)} 个协作任务逾期")
        overdue_delivery = [row for row in service_by_customer[customer_id] if row.status not in {"completed", "cancelled"} and _day(row.due_date) and _day(row.due_date) < today]
        if overdue_delivery:
            deduct(min(20, 5 + len(overdue_delivery) * 3), "overdue_delivery", f"有 {len(overdue_delivery)} 个交付任务逾期")
        unresolved = [row for row in progress_by_customer[customer_id] if row.issue_status and not row.issue_resolved]
        if unresolved:
            deduct(15, "unresolved_service_issue", f"有 {len(unresolved)} 个服务问题未解决")
        overdue_callbacks = [row for row in callback_by_customer[customer_id] if row.status == "pending" and _day(row.callback_date) and _day(row.callback_date) < today]
        if overdue_callbacks:
            deduct(10, "overdue_callback", f"有 {len(overdue_callbacks)} 个客户回访逾期")
        score = max(0, score)
        level = "critical" if score < 40 else "risk" if score < 60 else "watch" if score < 80 else "healthy"
        customer = base["customer_by_id"].get(customer_id)
        line = base["line_by_id"].get(int(project.business_line_id))
        employee = base["employee_by_id"].get(int(project.owner_employee_id)) if project.owner_employee_id else None
        action = "继续正常服务并按节奏回访" if level == "healthy" else (
            "48 小时内由负责人核对收款、续费和服务问题" if level in {"risk", "critical"} else "本周完成到期、任务和客户反馈复查"
        )
        items.append({
            "project_id": int(project.id), "customer_id": customer_id,
            "customer_name": customer.business_name if customer else f"客户 #{customer_id}",
            "business_line": line.name if line else "未分类", "product_name": project.package_name,
            "project_status": project.status, "owner_employee_id": project.owner_employee_id,
            "owner_name": employee.name if employee else None, "score": score, "level": level,
            "reasons": sorted(reasons, key=lambda row: row["points"], reverse=True), "recommended_action": action,
        })
    items.sort(key=lambda row: (row["score"], row["customer_name"]))
    counts = Counter(row["level"] for row in items)
    return {"summary": dict(counts), "items": items, "auto_stop_enabled": False, "updated_through": today.isoformat()}


def _converted(usd_value: float, cny_value: float, rate: Optional[float]) -> Optional[float]:
    if abs(usd_value) > 0.005 and rate is None:
        return None
    return round(usd_value * (rate or 0) + cny_value, 2)


def _profit_rollup(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    operating_ready = all(row["formal_profit_cny"] is not None for row in rows)
    cash_ready = all(row["cash_profit_cny"] is not None for row in rows)
    revenue_ready = all(row["recognized_revenue_cny_equivalent"] is not None for row in rows)
    cash_revenue_ready = all(row["cash_revenue_cny_equivalent"] is not None for row in rows)
    operating_profit = round(sum(row["formal_profit_cny"] or 0 for row in rows), 2) if operating_ready else None
    cash_profit = round(sum(row["cash_profit_cny"] or 0 for row in rows), 2) if cash_ready else None
    revenue = round(sum(row["recognized_revenue_cny_equivalent"] or 0 for row in rows), 2) if revenue_ready else None
    cash_revenue = round(sum(row["cash_revenue_cny_equivalent"] or 0 for row in rows), 2) if cash_revenue_ready else None
    cost = round(sum(row["total_cost_cny_equivalent"] or 0 for row in rows), 2) if operating_ready else None
    return {
        "label": label,
        "start_month": rows[0]["year_month"],
        "end_month": rows[-1]["year_month"],
        "month_count": len(rows),
        "ready_month_count": sum(row["formal_profit_cny"] is not None for row in rows),
        "locked_month_count": sum(row.get("close_status") == "locked" for row in rows),
        "recognized_revenue_cny": revenue,
        "cash_revenue_cny": cash_revenue,
        "total_cost_cny": cost,
        "operating_profit_cny": operating_profit,
        "cash_profit_cny": cash_profit,
        "operating_margin": round(operating_profit / revenue, 4) if operating_profit is not None and revenue else None,
        "status": "ready" if operating_ready else "missing_rate",
    }


async def build_formal_monthly_profit(
    db: AsyncSession,
    *,
    start_date: date,
    end_date: date,
    base: dict[str, Any],
) -> dict[str, Any]:
    """Build company-wide RMB operating profit without requiring project attribution."""
    rates = [row for row in base["exchange_rates"] if row.base_currency == "USD" and row.quote_currency == "CNY"]
    rate_by_month = {row.year_month: row for row in rates}
    closes_by_month = {row.year_month: row for row in base.get("profit_closes", [])}
    payroll_sheet_by_id = {int(row.id): row for row in base["payroll_sheets"]}
    payment_by_id = {int(row.id): row for row in base["payments"]}
    rows: list[dict[str, Any]] = []
    fallback_payment_ids: set[int] = set()
    covered_payment_ids: set[int] = set()

    for month, month_start, month_end in _month_ranges(start_date, end_date):
        recognized_service, cash_service = Counter(), Counter()
        ad_spread, service_refunds, stripe_fees = Counter(), Counter(), Counter()
        customer_cost, channel_commission = Counter(), Counter()
        expense_by_currency, manual_payroll_by_currency = Counter(), Counter()

        for payment in base["payments"]:
            currency = _currency(payment.currency)
            cash_amount = _service_amount(payment) if _in_period(payment.payment_date, month_start, month_end) else 0.0
            cash_service[currency] += cash_amount
            recognized_amount, used_coverage = _payment_recognition_amount(payment, month_start, month_end)
            recognized_service[currency] += recognized_amount
            if used_coverage:
                if recognized_amount:
                    covered_payment_ids.add(int(payment.id))
            elif cash_amount:
                fallback_payment_ids.add(int(payment.id))
            if cash_amount:
                stripe_fees[currency] += max(_money(payment.stripe_fee_amount), 0)

        for refund in base["refunds"]:
            if not _in_period(refund.refund_date, month_start, month_end):
                continue
            payment = payment_by_id.get(int(refund.payment_id))
            paid = max(_money(payment.amount_paid) if payment else 0, 0)
            service_ratio = min(1.0, _service_amount(payment) / paid) if payment and paid else 1.0
            currency = _currency(refund.currency)
            service_refunds[currency] += _money(refund.refund_amount) * service_ratio
            stripe_fees[currency] -= max(_money(refund.stripe_fee_refunded_amount), 0)

        for settlement in base["settlements"]:
            if str(settlement.year_month or "")[:7] == month:
                ad_spread[_currency(settlement.currency)] += _money(settlement.recognized_spread_amount)

        for expense in base["expenses"]:
            if _in_period(expense.expense_date or expense.payment_date, month_start, month_end) and not _is_pass_through_expense(expense):
                customer_cost[_currency(expense.currency)] += _money(expense.amount)

        for commission in base["commissions"]:
            if _in_period(commission.occurred_at, month_start, month_end):
                channel_commission[_currency(commission.currency)] += _money(commission.commission_amount)

        for expense in base["company_expenses"]:
            expense_month = str(expense.expense_month or "")[:7]
            if not expense_month:
                expense_day = _day(expense.expense_date or expense.created_at)
                expense_month = expense_day.strftime("%Y-%m") if expense_day else ""
            if expense_month == month:
                target = manual_payroll_by_currency if _is_payroll_company_expense(expense) else expense_by_currency
                target[_currency(expense.currency or "CNY")] += _money(expense.amount)

        paid_payroll_cny = round(sum(
            _payroll_net(item)
            for item in base["payroll_items"]
            if item.payment_status == "paid"
            and payroll_sheet_by_id.get(int(item.sheet_id))
            and payroll_sheet_by_id[int(item.sheet_id)].month == month
            and _currency(payroll_sheet_by_id[int(item.sheet_id)].currency) == "CNY"
        ), 2)
        payroll_cost_cny = paid_payroll_cny if paid_payroll_cny else round(manual_payroll_by_currency["CNY"], 2)
        payroll_source = "paid_payroll" if paid_payroll_cny else "company_expense" if payroll_cost_cny else "none"
        expense_by_currency["USD"] += manual_payroll_by_currency["USD"]

        rate = rate_by_month.get(month)
        locked_rate = _money(rate.average_rate) if rate and rate.status == "locked" else None
        project_contribution = Counter()
        cash_project_contribution = Counter()
        for currency in {"USD", "CNY"}:
            common_cost = service_refunds[currency] + stripe_fees[currency] + customer_cost[currency] + channel_commission[currency]
            project_contribution[currency] = recognized_service[currency] + ad_spread[currency] - common_cost
            cash_project_contribution[currency] = cash_service[currency] + ad_spread[currency] - common_cost

        operating_usd_net = round(project_contribution["USD"] - expense_by_currency["USD"], 2)
        operating_cny_net = round(project_contribution["CNY"] - expense_by_currency["CNY"] - payroll_cost_cny, 2)
        cash_usd_net = round(cash_project_contribution["USD"] - expense_by_currency["USD"], 2)
        cash_cny_net = round(cash_project_contribution["CNY"] - expense_by_currency["CNY"] - payroll_cost_cny, 2)
        formal_profit = _converted(operating_usd_net, operating_cny_net, locked_rate)
        cash_profit = _converted(cash_usd_net, cash_cny_net, locked_rate)
        recognized_revenue = _converted(
            recognized_service["USD"] + ad_spread["USD"],
            recognized_service["CNY"] + ad_spread["CNY"],
            locked_rate,
        )
        cash_revenue = _converted(
            cash_service["USD"] + ad_spread["USD"],
            cash_service["CNY"] + ad_spread["CNY"],
            locked_rate,
        )
        total_cost = _converted(
            service_refunds["USD"] + stripe_fees["USD"] + customer_cost["USD"] + channel_commission["USD"] + expense_by_currency["USD"],
            service_refunds["CNY"] + stripe_fees["CNY"] + customer_cost["CNY"] + channel_commission["CNY"] + expense_by_currency["CNY"] + payroll_cost_cny,
            locked_rate,
        )
        needs_rate = any(abs(value) > 0.005 for value in (
            operating_usd_net, cash_usd_net, recognized_service["USD"], cash_service["USD"], ad_spread["USD"],
        ))
        live_row = {
            "year_month": month,
            "recognized_service_revenue_usd": round(recognized_service["USD"], 2),
            "recognized_service_revenue_cny": round(recognized_service["CNY"], 2),
            "cash_service_revenue_usd": round(cash_service["USD"], 2),
            "cash_service_revenue_cny": round(cash_service["CNY"], 2),
            "ad_spread_usd": round(ad_spread["USD"], 2),
            "ad_spread_cny": round(ad_spread["CNY"], 2),
            "refunds_usd": round(service_refunds["USD"], 2),
            "refunds_cny": round(service_refunds["CNY"], 2),
            "stripe_fee_usd": round(stripe_fees["USD"], 2),
            "stripe_fee_cny": round(stripe_fees["CNY"], 2),
            "customer_cost_usd": round(customer_cost["USD"], 2),
            "customer_cost_cny": round(customer_cost["CNY"], 2),
            "channel_commission_usd": round(channel_commission["USD"], 2),
            "channel_commission_cny": round(channel_commission["CNY"], 2),
            "project_contribution_usd": round(project_contribution["USD"], 2),
            "project_contribution_cny": round(project_contribution["CNY"], 2),
            "cash_project_contribution_usd": round(cash_project_contribution["USD"], 2),
            "cash_project_contribution_cny": round(cash_project_contribution["CNY"], 2),
            "company_expense_usd": round(expense_by_currency["USD"], 2),
            "company_expense_cny": round(expense_by_currency["CNY"], 2),
            "payroll_cost_cny": payroll_cost_cny,
            "payroll_source": payroll_source,
            "exchange_rate": locked_rate,
            "exchange_rate_source": rate.source if rate else None,
            "exchange_rate_status": rate.status if rate else "missing",
            "recognized_revenue_cny_equivalent": recognized_revenue,
            "cash_revenue_cny_equivalent": cash_revenue,
            "total_cost_cny_equivalent": total_cost,
            "formal_profit_cny": formal_profit,
            "cash_profit_cny": cash_profit,
            "status": "ready" if locked_rate is not None else "cny_only" if not needs_rate else "missing_rate",
            "close_status": "open",
        }
        close = closes_by_month.get(month)
        if close and close.status == "locked":
            try:
                snapshot = json.loads(close.snapshot_json)
                if isinstance(snapshot, dict) and snapshot.get("year_month") == month:
                    live_row = snapshot
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
            live_row.update({
                "close_status": "locked",
                "closed_by": close.locked_by,
                "closed_at": close.locked_at,
            })
        rows.append(live_row)

    quarter_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    year_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        year, month_number = row["year_month"].split("-")
        quarter_groups[f"{year}-Q{(int(month_number) - 1) // 3 + 1}"].append(row)
        year_groups[year].append(row)

    return {
        "definition": "人民币经营净利润 =（按服务期确认的 USD 服务收入 + 已关账投流差价 - 退款 - Stripe 手续费 - 客户成本 - 已确认分润 - USD 公司支出）× 当月锁定平均汇率 + CNY 项目贡献 - CNY 运营支出 - 已发放工资",
        "cash_definition": "人民币现金口径经营结果使用实际收款月份；投流代充值本金仍不计收入。",
        "accounting_note": "公司总利润纳入全部有效收支，不依赖项目归属；项目归属仅用于客户和业务线下钻。季付、年付按 coverage_start/coverage_end 服务期逐日分摊，缺服务期时暂按收款月并提示核对。工资只读已发放工资表，避免与财务手工工资重复扣除。",
        "rows": rows,
        "summary": _profit_rollup(rows, f"{start_date.isoformat()} 至 {end_date.isoformat()}"),
        "quarterly": [_profit_rollup(group, label) for label, group in sorted(quarter_groups.items())],
        "yearly": [_profit_rollup(group, label) for label, group in sorted(year_groups.items())],
        "missing_rate_months": [row["year_month"] for row in rows if row["status"] == "missing_rate"],
        "data_quality": {
            "payments_with_service_period": len(covered_payment_ids),
            "payments_using_receipt_month": len(fallback_payment_ids),
            "unlinked_payment_count": sum(
                1 for payment in base["payments"]
                if _in_period(payment.payment_date, start_date, end_date) and not payment.engagement_id and _service_amount(payment) > 0
            ),
            "locked_month_count": sum(row.get("close_status") == "locked" for row in rows),
        },
    }


async def health_risk_anomalies(db: AsyncSession, *, today: Optional[date] = None) -> list[dict[str, Any]]:
    health = await build_customer_health(db, today=today)
    anomalies = []
    for row in health["items"]:
        if row["level"] not in {"risk", "critical"}:
            continue
        reason_text = "；".join(item["message"] for item in row["reasons"][:3])
        anomalies.append({
            "customer_id": row["customer_id"], "customer_name": row["customer_name"],
            "project_id": row["project_id"], "assignee_id": row["owner_employee_id"], "assignee_name": row["owner_name"],
            "code": "customer_health_risk", "category": "risk",
            "severity": "high" if row["level"] == "critical" else "warning",
            "message": f"客户健康度 {row['score']} 分：{reason_text}",
            "suggested_action": row["recommended_action"],
        })
    return anomalies


async def build_team_capacity(
    db: AsyncSession,
    *,
    project_capacity_target: int,
    capacity_warning_ratio: float,
    base: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    base = base or await _base_rows(db)
    projects = [row for row in base["projects"] if row.status in ACTIVE_PROJECT_STATUSES]
    tasks = base["tasks"]
    service_tasks = base["service_tasks"]
    active_employees = [row for row in base["employee_by_id"].values() if row.status in {"active", "probation"}]
    today = datetime.now(timezone.utc).date()
    rows = []
    for employee in active_employees:
        owned = [row for row in projects if row.owner_employee_id == employee.id]
        open_tasks = [row for row in tasks if row.status in OPEN_TASK_STATUSES and (row.assignee_id == employee.id or row.assignee_name == employee.name)]
        overdue_tasks = [row for row in open_tasks if _day(row.due_date) and _day(row.due_date) < today]
        delivery = [row for row in service_tasks if row.status not in {"completed", "cancelled"} and row.assignee_name == employee.name]
        overdue_delivery = [row for row in delivery if _day(row.due_date) and _day(row.due_date) < today]
        utilization = round(len(owned) / max(1, project_capacity_target), 4)
        rows.append({
            "employee_id": int(employee.id), "employee_name": employee.name, "role": employee.role,
            "active_projects": len(owned), "open_tasks": len(open_tasks), "overdue_tasks": len(overdue_tasks),
            "open_delivery_tasks": len(delivery), "overdue_delivery_tasks": len(overdue_delivery),
            "capacity_target": project_capacity_target, "utilization": utilization,
            "capacity_level": "overloaded" if utilization >= 1 else "near_limit" if utilization >= capacity_warning_ratio else "available",
        })
    operations = [row for row in rows if row["active_projects"] or row["open_delivery_tasks"]]
    overloaded = [row for row in operations if row["utilization"] >= capacity_warning_ratio]
    overdue_total = sum(row["overdue_tasks"] + row["overdue_delivery_tasks"] for row in operations)
    open_total = sum(row["open_tasks"] + row["open_delivery_tasks"] for row in operations)
    overdue_rate = round(overdue_total / open_total, 4) if open_total else 0
    from services.sales_lead_cycle import automation_overview as sales_automation_overview
    sales = await sales_automation_overview(db)
    recommendations = []
    if overloaded and overdue_rate >= 0.15:
        recommendations.append({"level": "hire", "title": "准备补充运营产能", "message": f"{len(overloaded)} 位负责人达到预警线，任务逾期率 {overdue_rate:.0%}。先确认连续 4 周后再招聘。"})
    elif overdue_rate >= 0.15:
        recommendations.append({"level": "process", "title": "先修流程，不急于招聘", "message": f"当前任务逾期率 {overdue_rate:.0%}，但项目负载未普遍达到预警线，优先处理分配、截止时间和阻塞。"})
    else:
        recommendations.append({"level": "stable", "title": "运营产能暂时可控", "message": "项目负载与逾期未同时触发招聘线，保持每周复盘即可。"})
    pool_days = float(sales.get("estimated_pool_days") or 0)
    if pool_days < 10:
        recommendations.append({"level": "hold", "title": "暂不增加销售人数", "message": f"可复用线索约只够 {pool_days:.1f} 天，先补充和回收线索池，否则新增销售会争抢同一批数据。"})
    else:
        recommendations.append({"level": "observe", "title": "销售招聘需结合转化率", "message": f"线索池约可支持 {pool_days:.1f} 天；连续观察人均有效沟通、商机与成交后再决定扩编。"})
    return {
        "settings": {"project_capacity_target": project_capacity_target, "capacity_warning_ratio": capacity_warning_ratio},
        "summary": {"active_projects": len(projects), "unassigned_projects": sum(not row.owner_employee_id for row in projects), "overdue_rate": overdue_rate, "near_or_over_capacity": len(overloaded)},
        "employees": sorted(operations, key=lambda row: (row["utilization"], row["overdue_tasks"] + row["overdue_delivery_tasks"]), reverse=True),
        "sales_lead_capacity": sales, "recommendations": recommendations,
    }


async def build_growth_dashboard(
    db: AsyncSession,
    *,
    start_date: date,
    end_date: date,
    project_capacity_target: int = 12,
    capacity_warning_ratio: float = 0.85,
) -> dict[str, Any]:
    base = await _base_rows(db)
    return {
        "period": {"start_date": start_date, "end_date": end_date},
        "unit_economics": await build_unit_economics(db, start_date=start_date, end_date=end_date, base=base),
        "formal_monthly_profit": await build_formal_monthly_profit(db, start_date=start_date, end_date=end_date, base=base),
        "customer_health": await build_customer_health(db, today=end_date, base=base),
        "team_capacity": await build_team_capacity(db, project_capacity_target=project_capacity_target, capacity_warning_ratio=capacity_warning_ratio, base=base),
    }
