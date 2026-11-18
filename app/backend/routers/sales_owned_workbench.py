"""Read a salesperson's current assignments independently of the daily dial queue."""
from datetime import date, datetime, timezone
import re
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_intelligence import SalesLeadProfiles
from models.sales_leads import SalesLeads
from routers.sales_leads import BUSINESS_TIMEZONE, _ensure_lead_role, _resolve_workbench_salesperson
from schemas.auth import UserResponse
from services.merchant_industries import workbench_industry_group
from services.prospect_verification import quality_for_many
from services.sales_contact_protection import contact_protection_summaries
from services.sales_dossiers import active_actor
from services.sales_intelligence import unpack
from services.sales_queue_policy import aware, contact_queue_context, queue_context
from services.sales_task_assignment import active_closing_leads

router = APIRouter(prefix="/api/v1/sales-leads/workbench", tags=["sales-leads"])
View = Literal["summary", "assigned", "callable"]


def _assignment_matches(row, industry, search, digits, lead_id):
    if lead_id is not None and row.id != lead_id:
        return False
    if industry and industry != "all" and workbench_industry_group(row.industry) != industry:
        return False
    if not search:
        return True
    return (any(search in (field or "").casefold() for field in
                (row.business_name, row.contact_name, row.phone, row.city, row.state)) or
            bool(digits and digits in re.sub(r"\D", "", row.phone or "")))


async def _contact_availability(db, rows, salesperson_id, day):
    """Mirror the manual-task and dial guards for display. They recheck on write."""
    reasons = {}
    needs_phone = set()
    for offset in range(0, len(rows), 2000):
        batch = rows[offset:offset + 2000]
        ids = [row.id for row in batch]
        protections = await contact_protection_summaries(db, batch, include_dialability=True)
        quality = await quality_for_many(db, "lead", ids)
        closers = set(await db.scalars(select(SalesLeads.id).where(
            SalesLeads.id.in_(ids), SalesLeads.id.in_(active_closing_leads()))))
        other_tasks = set(await db.scalars(select(SalesDailyDialTasks.lead_id).where(
            SalesDailyDialTasks.lead_id.in_(ids), SalesDailyDialTasks.task_date == day,
            SalesDailyDialTasks.sales_employee_id != salesperson_id,
            SalesDailyDialTasks.status.in_(("pending", "completed")))))
        for row in batch:
            if not protections[row.id]["has_dialable_number"]:
                needs_phone.add(row.id)
            if row.status in {"converted", "won", "lost"} or row.converted_customer_id or row.converted_at:
                reasons[row.id] = "该商家已结束电话跟进"
            elif not protections[row.id]["can_contact"]:
                reasons[row.id] = protections[row.id]["reason"]
            elif row.id in closers:
                reasons[row.id] = "已由主管或老板接手"
            elif quality[row.id]["status"] in {"invalid_phone", "not_target", "closed"}:
                reasons[row.id] = "已标记为号码无效、非目标或停业"
            elif row.task_status == "completed":
                reasons[row.id] = "所选日期已完成联系"
            elif row.task_status == "cancelled" or (row.id in other_tasks and row.task_status != "pending"):
                reasons[row.id] = "请先核对联系任务或交接状态"
    return reasons, needs_phone


@router.get("/owned")
async def owned_workbench(
    sales_employee_id: Optional[int] = None,
    target_date: Optional[date] = None,
    view: View = "assigned",
    industry: Optional[Literal["all", "restaurant", "beauty", "other"]] = None,
    q: Optional[str] = Query(None, max_length=160),
    lead_id: Optional[int] = Query(None, gt=0),
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_lead_role(current_user)
    actor = await active_actor(db, current_user)
    person = await _resolve_workbench_salesperson(db, current_user.model_copy(update={"name": actor.name}), sales_employee_id)
    now = datetime.now(timezone.utc)
    today = now.astimezone(BUSINESS_TIMEZONE).date()
    day = target_date or today
    # Only current ownership is authoritative. A leftover task from a prior
    # assignment grants no visibility. Keep large notes and AI snapshots out.
    lead, task = SalesLeads, SalesDailyDialTasks
    query = (select(lead.id, lead.business_name, lead.contact_name, lead.phone, lead.country,
        lead.state, lead.city, lead.address, lead.industry, lead.status, lead.converted_at,
        lead.converted_customer_id, lead.do_not_contact, lead.is_blacklisted, lead.assigned_sales_id,
        lead.cooldown_until, lead.next_follow_up_at, SalesLeadProfiles.payload_json,
        task.id.label("task_id"), task.status.label("task_status"))
        .outerjoin(SalesLeadProfiles, SalesLeadProfiles.lead_id == lead.id)
        .outerjoin(task, and_(task.lead_id == lead.id, task.task_date == day,
                              task.sales_employee_id == person.id))
        .where(lead.assigned_sales_id == person.id)
        .order_by(func.coalesce(lead.assigned_at, lead.created_at).desc(), lead.id.desc()))
    rows = (await db.execute(query)).all()
    _, start, end = await queue_context(db, [], day)
    search = (q or "").strip().casefold()
    digits = re.sub(r"\D", "", search) if re.fullmatch(r"[+()\d\s.\-]+", search) else ""
    matching = [row for row in rows if _assignment_matches(row, industry, search, digits, lead_id)] if view != "summary" else []
    page = matching[skip:skip + limit] if view == "assigned" else []
    page_ids = {row.id for row in page}
    contexts = {}
    candidates = []
    for row in rows:
        if day != today and row.id not in page_ids:
            continue
        context = contact_queue_context(row, now=now, profile=unpack(row.payload_json), start=start, end=end)
        if row.id in page_ids or context["in_contact_window"] and day == today:
            contexts[row.id] = context
        follow_up_due = not row.next_follow_up_at or context["due_follow_up"]
        if day == today and context["in_contact_window"] and follow_up_due and row.task_status not in {"completed", "cancelled"}:
            candidates.append(row)
    checked = {row.id: row for row in (*candidates, *page)}
    reasons, needs_phone = await _contact_availability(db, list(checked.values()), person.id, day)
    callable_ids = {row.id for row in candidates if row.id not in reasons and row.id not in needs_phone}
    if view == "callable":
        matching = [row for row in matching if row.id in callable_ids]
        page = matching[skip:skip + limit]

    items = []
    for row in page:
        reason = reasons.get(row.id) if day == today else "所选日期仅供查看"
        note = reason or ("号码待核实，可先完善资料" if row.id in needs_phone else None)
        if row.next_follow_up_at:
            zone = contexts[row.id]["timezone"]
            follow_up = aware(row.next_follow_up_at).astimezone(ZoneInfo(zone) if zone else BUSINESS_TIMEZONE)
            schedule = f"约定回访 · {'当地' if zone else '北京时间'} {follow_up:%Y-%m-%d %H:%M}"
            note = f"{note} · {schedule}" if note else schedule
        items.append({"lead": {"id": row.id, "business_name": row.business_name, "contact_name": row.contact_name,
            "phone": row.phone, "country": row.country, "state": row.state, "city": row.city, "industry": row.industry,
            "industry_group": workbench_industry_group(row.industry), "status": row.status},
            "task_id": row.task_id, "task_status": row.task_status, "contact_queue": contexts[row.id],
            "can_start": reason is None, "unavailable_reason": note})
    return {"sales_employee_id": person.id, "target_date": day, "evaluated_at": now,
            "counts": {"assigned": len(rows), "pending": sum(row.task_status == "pending" for row in rows),
                       "callable": len(callable_ids)}, "total": len(matching), "skip": skip, "limit": limit,
            "has_more": skip + len(items) < len(matching), "items": items}
