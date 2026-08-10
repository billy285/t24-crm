from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.employees import Employees
from models.sales_call_activities import SalesCallActivities
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_lead_assignment_logs import SalesLeadAssignmentLogs
from models.sales_leads import SalesLeads


PROTECTED_STATUSES = {"follow_up", "interested", "appointment"}
CLOSED_STATUSES = {"won", "lost", "blocked"}


def aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def queue_category(lead: SalesLeads) -> str:
    if lead.status in PROTECTED_STATUSES:
        return "follow_up"
    if int(lead.rotation_count or 0) > 0:
        return "recycled"
    if int(lead.contact_attempt_count or 0) > 0:
        return "retry"
    return "new"


async def run_sales_lead_cycle(db: AsyncSession, *, now: Optional[datetime] = None, commit: bool = True) -> dict:
    """Release expired/stale execution ownership without deleting or rewriting history."""
    now = now or datetime.now(timezone.utc)
    leads = (await db.execute(select(SalesLeads))).scalars().all()
    released_cooldown = released_unstarted = protected = 0
    for lead in leads:
        lead.last_automation_at = now
        if lead.do_not_contact or lead.is_blacklisted or lead.status == "blocked":
            lead.automation_state = "blocked"
            continue
        if lead.status in {"won", "lost"} or lead.converted_customer_id:
            lead.automation_state = "closed"
            continue
        if lead.status in PROTECTED_STATUSES:
            lead.automation_state = "protected"
            protected += 1
            continue
        cooldown = aware(lead.cooldown_until)
        if cooldown and cooldown > now:
            lead.automation_state = "cooling"
            continue
        if cooldown and cooldown <= now:
            lead.cooldown_until = None
            lead.automation_state = "eligible"
            released_cooldown += 1
        elif lead.automation_state not in {"eligible", "assigned"}:
            lead.automation_state = "eligible"

        assigned_at = aware(lead.assigned_at or lead.updated_at or lead.created_at)
        if lead.assigned_sales_id and lead.status == "new" and assigned_at and assigned_at + timedelta(hours=48) <= now:
            activity_count = (await db.execute(
                select(func.count(SalesCallActivities.id)).where(SalesCallActivities.lead_id == lead.id)
            )).scalar_one()
            if not activity_count:
                old_id, old_name = lead.assigned_sales_id, lead.assigned_sales_name
                lead.last_assigned_sales_id = old_id
                lead.assigned_sales_id = None
                lead.assigned_sales_name = None
                lead.assigned_at = None
                lead.automation_state = "eligible"
                lead.rotation_count = int(lead.rotation_count or 0) + 1
                lead.last_recycle_reason = "分配后48小时未开始处理，系统自动回收"
                db.add(SalesLeadAssignmentLogs(
                    lead_id=lead.id, action="auto_reclaimed_unstarted",
                    from_sales_employee_id=old_id, from_sales_employee_name=old_name,
                    reason=lead.last_recycle_reason, operated_by_name="系统自动循环",
                ))
                released_unstarted += 1
    if commit:
        await db.commit()
    return {
        "released_from_cooldown": released_cooldown,
        "released_unstarted": released_unstarted,
        "protected": protected,
        "scanned": len(leads),
        "ran_at": now,
    }


async def ensure_daily_batch(
    db: AsyncSession, sales_employee_id: int, target_date: date, quota: int, *, commit: bool = True
) -> dict:
    now = datetime.now(timezone.utc)
    await run_sales_lead_cycle(db, now=now, commit=False)
    existing = (await db.execute(select(SalesDailyDialTasks).where(
        SalesDailyDialTasks.sales_employee_id == sales_employee_id,
        SalesDailyDialTasks.task_date == target_date,
    ))).scalars().all()
    if len(existing) >= quota:
        if commit:
            await db.commit()
        else:
            await db.flush()
        return {"created": 0, "total": len(existing)}

    used_today = set((await db.execute(select(SalesDailyDialTasks.lead_id).where(
        SalesDailyDialTasks.task_date == target_date
    ))).scalars().all())
    active_sales = (await db.execute(select(func.count(Employees.id)).where(
        Employees.role == "sales", Employees.status.in_(["active", "probation"])
    ))).scalar_one()
    candidates = (await db.execute(select(SalesLeads).where(
        SalesLeads.is_blacklisted.is_(False),
        SalesLeads.do_not_contact.is_(False),
        SalesLeads.status.notin_(list(CLOSED_STATUSES)),
        or_(SalesLeads.assigned_sales_id == sales_employee_id, SalesLeads.assigned_sales_id.is_(None)),
    ))).scalars().all()

    def eligible(lead: SalesLeads) -> bool:
        if lead.id in used_today:
            return False
        follow_up = aware(lead.next_follow_up_at)
        cooldown = aware(lead.cooldown_until)
        if cooldown and cooldown > now:
            return False
        if follow_up and follow_up.date() > target_date:
            return False
        if lead.last_contact_at and lead.status not in PROTECTED_STATUSES:
            last_contact = aware(lead.last_contact_at)
            if last_contact and last_contact + timedelta(hours=36) > now:
                return False
        if lead.assigned_sales_id is None and lead.last_assigned_sales_id == sales_employee_id and int(lead.rotation_count or 0) > 0 and int(active_sales or 0) > 1:
            return False
        return True

    candidates = [lead for lead in candidates if eligible(lead)]
    category_order = {"follow_up": 0, "retry": 1, "recycled": 2, "new": 3}
    candidates.sort(key=lambda lead: (
        category_order[queue_category(lead)],
        aware(lead.next_follow_up_at) or datetime.max.replace(tzinfo=timezone.utc),
        lead.id,
    ))
    employee = await db.get(Employees, sales_employee_id)
    created = 0
    category_counts = {"follow_up": 0, "retry": 0, "recycled": 0, "new": 0}
    for lead in candidates:
        if len(existing) + created >= quota:
            break
        category = queue_category(lead)
        if lead.assigned_sales_id is None:
            old_id = lead.last_assigned_sales_id
            lead.assigned_sales_id = sales_employee_id
            lead.assigned_sales_name = employee.name if employee else None
            lead.assigned_at = now
            lead.automation_state = "assigned"
            db.add(SalesLeadAssignmentLogs(
                lead_id=lead.id, action="auto_assigned",
                from_sales_employee_id=old_id,
                to_sales_employee_id=sales_employee_id,
                to_sales_employee_name=employee.name if employee else None,
                reason=f"系统生成{target_date.isoformat()}每日队列（{category}）",
                operated_by_name="系统自动循环",
            ))
        db.add(SalesDailyDialTasks(
            sales_employee_id=sales_employee_id, task_date=target_date,
            lead_id=lead.id, status="pending", queue_category=category,
        ))
        used_today.add(lead.id)
        created += 1
        category_counts[category] += 1
    if commit:
        await db.commit()
    else:
        await db.flush()
    return {"created": created, "total": len(existing) + created, "categories": category_counts}


async def automation_overview(db: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    leads = (await db.execute(select(SalesLeads))).scalars().all()
    counts = {"eligible": 0, "assigned": 0, "protected": 0, "cooling": 0, "blocked": 0, "closed": 0}
    for lead in leads:
        state = lead.automation_state or "eligible"
        if aware(lead.cooldown_until) and aware(lead.cooldown_until) > now:
            state = "cooling"
        counts[state if state in counts else "eligible"] += 1
    active_sales = (await db.execute(select(func.count(Employees.id)).where(
        Employees.role == "sales", Employees.status.in_(["active", "probation"])
    ))).scalar_one()
    daily_capacity = int(active_sales or 0) * 100
    reusable = counts["eligible"] + counts["assigned"] + counts["protected"] + counts["cooling"]
    return {
        "counts": counts,
        "total": len(leads),
        "reusable": reusable,
        "active_sales": int(active_sales or 0),
        "daily_capacity": daily_capacity,
        "estimated_pool_days": round(reusable / daily_capacity, 1) if daily_capacity else None,
        "rules": {
            "daily_default": 100,
            "unstarted_release_hours": 48,
            "same_sales_no_answer_attempts": 3,
            "no_answer_cooldown_days": 30,
            "soft_reject_cooldown_days": 60,
            "existing_provider_cooldown_days": 90,
            "minimum_company_contact_gap_hours": 36,
            "protected_statuses": sorted(PROTECTED_STATUSES),
        },
    }
