"""An actionable, deduplicated view of the current owner's recorded communications."""
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import Integer, and_, case, cast, func, null, or_, select, union_all
from sqlalchemy.orm import load_only

from models.ringcentral_call_records import RingCentralCallRecords as Call
from models.sales_call_activities import SalesCallActivities as Activity
from models.sales_daily_dial_tasks import SalesDailyDialTasks as Task
from models.sales_leads import SalesLeads as Lead
from schemas.sales_communication import CALL_OUTCOMES, activity_selections
from services.sales_contact_protection import contact_protection_summaries
from services.sales_queue_policy import aware
from services.sales_task_assignment import active_closing_leads


RevisitGroup = Literal["follow_up", "interested", "appointment", "no_answer"]


def verified_outgoing():
    return (Call.lead_id.is_not(None), Call.sync_status == "verified", func.lower(Call.direction) == "outbound",
            Call.started_at.is_not(None))


def today_task(lead_id, owner_id, day):
    return select(Task.id).where(Task.lead_id == lead_id, Task.sales_employee_id == owner_id,
                                 Task.task_date == day, Task.status == "pending")


async def can_record_previously_dialed(db, lead, day):
    if lead.status != "new" or not lead.assigned_sales_id:
        return False
    previous = await db.scalar(select(Call.id).where(*verified_outgoing(), Call.lead_id == lead.id,
        Call.sales_employee_id == lead.assigned_sales_id).limit(1))
    if previous is None:
        return False
    return await db.scalar(today_task(lead.id, lead.assigned_sales_id, day)) is None


def ranked_contacts(model, time, candidates, *conditions):
    # Scope before ranking. Importing a large batch of untouched leads adds no contact rows.
    return (select(model.id.label("id"), model.lead_id, func.row_number().over(
        partition_by=model.lead_id, order_by=(time.desc(), model.id.desc())).label("position"))
        .join(candidates, and_(model.lead_id == candidates.c.id,
                              model.sales_employee_id == candidates.c.assigned_sales_id))
        .where(*conditions).subquery())


def _latest_query(conditions, day):
    candidates = (select(Lead.id, Lead.assigned_sales_id).where(*conditions, Lead.assigned_sales_id.is_not(None),
        Lead.do_not_contact.is_(False), Lead.is_blacklisted.is_(False),
        Lead.converted_customer_id.is_(None), Lead.converted_at.is_(None),
        Lead.status.in_(("new", "contacted", "interested", "appointment", "follow_up")),
        or_(Lead.cooldown_until.is_(None), Lead.cooldown_until <= datetime.now(timezone.utc)),
        ~Lead.id.in_(active_closing_leads())).cte("revisit_candidates"))
    saved = ranked_contacts(Activity, Activity.called_at, candidates)
    verified = ranked_contacts(Call, Call.started_at, candidates, *verified_outgoing())
    # Merge positive matches first, so untouched leads never fan out across two
    # outer joins and each communication table is joined back by its primary key.
    empty_id = cast(null(), Integer)
    evidence = union_all(
        select(saved.c.lead_id, saved.c.id.label("activity_id"), empty_id.label("call_id")).where(saved.c.position == 1),
        select(verified.c.lead_id, empty_id.label("activity_id"), verified.c.id.label("call_id")).where(verified.c.position == 1),
    ).subquery()
    latest = (select(evidence.c.lead_id, func.max(evidence.c.activity_id).label("activity_id"),
                     func.max(evidence.c.call_id).label("call_id")).group_by(evidence.c.lead_id).subquery())
    contact_time = case((Activity.called_at.is_(None), Call.started_at),
                        (Call.started_at > Activity.called_at, Call.started_at), else_=Activity.called_at)
    pending = today_task(Lead.id, Lead.assigned_sales_id, day).correlate(Lead).scalar_subquery()
    return (select(Lead, Activity, Call, case((Lead.status == "new", pending)).label("pending_task_id"))
        .select_from(latest).join(Lead, Lead.id == latest.c.lead_id)
        .outerjoin(Activity, Activity.id == latest.c.activity_id)
        .outerjoin(Call, Call.id == latest.c.call_id)
        .options(load_only(Activity.outcome, Activity.called_at, Activity.communication_record, Activity.notes,
                           Activity.sync_status, Activity.ringcentral_connected),
                 load_only(Call.started_at, Call.activity_id, Call.connected, Call.provider_result))
        .order_by(Lead.next_follow_up_at.is_(None), Lead.next_follow_up_at.asc(), contact_time.desc(), Lead.id))


def _summary(activity, call, task_id):
    # A verified call linked to this exact saved result represents the same interaction.
    same_call = activity is not None and call is not None and call.activity_id == activity.id
    snapshot = activity_selections(activity) if activity is not None else {"quick_notes": [], "outcomes": []}
    saved = {
        "note_at": aware(activity.called_at) if activity is not None else None,
        "quick_notes": [{"id": n["id"], "label": n["label"]} for n in snapshot["quick_notes"]],
        "notes": activity.notes[:220] if activity is not None and activity.notes else None,
        "pending_task_id": task_id,
    }
    if activity is not None and (call is None or same_call or aware(activity.called_at) >= aware(call.started_at)):
        outcome = activity.outcome
        confirmed = call.connected if same_call else None
        if not same_call and activity.sync_status == "verified":
            confirmed = activity.ringcentral_connected
        return {
            **saved, "at": aware(activity.called_at), "source": "crm", "outcome": outcome,
            "outcome_labels": snapshot["outcome_labels"] or [CALL_OUTCOMES.get(outcome, outcome)],
            "provider_connected": confirmed,
        }, snapshot["outcomes"]

    # A newer official call supplies the latest outcome. The last saved notes
    # and their timestamp still belong to the salesperson's earlier record.
    missed = (call.provider_result or "").strip().lower() in {
        "no answer", "unanswered", "missed", "busy", "rejected", "declined", "not connected",
        "call failed", "failed", "cancelled", "canceled", "abandoned", "voicemail", "voice mail",
    }
    outcome = "connected" if call.connected else "no_answer" if missed else "dialed"
    label = {"connected": "已接通", "no_answer": "未接通", "dialed": "已拨出"}[outcome]
    return {
        **saved, "at": aware(call.started_at), "source": "ringcentral", "outcome": outcome,
        "outcome_labels": [label], "provider_connected": None if outcome == "dialed" else bool(call.connected),
    }, snapshot["outcomes"]


async def revisit_page(db, conditions, day, group, note_id, skip, limit):
    """Apply the same phone/suppression guards as dialing *before* counting and paging."""
    stream = await db.stream(_latest_query(conditions, day).execution_options(yield_per=250))
    selected, summaries, latest_labels = [], {}, {}
    total = 0
    async for batch in stream.partitions(250):
        matches = []
        for lead, activity, call, task_id in batch:
            summary, outcomes = _summary(activity, call, task_id)
            result_key = "callback" if group == "follow_up" else group
            if group == "no_answer":
                if summary["outcome"] != "no_answer":
                    continue
            elif group and lead.status != group and result_key not in outcomes:
                continue
            matches.append((lead, summary))
        protection = await contact_protection_summaries(db, [lead for lead, _ in matches])
        for lead, summary in matches:
            if not protection[lead.id]["can_contact"]:
                continue
            for note in summary["quick_notes"]:
                rank = (summary["note_at"], lead.id)
                if note["id"] not in latest_labels or latest_labels[note["id"]][0] < rank:
                    latest_labels[note["id"]] = (rank, note)
            if note_id and not any(note["id"] == note_id for note in summary["quick_notes"]):
                continue
            if skip <= total < skip + limit:
                selected.append(lead)
                summaries[lead.id] = summary
            total += 1
    options = sorted((note for _, note in latest_labels.values()), key=lambda n: (n["label"], n["id"]))
    return selected, total, summaries, options
