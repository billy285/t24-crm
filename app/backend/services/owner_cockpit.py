from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.automation import DataQualityIssue
from models.company_expenses import Company_expenses
from models.customer_callbacks import Customer_callbacks
from models.customers import Customers
from models.management_decisions import BusinessLine, CustomerEngagement
from models.service_progresses import Service_progresses
from models.service_tasks import Service_tasks
from models.tasks import Tasks
from services.automation_monitor import OPEN_TASK_STATUSES, automation_overview


ACTIVE_PROJECT_STATUSES = {"pending_setup", "trial", "active_paid", "at_risk", "paused", "pending_stop", "reactivated"}
FINISHED_TASK_STATUSES = {"completed", "cancelled"}


def _date_value(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return datetime.strptime(raw[:10], "%Y-%m-%d").date()
            except ValueError:
                return None
    return None


def _money(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


async def _monthly_finance(db: AsyncSession, month: str) -> dict[str, Any]:
    # Reuse the same audited finance aggregation that powers the monthly detail
    # and exports. This keeps ad-fund top-ups outside operating revenue and
    # preserves separate USD/CNY reporting.
    from routers.reports_export import (
        _aggregate_monthly,
        _apply_deductions,
        _get_default_deduction_rate,
        _get_monthly_deduction_map,
    )

    year, month_number = (int(part) for part in month.split("-"))
    start = date(year, month_number, 1)
    if month_number == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month_number + 1, 1)
    end = date.fromordinal(next_month.toordinal() - 1)
    raw, months = await _aggregate_monthly(db, start.isoformat(), end.isoformat())
    default_rate = await _get_default_deduction_rate(db)
    rate_map = await _get_monthly_deduction_map(db, month, month)
    rows = _apply_deductions(raw, months, rate_map, default_rate, None)
    by_currency = {
        str(row["currency_or_base"]): {
            "gross_receipts": _money(row["gross_receipts"]),
            "refund_amount": _money(row["refund_amount"]),
            "net_receipts": _money(row["net_receipts"]),
            "service_revenue": _money(row["service_revenue"]),
            "ads_client_funds": _money(row["ads_client_funds"]),
            "recognized_ad_spread": _money(row["recognized_ad_spread"]),
            "deduction_amount": _money(row["deduction_amount"]),
            "stripe_platform_fee": _money(row["stripe_platform_fee"]),
            "channel_commission": _money(row.get("channel_commission")),
            "cost": _money(row["cost"]),
            "profit": _money(row["profit"]),
        }
        for row in rows
        if row["month"] == month
    }
    company_expenses = (await db.execute(select(Company_expenses))).scalars().all()
    company_cost_cny = round(sum(
        _money(row.amount)
        for row in company_expenses
        if str(row.expense_month or "")[:7] == month and str(row.currency or "CNY").upper() == "CNY"
    ), 2)
    return {
        "month": month,
        "USD": by_currency.get("USD", {
            "gross_receipts": 0.0,
            "refund_amount": 0.0,
            "net_receipts": 0.0,
            "service_revenue": 0.0,
            "ads_client_funds": 0.0,
            "recognized_ad_spread": 0.0,
            "deduction_amount": 0.0,
            "stripe_platform_fee": 0.0,
            "channel_commission": 0.0,
            "cost": 0.0,
            "profit": 0.0,
        }),
        "company_cost_cny": company_cost_cny,
        "currency_policy": "USD 与 CNY 独立统计；客户投流充值不计经营收入，只有已关账差价进入利润；已确认渠道佣金单独计入成本。",
    }


async def build_owner_cockpit(
    db: AsyncSession,
    *,
    reference_time: Optional[datetime] = None,
) -> dict[str, Any]:
    now = reference_time or datetime.now(timezone.utc)
    today = now.date()
    month = f"{today.year:04d}-{today.month:02d}"

    finance = await _monthly_finance(db, month)
    quality = await automation_overview(db)
    tasks = (await db.execute(select(Tasks))).scalars().all()
    projects = (await db.execute(
        select(CustomerEngagement, BusinessLine)
        .join(BusinessLine, BusinessLine.id == CustomerEngagement.business_line_id)
    )).all()
    callbacks = (await db.execute(select(Customer_callbacks))).scalars().all()
    service_progresses = (await db.execute(select(Service_progresses))).scalars().all()
    service_tasks = (await db.execute(select(Service_tasks))).scalars().all()
    customers = (await db.execute(select(Customers.id, Customers.status))).all()
    customer_status = {int(customer_id): str(status or "").lower() for customer_id, status in customers}
    active_service_progresses = [
        row for row in service_progresses
        if customer_status.get(int(row.customer_id)) != "lost"
        and str(row.service_stage or "").lower() not in {"ended", "paused"}
    ]
    active_service_ids = {int(row.id) for row in active_service_progresses}
    open_issues = (await db.execute(
        select(DataQualityIssue).where(DataQualityIssue.status != "resolved")
    )).scalars().all()

    open_tasks = [row for row in tasks if row.status in OPEN_TASK_STATUSES]
    overdue_tasks = [row for row in open_tasks if (_date_value(row.due_date) or today) < today]
    system_tasks = [row for row in open_tasks if row.source_type == "system"]
    completed_this_month = [
        row for row in tasks
        if row.status == "completed" and str(row.completed_at or "")[:7] == month
    ]
    active_projects = [(project, line) for project, line in projects if project.status in ACTIVE_PROJECT_STATUSES]
    at_risk_projects = [
        (project, line) for project, line in projects
        if project.status in {"at_risk", "pending_stop"}
    ]
    stopped_this_month = [
        (project, line) for project, line in projects
        if project.status in {"stopped", "completed"} and str(project.stopped_at or "")[:7] == month
    ]
    line_counts = Counter(line.code for project, line in active_projects)
    line_names = {line.code: line.name for _, line in projects}

    overdue_callbacks = [
        row for row in callbacks
        if row.status == "pending" and (_date_value(row.callback_date) or today) < today
    ]
    overdue_service_tasks = [
        row for row in service_tasks
        if row.status not in FINISHED_TASK_STATUSES
        and (not row.service_progress_id or int(row.service_progress_id) in active_service_ids)
        and customer_status.get(int(row.customer_id)) != "lost"
        and (_date_value(row.due_date) or today) < today
    ]
    unresolved_service_issues = [
        row for row in active_service_progresses
        if row.issue_status and not row.issue_resolved
    ]
    issue_categories = Counter(row.category for row in open_issues)

    decisions: list[dict[str, Any]] = []

    def add_decision(key: str, level: str, title: str, count: int, description: str, link: str) -> None:
        if count <= 0:
            return
        decisions.append({
            "key": key,
            "level": level,
            "title": title,
            "count": count,
            "description": description,
            "link": link,
        })

    high_issues = sum(row.severity == "high" for row in open_issues)
    add_decision("high_quality", "critical", "高风险问题待闭环", high_issues, "已由每日扫描识别，优先核对数据或客户状态。", "/management-decisions?section=quality")
    add_decision("overdue_system_tasks", "critical", "系统任务已逾期", sum(row.source_type == "system" for row in overdue_tasks), "自动任务超过处理日期，需要负责人补充处理结果。", "/tasks?source=system&schedule=overdue")
    add_decision("overdue_tasks", "high", "团队任务已逾期", len(overdue_tasks), "已有任务超过计划完成日期，请确认负责人和新的完成时间。", "/tasks?schedule=overdue")
    add_decision("project_risk", "high", "合作项目存在流失风险", len(at_risk_projects), "项目只提醒，不会自动停止；需要人工确认下一步。", "/customer-lifecycle?status=at_risk")
    add_decision("finance", "high", "财务事项待处理", issue_categories.get("finance", 0), "包括欠款、收入拆分或投流月结问题。", "/finance")
    add_decision("delivery", "high", "交付事项待处理", issue_categories.get("delivery", 0), "包括逾期服务任务或未解决服务问题。", "/service-board")
    if not issue_categories.get("delivery", 0):
        add_decision("delivery_live", "high", "交付进度存在逾期或阻塞", len(overdue_service_tasks) + len(unresolved_service_issues), "页面实时数据已发现逾期任务或未解决问题，下一次扫描会建立闭环任务。", "/service-board")
    add_decision("customer_success", "medium", "回访与客户跟进逾期", issue_categories.get("customer_success", 0), "请按承诺时间完成回访并记录结果。", "/callbacks?status=pending&schedule=overdue")
    if not issue_categories.get("customer_success", 0):
        add_decision("customer_success_live", "medium", "客户回访已经逾期", len(overdue_callbacks), "请按承诺时间完成回访并记录结果。", "/callbacks?status=pending&schedule=overdue")
    add_decision("data_quality", "medium", "经营数据需要补齐", issue_categories.get("data_quality", 0) + issue_categories.get("integrity", 0), "缺失字段会降低生命周期和经营决策可信度。", "/management-decisions?section=quality")
    decisions.sort(key=lambda row: ({"critical": 0, "high": 1, "medium": 2}.get(row["level"], 3), -row["count"]))

    return {
        "as_of": now,
        "period": {"month": month, "today": today},
        "finance": finance,
        "customers": {
            "active_projects": len(active_projects),
            "at_risk_projects": len(at_risk_projects),
            "stopped_this_month": len(stopped_this_month),
            "business_lines": [
                {"code": code, "name": line_names.get(code, code), "active_projects": count}
                for code, count in sorted(line_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
        },
        "execution": {
            "open_tasks": len(open_tasks),
            "overdue_tasks": len(overdue_tasks),
            "system_tasks": len(system_tasks),
            "completed_this_month": len(completed_this_month),
        },
        "delivery": {
            "active_service_records": len(active_service_progresses),
            "overdue_service_tasks": len(overdue_service_tasks),
            "unresolved_service_issues": len(unresolved_service_issues),
            "overdue_callbacks": len(overdue_callbacks),
        },
        "quality": quality["summary"],
        "automation": {
            "last_run": quality["last_run"],
            "schedule": quality["schedule"],
        },
        "decisions": decisions[:8],
        "decision_state": "attention" if decisions else "healthy",
    }
