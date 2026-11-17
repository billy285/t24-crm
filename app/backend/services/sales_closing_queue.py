"""Management closing workspace derived from immutable qualification and management events."""
from datetime import datetime, timezone
import json
from typing import Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import aliased

from models.employees import Employees
from models.sales_call_activities import SalesCallActivities
from models.sales_intelligence import SalesInsightEvents
from models.sales_leads import SalesLeads
from services.prospect_verification import quality_for_many
from services.sales_contact_protection import contact_protection_summaries
from services.sales_dossiers import active_actor
from services.sales_enrichment import saved_dial_phone
from services.sales_queue_policy import aware
from services.sales_task_assignment import CLOSING_EVENTS, sync_pending_daily_tasks
from services.sales_workflow_locks import lock_sales_workflow

POSITIVE = ("interested", "appointment")
NEGATIVE = ("not_interested", "not_now", "existing_provider", "do_not_contact")
MANAGER_ROLES = {"sales_manager", "admin", "super_admin"}
QUALITY_STOP = {"invalid_phone", "not_target", "closed"}


class ClosingAction(BaseModel):
    action: Literal["claim", "take_over", "follow_up", "lost"]
    revision: int = Field(ge=0)
    note: Optional[str] = Field(default=None, max_length=2000)
    next_follow_up_at: Optional[datetime] = None

    @field_validator("next_follow_up_at")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("请使用带时区的回访时间")
        return aware(value)


def record_manual_interest(db, lead, user, *, at=None):
    """Preserve who qualified a lead through the ordinary lead editor."""
    db.add(SalesInsightEvents(lead_id=lead.id, kind="closing_qualified",
        actor_id=int(user.id), actor_name=user.name, owner_id=lead.assigned_sales_id,
        payload_json=json.dumps({"source_name": lead.assigned_sales_name, "note": lead.notes, "status": lead.status},
                                ensure_ascii=False), created_at=at or datetime.now(timezone.utc)))


async def retain_legacy_interest(db, lead, user):
    if lead.status not in POSITIVE:
        return
    recorded = await db.scalar(select(SalesCallActivities.id).where(
        SalesCallActivities.lead_id == lead.id, SalesCallActivities.outcome.in_(POSITIVE)).limit(1))
    if recorded is None:
        captured = await db.scalar(select(SalesInsightEvents.id).where(
            SalesInsightEvents.lead_id == lead.id, SalesInsightEvents.kind == "closing_qualified").limit(1))
        if captured is None:
            record_manual_interest(db, lead, user, at=aware(lead.last_contact_at or lead.updated_at or lead.created_at))


async def previous_interest(db, lead_id):
    last = (await db.execute(select(SalesCallActivities.outcome, SalesCallActivities.called_at).where(
        SalesCallActivities.lead_id == lead_id, SalesCallActivities.outcome.in_(POSITIVE + NEGATIVE)
    ).order_by(SalesCallActivities.called_at.desc(), SalesCallActivities.id.desc()).limit(1))).first()
    manual = await db.scalar(select(SalesInsightEvents).where(
        SalesInsightEvents.lead_id == lead_id, SalesInsightEvents.kind == "closing_qualified"
    ).order_by(SalesInsightEvents.id.desc()).limit(1))
    if manual is not None and (last is None or aware(manual.created_at) > aware(last.called_at)):
        return json.loads(manual.payload_json).get("status", "interested")
    return last.outcome if last is not None and last.outcome in POSITIVE else None


async def management_actor(db, user):
    if user.role not in MANAGER_ROLES:
        raise HTTPException(403, "踢单由销售主管和管理员处理")
    return await active_actor(db, user)


def _activity_id(outcomes, *, first=False):
    activity = SalesCallActivities
    ordering = (activity.called_at, activity.id) if first else (activity.called_at.desc(), activity.id.desc())
    return (select(activity.id).where(activity.lead_id == SalesLeads.id, activity.outcome.in_(outcomes))
            .order_by(*ordering).limit(1).correlate(SalesLeads).scalar_subquery())


def _event_id(kinds, *, first=False):
    event = SalesInsightEvents
    return (select(event.id).where(event.lead_id == SalesLeads.id, event.kind.in_(kinds))
            .order_by(event.id if first else event.id.desc()).limit(1)
            .correlate(SalesLeads).scalar_subquery())


def _rows(scope):
    """One row per lead. Cached/current lead status alone can lose a past qualification."""
    positive = aliased(SalesCallActivities)
    signal = aliased(SalesCallActivities)
    manual = aliased(SalesInsightEvents)
    event = aliased(SalesInsightEvents)
    latest_manual = aliased(SalesInsightEvents)
    manual_first = and_(manual.id.is_not(None),
        or_(positive.id.is_(None), manual.created_at < positive.called_at))
    source = case((event.id.is_not(None), event.owner_id),
                  (manual_first, manual.owner_id),
                  (positive.id.is_not(None), positive.sales_employee_id), else_=SalesLeads.assigned_sales_id)
    converted = or_(SalesLeads.converted_customer_id.is_not(None), SalesLeads.converted_at.is_not(None))
    rejected = and_(signal.outcome.in_(NEGATIVE),
                    or_(latest_manual.id.is_(None), latest_manual.created_at <= signal.called_at))
    renewed_interest = or_(latest_manual.created_at > event.created_at,
                           and_(signal.outcome.in_(POSITIVE), signal.called_at > event.created_at))
    stage = case((converted, "won"),
                 (or_(SalesLeads.status == "lost", rejected), "lost"),
                 (and_(event.kind == "closing_lost", renewed_interest), "pending"),
                 (event.kind == "closing_lost", "lost"),
                 (event.id.is_not(None), "working"), else_="pending")
    query = (select(SalesLeads, positive, manual, event, source.label("source_id"), Employees.name,
                    stage.label("stage")).select_from(SalesLeads)
             .outerjoin(positive, positive.id == _activity_id(POSITIVE, first=True))
             .outerjoin(signal, signal.id == _activity_id(POSITIVE + NEGATIVE))
             .outerjoin(manual, manual.id == _event_id(("closing_qualified",), first=True))
             .outerjoin(latest_manual, latest_manual.id == _event_id(("closing_qualified",)))
             .outerjoin(event, event.id == _event_id(CLOSING_EVENTS))
             .outerjoin(Employees, Employees.id == source)
             .where(SalesLeads.is_blacklisted.is_(False), SalesLeads.do_not_contact.is_(False),
                    SalesLeads.status != "blocked",
                    or_(SalesLeads.status.notin_(("won", "converted")), converted),
                    or_(SalesLeads.status.in_(POSITIVE), positive.id.is_not(None),
                        manual.id.is_not(None), event.id.is_not(None))))
    if scope is not None:
        query = query.where(scope)
    return query, source, stage


def _snapshot(row):
    lead, positive, manual, event, source_id, source_name, stage = row
    qualified = json.loads(manual.payload_json) if manual is not None else {}
    progress = json.loads(event.payload_json) if event is not None else {}
    manual_first = manual is not None and (positive is None or aware(manual.created_at) < aware(positive.called_at))
    first_note = qualified.get("note") if manual_first else positive.notes if positive else None
    source_name = (source_name or progress.get("source_name") or
                   (positive.sales_employee_name if positive and positive.sales_employee_id == source_id else None)
                   or qualified.get("source_name") or (lead.assigned_sales_name if lead.assigned_sales_id == source_id else None))
    interest_note = progress.get("interest_note") or first_note or lead.notes
    due = aware(lead.next_follow_up_at)
    if stage == "pending" and event:
        # A fresh positive signal reopened a concluded case. The old closer and
        # last loss note belong to history until someone claims the new work.
        interest_note = lead.notes or first_note
        progress = {}
    if event and progress.get("next_follow_up_at"):
        due = aware(datetime.fromisoformat(progress["next_follow_up_at"]))
    if stage in {"won", "lost"}:
        due = None
    return {"lead_id": lead.id, "business_name": lead.business_name, "phone": lead.phone, "country": lead.country,
            "stage": stage, "source_sales_id": source_id, "source_sales_name": source_name,
            "closer_id": event.actor_id if event and stage != "pending" else None,
            "closer_name": event.actor_name if event and stage != "pending" else None,
            "interest_note": interest_note, "note": progress.get("note"),
            "next_follow_up_at": due, "revision": event.id if event else 0}


async def _present(db, rows):
    leads = [row[0] for row in rows]
    protections = await contact_protection_summaries(db, leads)
    qualities = await quality_for_many(db, "lead", [lead.id for lead in leads]) if leads else {}
    result = []
    for row in rows:
        item = _snapshot(row)
        reason = protections[item["lead_id"]]["reason"]
        if qualities[item["lead_id"]]["status"] in QUALITY_STOP:
            reason = "商家已核验为号码无效、非目标或停业"
        if item["stage"] in {"won", "lost"}:
            reason = "该商家已结束踢单"
        result.append({**item, "can_contact": not reason, "contact_reason": reason})
    return result


async def closing_list(db, scope, stage_filter, source_sales_id, search, page, page_size):
    base, source, stage = _rows(scope)
    # Facets contain only employees represented by leads visible to this viewer.
    sources = (await db.execute(base.with_only_columns(source.label("id"), Employees.name)
        .where(source.is_not(None)).distinct().order_by(Employees.name, source))).all()
    if stage_filter == "active":
        base = base.where(stage.in_(("pending", "working")))
    elif stage_filter != "all":
        base = base.where(stage == stage_filter)
    if source_sales_id is not None:
        base = base.where(source == source_sales_id)
    if search and search.strip():
        term = search.strip()
        base = base.where(or_(SalesLeads.business_name.icontains(term, autoescape=True),
                              SalesLeads.phone.icontains(term, autoescape=True)))
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = (await db.execute(base.order_by(SalesLeads.next_follow_up_at.is_(None),
        SalesLeads.next_follow_up_at, SalesLeads.id).offset((page - 1) * page_size).limit(page_size))).all()
    return {"items": await _present(db, rows), "total": total, "page": page, "page_size": page_size,
            "sources": [{"id": id_, "name": name or str(id_)} for id_, name in sources]}


async def closing_dial_target(db, lead_id, actor, scope, revision):
    base, _, _ = _rows(scope)
    row = (await db.execute(base.where(SalesLeads.id == lead_id))).one_or_none()
    if row is None:
        raise HTTPException(404, "该商家不在你的踢单名单内")
    item = (await _present(db, [row]))[0]
    if revision is not None and item["revision"] != revision:
        raise HTTPException(409, "踢单进度已更新，请刷新名单后再拨打")
    if item["stage"] != "working":
        raise HTTPException(409, "该商家当前没有进行中的踢单")
    if item["closer_id"] != actor.id:
        raise HTTPException(403, "仅当前踢单负责人可以拨打")
    if not item["can_contact"]:
        raise HTTPException(409, item["contact_reason"])
    return {"phone": await saved_dial_phone(db, row[0]), "country": row[0].country,
            "lead_id": lead_id, "revision": item["revision"]}


async def update_closing(db, lead_id, user, scope_for, payload):
    if user.role not in MANAGER_ROLES:
        raise HTTPException(403, "踢单由销售主管和管理员处理")
    await lock_sales_workflow(db, lead_ids=[lead_id])
    actor = await management_actor(db, user)
    base, _, _ = _rows(await scope_for(db, actor))
    query = base.where(SalesLeads.id == lead_id).execution_options(populate_existing=True)
    row = (await db.execute(query)).one_or_none()
    if row is None:
        raise HTTPException(404, "该商家未进入踢单名单或不在你的管理范围")
    item = (await _present(db, [row]))[0]
    if item["revision"] != payload.revision:
        raise HTTPException(409, "踢单进度已更新，请刷新名单后重试")
    if not item["can_contact"]:
        raise HTTPException(409, item["contact_reason"])
    if payload.action == "claim":
        if item["stage"] != "pending":
            raise HTTPException(409, "该商家已有踢单负责人")
    else:
        if item["stage"] != "working":
            raise HTTPException(409, "请先接手这家商家")
        if payload.action == "take_over":
            if actor.role != "super_admin":
                raise HTTPException(403, "只有老板可以接手其他负责人的踢单")
            if item["closer_id"] == actor.id:
                raise HTTPException(409, "你已是这家商家的踢单负责人")
        elif item["closer_id"] != actor.id:
            raise HTTPException(403, "由当前踢单负责人记录进展")
    note = (payload.note or "").strip()
    if payload.action != "claim" and not note:
        raise HTTPException(422, "请填写跟进内容、接手说明或结束原因")
    if payload.action == "follow_up" and payload.next_follow_up_at is None:
        raise HTTPException(422, "请填写下次回访时间")
    lead = row[0]
    if payload.action == "claim":
        await sync_pending_daily_tasks(db, lead, None)
    if payload.action == "lost":
        lead.status = "lost"
        lead.next_follow_up_at = None
        lead.automation_state = "closed"
        await sync_pending_daily_tasks(db, lead, None)
    else:
        lead.automation_state = "closing_active"
        lead.next_follow_up_at = payload.next_follow_up_at or item["next_follow_up_at"]
    event = SalesInsightEvents(lead_id=lead.id, kind="closing_" + payload.action,
        actor_id=actor.id, actor_name=actor.name, owner_id=item["source_sales_id"],
        payload_json=json.dumps({"source_name": item["source_sales_name"], "interest_note": item["interest_note"],
            "note": note, "next_follow_up_at": aware(lead.next_follow_up_at).isoformat() if lead.next_follow_up_at else None},
            ensure_ascii=False), created_at=datetime.now(timezone.utc))
    db.add(event)
    await db.flush()
    updated = (await _present(db, [(await db.execute(query)).one()]))[0]
    await db.commit()
    return updated
