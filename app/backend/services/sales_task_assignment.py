"""Move today's pending work without changing completed call attribution."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import func, select
from models.sales_intelligence import SalesInsightEvents
from models.sales_daily_dial_tasks import SalesDailyDialTasks

CLOSING_EVENTS = ("closing_claim", "closing_follow_up", "closing_take_over", "closing_pause",
                  "closing_take_over_paused", "closing_delegate", "closing_delegate_paused",
                  "closing_resume", "closing_lost")


def active_closing_leads():
    event = SalesInsightEvents
    latest = (select(func.max(event.id)).where(event.kind.in_(CLOSING_EVENTS)).group_by(event.lead_id))
    return select(event.lead_id).where(event.id.in_(latest), event.kind != "closing_lost")


async def lead_has_active_closer(db, lead_id):
    latest = await db.scalar(select(SalesInsightEvents.kind).where(
        SalesInsightEvents.lead_id == lead_id, SalesInsightEvents.kind.in_(CLOSING_EVENTS)
    ).order_by(SalesInsightEvents.id.desc()).limit(1))
    return latest is not None and latest != "closing_lost"


async def sync_pending_daily_tasks(db, lead, new_employee_id, *, now=None):
    today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("Asia/Shanghai")).date()
    if new_employee_id is not None and await lead_has_active_closer(db, lead.id):
        new_employee_id = None
    tasks = (await db.execute(select(SalesDailyDialTasks).where(
        SalesDailyDialTasks.lead_id == lead.id, SalesDailyDialTasks.task_date >= today,
    ))).scalars().all()
    dates = set()
    for task in tasks:
        if task.status == "cancelled" and new_employee_id is not None:
            dates.add(task.task_date)
        if task.status == "pending" and task.sales_employee_id != new_employee_id:
            task.status = "cancelled"
            dates.add(task.task_date)
    if new_employee_id is None or lead.is_blacklisted or lead.do_not_contact or lead.status in {"blocked", "lost", "won"} or lead.converted_customer_id:
        return
    for task_date in dates:
        target = next((task for task in tasks if task.sales_employee_id == new_employee_id and task.task_date == task_date), None)
        if target:
            if target.status == "cancelled":
                target.status = "pending"
            continue
        db.add(SalesDailyDialTasks(sales_employee_id=new_employee_id, lead_id=lead.id,
            task_date=task_date, status="pending", queue_category="follow_up" if lead.status in {"follow_up", "interested", "appointment"} else "new"))
