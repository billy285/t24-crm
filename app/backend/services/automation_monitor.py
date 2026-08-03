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
from models.employees import Employees
from models.management_decisions import CustomerEngagement
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
    return f"{row['code']}:customer:{int(row['customer_id'])}:project:{int(row.get('project_id') or 0)}"


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
        anomalies = review.get("anomalies", [])
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
                _, created, updated = await _ensure_task(db, issue, owner_by_project=owner_by_project)
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
