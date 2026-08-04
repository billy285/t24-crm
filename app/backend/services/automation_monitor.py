from __future__ import annotations

import asyncio
import logging
import os
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import db_manager
from models.automation import AutomationScanRun, DataQualityIssue
from models.ad_fund_settlements import AdFundSettlement
from models.customer_callbacks import Customer_callbacks
from models.customers import Customers
from models.employees import Employees
from models.follow_ups import Follow_ups
from models.management_decisions import CustomerEngagement
from models.payments import Payments
from models.service_progresses import Service_progresses
from models.service_tasks import Service_tasks
from models.subscriptions import Subscriptions
from models.tasks import Tasks
from services.management_decision_workflow import build_classification_review_queue


logger = logging.getLogger(__name__)
BEIJING = ZoneInfo("Asia/Shanghai")
OPEN_TASK_STATUSES = {"pending", "in_progress", "waiting_client", "internal_waiting", "delayed"}
AUTO_RESOLUTION_PREFIX = "系统复查："


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def scan_hour() -> int:
    raw = (os.environ.get("AUTOMATION_SCAN_HOUR") or "8").strip()
    try:
        return min(23, max(0, int(raw)))
    except ValueError:
        return 8


def next_scheduled_scan(now: Optional[datetime] = None) -> datetime:
    local_now = (now or utcnow()).astimezone(BEIJING)
    target = datetime.combine(local_now.date(), time(hour=scan_hour()), tzinfo=BEIJING)
    if target <= local_now:
        target += timedelta(days=1)
    return target.astimezone(timezone.utc)


def issue_key(row: dict[str, Any]) -> str:
    suffix = f":scope:{row['scope_key']}" if row.get("scope_key") else ""
    return f"{row['code']}:customer:{int(row['customer_id'])}:project:{int(row.get('project_id') or 0)}{suffix}"


def _issue_category(row: dict[str, Any]) -> str:
    if row.get("category"):
        return str(row["category"])
    if row.get("severity") == "high":
        return "integrity"
    return "data_quality"


def _issue_title(issue: DataQualityIssue) -> str:
    titles = {
        "automatic_project_risk_reminder": "核对客户项目风险",
        "customer_project_status_mismatch": "核对客户与项目状态",
        "active_project_missing_paid_start": "补齐首次有效收款日期",
        "active_project_missing_owner": "分配项目负责人",
        "active_project_missing_billing_config": "补齐收费信息",
        "historical_classification_pending": "确认历史客户项目分类",
        "finance_receivable_open": "跟进客户欠款",
        "finance_payment_missing_date": "补齐收款日期",
        "finance_income_split_mismatch": "核对收入拆分",
        "finance_ad_fund_unsettled": "完成投流月结",
        "subscription_missing_next_payment": "补齐订阅扣款日期",
        "customer_follow_up_overdue": "完成逾期客户跟进",
        "customer_callback_overdue": "完成逾期客户回访",
        "delivery_task_overdue": "完成逾期交付任务",
        "delivery_issue_unresolved": "处理客户服务问题",
    }
    return titles.get(issue.code, "处理经营数据异常")


def _task_worthy(issue: DataQualityIssue) -> bool:
    return issue.category == "risk" or issue.severity == "high"


def _task_notes(issue: DataQualityIssue) -> str:
    lines = [
        "系统每日自动扫描生成；只提醒和跟进，不会自动停止客户或项目。",
        f"发现问题：{issue.message}",
    ]
    if issue.suggested_action:
        lines.append(f"建议处理：{issue.suggested_action}")
    lines.append(f"问题编号：DQ-{issue.id}")
    return "\n".join(lines)


async def _ensure_task(
    db: AsyncSession,
    issue: DataQualityIssue,
    *,
    owner_by_project: Optional[dict[int, tuple[Optional[int], Optional[str]]]] = None,
    fallback_owner: tuple[Optional[int], Optional[str]] = (None, None),
    force: bool = False,
) -> tuple[Tasks, bool, bool]:
    existing = (await db.execute(
        select(Tasks).where(Tasks.automation_issue_id == issue.id)
    )).scalar_one_or_none()
    if existing and existing.status not in {"completed", "cancelled"}:
        existing.title = f"【系统提醒】{issue.customer_name} · {_issue_title(issue)}"
        existing.priority = "high" if issue.severity == "high" else "medium"
        existing.source_type = "system"
        existing.updated_at = utcnow()
        return existing, False, True
    if not force and not _task_worthy(issue):
        if existing:
            return existing, False, False
        raise ValueError("该问题保留在数据质量中心，不需要自动生成任务")

    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    if issue.project_id and owner_by_project:
        owner_id, owner_name = owner_by_project.get(int(issue.project_id), (None, None))
    if not owner_id and not owner_name:
        owner_id, owner_name = fallback_owner
    due_days = 1 if issue.severity == "high" else 2
    now = utcnow()

    if existing:
        history = str(existing.notes or "").strip()
        reopen_note = f"系统再次发现（{now.astimezone(BEIJING).strftime('%Y-%m-%d %H:%M')}）：{issue.message}"
        existing.title = f"【系统提醒】{issue.customer_name} · {_issue_title(issue)}"
        existing.priority = "high" if issue.severity == "high" else "medium"
        existing.status = "pending"
        existing.due_date = now + timedelta(days=due_days)
        existing.assignee_id = owner_id or existing.assignee_id
        existing.assignee_name = owner_name or existing.assignee_name
        existing.source_type = "system"
        existing.completion_result = None
        existing.completed_at = None
        existing.notes = "\n\n".join(value for value in (history, reopen_note) if value)
        existing.updated_at = now
        return existing, False, True

    task = Tasks(
        title=f"【系统提醒】{issue.customer_name} · {_issue_title(issue)}",
        customer_id=issue.customer_id,
        customer_name=issue.customer_name,
        assignee_id=owner_id,
        assignee_name=owner_name,
        task_type="other",
        priority="high" if issue.severity == "high" else "medium",
        status="pending",
        due_date=now + timedelta(days=due_days),
        notes=_task_notes(issue),
        source_type="system",
        automation_issue_id=issue.id,
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    await db.flush()
    return task, True, False


async def create_task_for_issue(db: AsyncSession, issue_id: int) -> Tasks:
    issue = (await db.execute(
        select(DataQualityIssue).where(DataQualityIssue.id == issue_id)
    )).scalar_one_or_none()
    if not issue:
        raise ValueError("数据质量问题不存在")
    if issue.status == "resolved":
        raise ValueError("该问题已经解决，无需创建任务")
    owner_by_project = await _owner_map(db, [issue.project_id] if issue.project_id else [])
    task, _, _ = await _ensure_task(db, issue, owner_by_project=owner_by_project, force=True)
    await db.commit()
    await db.refresh(task)
    return task


async def _owner_map(
    db: AsyncSession,
    project_ids: list[Optional[int]],
) -> dict[int, tuple[Optional[int], Optional[str]]]:
    wanted = {int(value) for value in project_ids if value}
    if not wanted:
        return {}
    projects = (await db.execute(
        select(CustomerEngagement.id, CustomerEngagement.owner_employee_id)
        .where(CustomerEngagement.id.in_(wanted))
    )).all()
    employee_ids = {int(owner_id) for _, owner_id in projects if owner_id}
    employee_names = dict((await db.execute(
        select(Employees.id, Employees.name).where(Employees.id.in_(employee_ids))
    )).all()) if employee_ids else {}
    return {
        int(project_id): (int(owner_id), employee_names.get(int(owner_id))) if owner_id else (None, None)
        for project_id, owner_id in projects
    }


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _aware(value).date() if _aware(value) else None
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


def _ads_recharge(payment: Payments) -> float:
    if payment.ads_recharge_amount is not None:
        return max(_money(payment.ads_recharge_amount), 0)
    return max(_money(payment.amount_paid), 0) if payment.income_type == "ads_fee" else 0


def _income_split_mismatch(payment: Payments) -> bool:
    management = max(_money(payment.management_amount), 0)
    ads = _ads_recharge(payment)
    paid = max(_money(payment.amount_paid), 0)
    if management + ads > paid + 0.01:
        return True
    return payment.income_type == "management_ads_mixed" and (management <= 0 or ads <= 0)


async def _business_anomalies(db: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    """Cross-functional daily checks. Every item remains advisory until a human closes its task."""
    today = now.astimezone(BEIJING).date()
    current_month = f"{today.year:04d}-{today.month:02d}"
    customers = (await db.execute(select(Customers))).scalars().all()
    customer_by_id = {int(row.id): row for row in customers}
    anomalies: list[dict[str, Any]] = []

    def customer_payload(customer_id: int) -> Optional[dict[str, Any]]:
        customer = customer_by_id.get(int(customer_id))
        if not customer:
            return None
        return {
            "customer_id": int(customer.id),
            "customer_name": customer.business_name,
            "assignee_id": customer.sales_employee_id,
            "assignee_name": customer.sales_person,
        }

    payments = (await db.execute(select(Payments))).scalars().all()
    receivables: dict[int, list[Payments]] = {}
    ad_months: dict[tuple[int, str, str], list[Payments]] = {}
    for payment in payments:
        base = customer_payload(payment.customer_id)
        if not base:
            continue
        if payment.payment_date is None:
            anomalies.append({
                **base,
                "code": "finance_payment_missing_date",
                "category": "finance",
                "severity": "high",
                "scope_key": f"payment-{payment.id}",
                "message": f"收款记录 #{payment.id} 缺少收款日期，无法进入正确月份",
                "suggested_action": "核对银行或 Stripe 记录并补齐实际收款日期",
            })
        if _income_split_mismatch(payment):
            anomalies.append({
                **base,
                "code": "finance_income_split_mismatch",
                "category": "finance",
                "severity": "high",
                "scope_key": f"payment-{payment.id}",
                "message": f"收款记录 #{payment.id} 的管理费与投流充值拆分不一致",
                "suggested_action": "核对实收金额，重新填写管理费与投流充值金额",
            })
        if _money(payment.outstanding_amount) > 0.01:
            receivables.setdefault(int(payment.customer_id), []).append(payment)
        payment_day = _as_date(payment.payment_date)
        ads_amount = _ads_recharge(payment)
        if payment_day and ads_amount > 0:
            month = f"{payment_day.year:04d}-{payment_day.month:02d}"
            currency = str(payment.currency or "USD").upper()
            ad_months.setdefault((int(payment.customer_id), month, currency), []).append(payment)

    for customer_id, rows in receivables.items():
        base = customer_payload(customer_id)
        if not base:
            continue
        amounts = Counter()
        for row in rows:
            amounts[str(row.currency or "USD").upper()] += _money(row.outstanding_amount)
        amount_text = " / ".join(f"{currency} {amounts[currency]:,.2f}" for currency in sorted(amounts))
        anomalies.append({
            **base,
            "code": "finance_receivable_open",
            "category": "finance",
            "severity": "high",
            "message": f"存在 {len(rows)} 笔未收齐款项，合计 {amount_text}",
            "suggested_action": "核对约定付款时间并记录催收结果",
        })

    settlements = (await db.execute(select(AdFundSettlement))).scalars().all()
    closed_settlements = {
        (int(row.customer_id), str(row.year_month)[:7], str(row.currency or "USD").upper())
        for row in settlements if row.status == "closed"
    }
    for (customer_id, month, currency), rows in ad_months.items():
        if month >= current_month or (customer_id, month, currency) in closed_settlements:
            continue
        base = customer_payload(customer_id)
        if not base:
            continue
        anomalies.append({
            **base,
            "code": "finance_ad_fund_unsettled",
            "category": "finance",
            "severity": "high",
            "scope_key": f"{month}-{currency}",
            "message": f"{month} 有 {currency} 投流充值，但尚未完成月结关账",
            "suggested_action": "录入广告实支、客户退款、确认差价与结余后关账",
        })

    subscriptions = (await db.execute(select(Subscriptions))).scalars().all()
    for subscription in subscriptions:
        if not subscription.auto_renew or subscription.next_payment_date or subscription.status in {"stopped", "cancelled"}:
            continue
        base = customer_payload(subscription.customer_id)
        if not base:
            continue
        anomalies.append({
            **base,
            "code": "subscription_missing_next_payment",
            "category": "data_quality",
            "severity": "warning",
            "scope_key": f"subscription-{subscription.id}",
            "message": f"自动续费套餐“{subscription.package_name}”缺少下次付款日期",
            "suggested_action": "在套餐续费管理中补齐实际计划扣款日",
        })

    follow_ups = (await db.execute(select(Follow_ups))).scalars().all()
    latest_follow_up: dict[int, Follow_ups] = {}
    for row in follow_ups:
        current = latest_follow_up.get(int(row.customer_id))
        if current is None or str(row.created_at or "") > str(current.created_at or ""):
            latest_follow_up[int(row.customer_id)] = row
    for customer_id, row in latest_follow_up.items():
        due = _as_date(row.next_follow_date)
        if not due or due >= today or row.stage in {"closed", "lost"}:
            continue
        base = customer_payload(customer_id)
        if not base:
            continue
        overdue_days = (today - due).days
        anomalies.append({
            **base,
            "assignee_id": row.employee_id or base.get("assignee_id"),
            "assignee_name": row.employee_name or base.get("assignee_name"),
            "code": "customer_follow_up_overdue",
            "category": "customer_success",
            "severity": "high" if overdue_days >= 3 else "warning",
            "message": f"客户跟进已逾期 {overdue_days} 天",
            "suggested_action": "联系客户并记录本次结果与下一次明确日期",
        })

    callbacks = (await db.execute(select(Customer_callbacks))).scalars().all()
    overdue_callbacks: dict[int, list[Customer_callbacks]] = {}
    for row in callbacks:
        due = _as_date(row.callback_date)
        if row.status == "pending" and due and due < today:
            overdue_callbacks.setdefault(int(row.customer_id), []).append(row)
    for customer_id, rows in overdue_callbacks.items():
        base = customer_payload(customer_id)
        if not base:
            continue
        oldest = min(_as_date(row.callback_date) or today for row in rows)
        overdue_days = (today - oldest).days
        owner = sorted(rows, key=lambda row: _as_date(row.callback_date) or today)[0]
        anomalies.append({
            **base,
            "assignee_id": owner.employee_id or base.get("assignee_id"),
            "assignee_name": owner.employee_name or base.get("assignee_name"),
            "code": "customer_callback_overdue",
            "category": "customer_success",
            "severity": "high" if overdue_days >= 3 else "warning",
            "message": f"存在 {len(rows)} 条逾期回访，最早已逾期 {overdue_days} 天",
            "suggested_action": "完成回访并填写回访结果；如需延期请更新下次日期",
        })

    employees = (await db.execute(select(Employees))).scalars().all()
    employee_by_name = {str(row.name).strip(): row for row in employees if row.name}
    service_tasks = (await db.execute(select(Service_tasks))).scalars().all()
    overdue_service: dict[int, list[Service_tasks]] = {}
    for row in service_tasks:
        due = _as_date(row.due_date)
        if row.status not in {"completed", "cancelled"} and due and due < today:
            overdue_service.setdefault(int(row.customer_id), []).append(row)
    for customer_id, rows in overdue_service.items():
        base = customer_payload(customer_id)
        if not base:
            continue
        oldest = min(_as_date(row.due_date) or today for row in rows)
        overdue_days = (today - oldest).days
        owner_name = next((row.assignee_name for row in rows if row.assignee_name), None)
        owner = employee_by_name.get(str(owner_name).strip()) if owner_name else None
        anomalies.append({
            **base,
            "assignee_id": owner.id if owner else base.get("assignee_id"),
            "assignee_name": owner_name or base.get("assignee_name"),
            "code": "delivery_task_overdue",
            "category": "delivery",
            "severity": "high",
            "message": f"存在 {len(rows)} 个交付任务逾期，最早已逾期 {overdue_days} 天",
            "suggested_action": "确认阻塞原因、负责人和新的完成日期",
        })

    service_progresses = (await db.execute(select(Service_progresses))).scalars().all()
    for row in service_progresses:
        if not row.issue_status or row.issue_resolved:
            continue
        base = customer_payload(row.customer_id)
        if not base:
            continue
        owner = employee_by_name.get(str(row.issue_owner or row.ops_person or "").strip())
        anomalies.append({
            **base,
            "assignee_id": owner.id if owner else base.get("assignee_id"),
            "assignee_name": row.issue_owner or row.ops_person or base.get("assignee_name"),
            "code": "delivery_issue_unresolved",
            "category": "delivery",
            "severity": "high",
            "scope_key": f"service-{row.id}",
            "message": row.issue_description or f"{row.service_type or '客户服务'}存在未解决问题",
            "suggested_action": "补充处理进度，解决后在服务进度看板标记完成",
        })

    return anomalies


async def run_automation_scan(
    db: AsyncSession,
    *,
    trigger: str = "manual",
    run_key: Optional[str] = None,
    start_date: date = date(2026, 1, 1),
) -> dict[str, Any]:
    now = utcnow()
    local_date = now.astimezone(BEIJING).date()
    key = run_key or f"{trigger}:{local_date.isoformat()}:{uuid4().hex}"
    existing_run = (await db.execute(
        select(AutomationScanRun).where(AutomationScanRun.run_key == key)
    )).scalar_one_or_none()
    if existing_run:
        return _scan_payload(existing_run, skipped=True)

    scan_run = AutomationScanRun(
        run_key=key,
        scan_date=local_date,
        trigger=trigger,
        status="running",
        started_at=now,
    )
    db.add(scan_run)
    await db.flush()

    try:
        review = await build_classification_review_queue(db, start_date)
        anomalies = [*review.get("anomalies", []), *(await _business_anomalies(db, now))]
        keys = {issue_key(row) for row in anomalies}
        existing_issues = (await db.execute(select(DataQualityIssue))).scalars().all()
        issue_by_key = {row.issue_key: row for row in existing_issues}
        owner_by_project = await _owner_map(db, [row.get("project_id") for row in anomalies])
        opened_count = 0
        resolved_count = 0
        task_created_count = 0
        task_updated_count = 0
        cooldown_days = max(1, int(os.environ.get("AUTOMATION_RESOLVED_COOLDOWN_DAYS") or "30"))

        for anomaly in anomalies:
            key_value = issue_key(anomaly)
            issue = issue_by_key.get(key_value)
            if not issue:
                issue = DataQualityIssue(
                    issue_key=key_value,
                    code=str(anomaly["code"]),
                    category=_issue_category(anomaly),
                    severity=str(anomaly.get("severity") or "warning"),
                    status="open",
                    customer_id=int(anomaly["customer_id"]),
                    project_id=int(anomaly["project_id"]) if anomaly.get("project_id") else None,
                    customer_name=str(anomaly.get("customer_name") or f"客户 #{anomaly['customer_id']}"),
                    message=str(anomaly.get("message") or "需要核对经营数据"),
                    suggested_action=anomaly.get("suggested_action"),
                    occurrence_count=1,
                    first_detected_at=now,
                    last_detected_at=now,
                )
                db.add(issue)
                await db.flush()
                issue_by_key[key_value] = issue
                opened_count += 1
            else:
                issue.code = str(anomaly["code"])
                issue.category = _issue_category(anomaly)
                issue.severity = str(anomaly.get("severity") or "warning")
                issue.customer_name = str(anomaly.get("customer_name") or issue.customer_name)
                issue.message = str(anomaly.get("message") or issue.message)
                issue.suggested_action = anomaly.get("suggested_action")
                issue.occurrence_count = int(issue.occurrence_count or 0) + 1
                issue.last_detected_at = now
                resolved_at = _aware(issue.resolved_at)
                manually_handled = bool(issue.resolution_note and not issue.resolution_note.startswith(AUTO_RESOLUTION_PREFIX))
                in_cooldown = bool(resolved_at and (now - resolved_at).days < cooldown_days)
                if issue.status == "resolved" and (not manually_handled or not in_cooldown):
                    issue.status = "open"
                    issue.resolved_at = None
                    issue.resolution_note = None
                    opened_count += 1

            if issue.status in {"open", "in_progress"} and _task_worthy(issue):
                _, created, updated = await _ensure_task(
                    db,
                    issue,
                    owner_by_project=owner_by_project,
                    fallback_owner=(anomaly.get("assignee_id"), anomaly.get("assignee_name")),
                )
                task_created_count += int(created)
                task_updated_count += int(updated)

        for issue in existing_issues:
            if issue.issue_key in keys or issue.status == "resolved":
                continue
            issue.status = "resolved"
            issue.resolved_at = now
            issue.resolution_note = f"{AUTO_RESOLUTION_PREFIX}相关风险或数据缺口已消失"
            linked_task = (await db.execute(
                select(Tasks).where(Tasks.automation_issue_id == issue.id)
            )).scalar_one_or_none()
            if linked_task and linked_task.status in OPEN_TASK_STATUSES:
                result = "系统复查确认：相关风险或数据缺口已消失"
                linked_task.status = "completed"
                linked_task.completion_result = result
                linked_task.completed_at = now
                linked_task.updated_at = now
                linked_task.notes = "\n\n".join(value for value in (linked_task.notes, result) if value)
                task_updated_count += 1
            resolved_count += 1

        scan_run.detected_count = len(anomalies)
        scan_run.opened_count = opened_count
        scan_run.resolved_count = resolved_count
        scan_run.task_created_count = task_created_count
        scan_run.task_updated_count = task_updated_count
        scan_run.status = "completed"
        scan_run.completed_at = utcnow()
        await db.commit()
        await db.refresh(scan_run)
        return _scan_payload(scan_run)
    except Exception as exc:
        await db.rollback()
        logger.exception("Automation scan failed trigger=%s key=%s", trigger, key)
        failed = AutomationScanRun(
            run_key=f"failed:{key}:{uuid4().hex[:8]}",
            scan_date=local_date,
            trigger=trigger,
            status="failed",
            error_message=str(exc)[:1000],
            started_at=now,
            completed_at=utcnow(),
        )
        db.add(failed)
        await db.commit()
        raise


def _scan_payload(row: AutomationScanRun, *, skipped: bool = False) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_key": row.run_key,
        "scan_date": row.scan_date,
        "trigger": row.trigger,
        "status": row.status,
        "detected_count": row.detected_count,
        "opened_count": row.opened_count,
        "resolved_count": row.resolved_count,
        "task_created_count": row.task_created_count,
        "task_updated_count": row.task_updated_count,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "skipped": skipped,
    }


async def automation_overview(db: AsyncSession) -> dict[str, Any]:
    issues = (await db.execute(
        select(DataQualityIssue).order_by(
            DataQualityIssue.status.asc(),
            DataQualityIssue.severity.asc(),
            DataQualityIssue.last_detected_at.desc(),
        )
    )).scalars().all()
    tasks = (await db.execute(
        select(Tasks).where(Tasks.automation_issue_id.is_not(None))
    )).scalars().all()
    task_by_issue = {int(row.automation_issue_id): row for row in tasks if row.automation_issue_id}
    last_run = (await db.execute(
        select(AutomationScanRun).order_by(AutomationScanRun.started_at.desc(), AutomationScanRun.id.desc()).limit(1)
    )).scalar_one_or_none()
    status_counts = Counter(row.status for row in issues)
    category_counts = Counter(row.category for row in issues if row.status != "resolved")
    severity_counts = Counter(row.severity for row in issues if row.status != "resolved")
    return {
        "summary": {
            "total": len(issues),
            "open": status_counts.get("open", 0),
            "in_progress": status_counts.get("in_progress", 0),
            "resolved": status_counts.get("resolved", 0),
            "category_counts": dict(category_counts),
            "severity_counts": dict(severity_counts),
            "open_task_count": sum(1 for row in tasks if row.status in OPEN_TASK_STATUSES),
        },
        "items": [
            {
                "id": issue.id,
                "issue_key": issue.issue_key,
                "code": issue.code,
                "category": issue.category,
                "severity": issue.severity,
                "status": issue.status,
                "customer_id": issue.customer_id,
                "project_id": issue.project_id,
                "customer_name": issue.customer_name,
                "message": issue.message,
                "suggested_action": issue.suggested_action,
                "occurrence_count": issue.occurrence_count,
                "first_detected_at": issue.first_detected_at,
                "last_detected_at": issue.last_detected_at,
                "resolved_at": issue.resolved_at,
                "resolution_note": issue.resolution_note,
                "task": ({
                    "id": task_by_issue[issue.id].id,
                    "status": task_by_issue[issue.id].status,
                    "assignee_name": task_by_issue[issue.id].assignee_name,
                    "due_date": task_by_issue[issue.id].due_date,
                    "completion_result": task_by_issue[issue.id].completion_result,
                } if issue.id in task_by_issue else None),
            }
            for issue in issues
        ],
        "last_run": _scan_payload(last_run) if last_run else None,
        "schedule": {
            "enabled": (os.environ.get("AUTOMATION_SCAN_ENABLED") or "true").strip().lower() not in {"0", "false", "no", "off"},
            "timezone": "Asia/Shanghai",
            "hour": scan_hour(),
            "next_run_at": next_scheduled_scan(),
            "mode": "remind_and_create_tasks_only",
            "auto_stop_enabled": False,
        },
    }


async def _scheduler_loop() -> None:
    delay = max(1, int(os.environ.get("AUTOMATION_SCAN_STARTUP_DELAY_SECONDS") or "30"))
    await asyncio.sleep(delay)
    while True:
        local_date = utcnow().astimezone(BEIJING).date()
        run_key = f"scheduled:{local_date.isoformat()}"
        try:
            async with db_manager.async_session_maker() as db:
                await run_automation_scan(db, trigger="scheduled", run_key=run_key)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduled automation scan failed")
        sleep_seconds = max(60.0, (next_scheduled_scan() - utcnow()).total_seconds())
        await asyncio.sleep(sleep_seconds)


def start_automation_scheduler() -> Optional[asyncio.Task]:
    enabled = (os.environ.get("AUTOMATION_SCAN_ENABLED") or "true").strip().lower() not in {"0", "false", "no", "off"}
    if not enabled or os.environ.get("IS_LAMBDA") == "true":
        logger.info("Daily automation scheduler is disabled")
        return None
    logger.info("Daily automation scheduler enabled at %02d:00 Asia/Shanghai", scan_hour())
    return asyncio.create_task(_scheduler_loop(), name="daily-automation-scan")


async def stop_automation_scheduler(task: Optional[asyncio.Task]) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
