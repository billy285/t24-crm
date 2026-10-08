"""Move today's pending work without changing completed call attribution."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from models.sales_daily_dial_tasks import SalesDailyDialTasks

async def sync_pending_daily_tasks(db, lead, new_employee_id, *, now=None):
    today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("Asia/Shanghai")).date()
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
