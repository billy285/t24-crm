"""Exercise the rep-to-closer workflow through the API with synthetic merchants."""
import asyncio
from datetime import datetime, timedelta, timezone
from functools import partial

import pytest
from sqlalchemy import select

from backend.tests.test_sales_dossiers import auth as dossier_auth, dossier_api
from backend.tests.test_sales_lead_isolation import _auth_headers, sales_app_client
from models.employees import Employees
from models.sales_call_activities import SalesCallActivities
from models.sales_contact_protection import SalesPhoneSuppression
from models.sales_intelligence import SalesInsightEvents
from models.sales_leads import SalesLeads
from services import sales_closing_queue


LEADS = "/api/v1/sales-leads"
CLOSING = f"{LEADS}/closing-queue"
OWNER = _auth_headers("admin", 1, "Admin")
MANAGER = _auth_headers("sales_manager", 10, "Manager A")
REP = _auth_headers("sales", 11, "Sales A")
OUTSIDE_REP = _auth_headers("sales", 12, "Sales B")


async def create_merchant(client, name, phone, rep_id=11):
    response = await client.post(
        LEADS, headers=OWNER,
        json={"business_name": name, "phone": phone, "assigned_sales_id": rep_id},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def first_result(client, lead_id, *, rep=REP, outcome="interested"):
    prepared = await client.post(f"{LEADS}/workbench/prepare", headers=rep)
    assert prepared.status_code == 200, prepared.text
    workbench = await client.get(f"{LEADS}/workbench/today", headers=rep)
    assert workbench.status_code == 200, workbench.text
    task = next(item for item in workbench.json()["items"] if item["lead"]["id"] == lead_id)
    result = await client.post(
        f"{LEADS}/workbench/tasks/{task['task_id']}/result", headers=rep,
        json={"outcome": outcome, "notes": "店主想了解报价",
              "next_follow_up_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
    )
    assert result.status_code == 200, result.text


async def follow_up(client, lead_id, outcome, *, rep=REP):
    result = await client.post(
        f"{LEADS}/{lead_id}/follow-up", headers=rep,
        json={"outcome": outcome, "notes": f"后续沟通 {outcome}",
              "next_follow_up_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()},
    )
    assert result.status_code == 200, result.text


def historical_merchant(lead_id, *, status="contacted", assigned=11, **fields):
    return SalesLeads(
        id=lead_id, business_name=f"Legacy Salon {lead_id}", country="US",
        phone=f"+1212555{lead_id:04}", status=status, assigned_sales_id=assigned,
        assigned_sales_name={11: "Sales A", 12: "Sales B"}[assigned], **fields,
    )


async def seed_historical_contacts(sessions):
    """Pre-feature rows cover imported statuses and real archived call records."""
    now = datetime.now(timezone.utc)
    async with sessions() as db:
        db.add_all([
            historical_merchant(601, status="appointment", notes="店主约好周五演示"),
            historical_merchant(602),
            historical_merchant(603, status="interested", do_not_contact=True),
            historical_merchant(604, status="won", converted_customer_id=80),
            historical_merchant(605, status="new"),
            historical_merchant(606, status="interested", assigned=12),
        ])
        db.add_all([
            SalesCallActivities(lead_id=602, outcome=outcome, notes=note,
                                sales_employee_id=11, sales_employee_name="Sales A",
                                called_at=now - timedelta(days=offset))
            for outcome, note, offset in (
                ("interested", "想了解方案", 4), ("appointment", "约在周五", 3),
                ("no_answer", "今天没接", 1),
            )
        ])
        await db.commit()


async def queue(client, *, actor=OWNER, **filters):
    response = await client.get(CLOSING, headers=actor, params=filters)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_repeated_interest_and_missed_callback_keep_one_origination(sales_app_client):
    client = sales_app_client
    lead_id = await create_merchant(client, "Intent Salon", "+12125558001")
    assert (await queue(client))["items"] == []
    await first_result(client, lead_id)
    await follow_up(client, lead_id, "appointment")
    await follow_up(client, lead_id, "no_answer")
    await follow_up(client, lead_id, "no_answer")
    await follow_up(client, lead_id, "no_answer")
    listing = await queue(client)
    assert listing["total"] == 1
    row = listing["items"][0]
    assert row["lead_id"] == lead_id
    assert row["source_sales_id"] == 11
    assert (await client.get(f"{LEADS}/{lead_id}", headers=REP)).json()["assigned_sales_id"] == 11
    history = await client.get(f"{LEADS}/{lead_id}/call-history", headers=REP)
    assert [event["outcome"] for event in history.json()] == ["no_answer"] * 3 + ["appointment", "interested"]


@pytest.mark.asyncio
async def test_legacy_queue_scopes_before_source_filter_and_pagination(dossier_api):
    client, sessions = dossier_api
    await seed_historical_contacts(sessions)
    owner_queue = partial(queue, client, actor=dossier_auth(1))
    mine = await queue(client, actor=dossier_auth(10))
    assert {row["lead_id"] for row in mine["items"]} == {601, 602}
    assert 12 not in {source["id"] for source in mine["sources"]}
    all_leads = await owner_queue()
    assert {row["lead_id"] for row in all_leads["items"]} == {601, 602, 606}
    by_rep = await owner_queue(source_sales_id=12)
    assert [row["lead_id"] for row in by_rep["items"]] == [606]
    first = await owner_queue(source_sales_id=11, page_size=1, page=1)
    second = await owner_queue(source_sales_id=11, page_size=1, page=2)
    assert first["total"] == second["total"] == 2
    assert {first["items"][0]["lead_id"], second["items"][0]["lead_id"]} == {601, 602}
    forbidden = await client.get(CLOSING, headers=REP)
    assert forbidden.status_code == 403
    assert (await client.get(CLOSING, headers=dossier_auth(15))).status_code == 403

    # A historical reassignment does not change who first found the opportunity.
    async with sessions() as db:
        transferred = await db.get(SalesLeads, 602)
        transferred.assigned_sales_id = 12
        transferred.assigned_sales_name = "Sales B"
        await db.commit()
    original_source = await owner_queue(source_sales_id=11)
    assert {row["lead_id"] for row in original_source["items"]} == {601, 602}
    # Old imported/status-only prospects have no positive call event. The first
    # unanswered follow-up after rollout must not erase that prior qualification.
    await follow_up(client, 601, "no_answer", rep=dossier_auth(11))
    still_pending = await owner_queue(stage="pending", source_sales_id=11)
    legacy = next(row for row in still_pending["items"] if row["lead_id"] == 601)
    assert (legacy["source_sales_id"], legacy["interest_note"]) == (11, "店主约好周五演示")


@pytest.mark.asyncio
async def test_claim_and_followup_are_scoped_revisioned_and_separate_from_rep_calls(sales_app_client):
    client = sales_app_client
    own = await create_merchant(client, "Inside Team", "+12125558001")
    other = await create_merchant(client, "Outside Team", "+12125558002", rep_id=12)
    await first_result(client, own)
    await first_result(client, other, rep=OUTSIDE_REP, outcome="appointment")
    payload = {"action": "claim", "revision": 0}
    assert (await client.post(f"{CLOSING}/{own}", headers=REP, json=payload)).status_code == 403
    assert (await client.post(f"{CLOSING}/{other}", headers=MANAGER, json=payload)).status_code in {403, 404}
    claimed = await client.post(f"{CLOSING}/{own}", headers=MANAGER, json=payload)
    assert claimed.status_code == 200, claimed.text
    row = claimed.json()
    assert (row["stage"], row["source_sales_id"], row["closer_id"]) == ("working", 11, 10)
    assert row["interest_note"] == "店主想了解报价"
    dial_target = f"{CLOSING}/{own}/dial-target"
    allowed = await client.get(dial_target, headers=MANAGER)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["phone"] == "+12125558001"
    for forbidden_actor in (OWNER, REP):
        assert (await client.get(dial_target, headers=forbidden_actor)).status_code in {403, 409}
    repeat = await client.post(f"{CLOSING}/{own}", headers=OWNER, json=payload)
    assert repeat.status_code == 409
    due = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    update = {"action": "follow_up", "revision": row["revision"],
              "note": "老板已看过报价，周五确认", "next_follow_up_at": due.isoformat()}
    wrong_actor = await client.post(f"{CLOSING}/{own}", headers=OWNER, json=update)
    assert wrong_actor.status_code in {403, 409}
    saved = await client.post(f"{CLOSING}/{own}", headers=MANAGER, json=update)
    assert saved.status_code == 200, saved.text
    assert saved.json()["note"] == update["note"]
    assert saved.json()["revision"] > row["revision"]
    assert (await client.post(f"{CLOSING}/{own}", headers=MANAGER, json=update)).status_code == 409
    # Concurrent rep-side edits cannot silently move the closer's appointment.
    edit = await client.put(f"{LEADS}/{own}", headers=REP,
                            json={"next_follow_up_at": (due + timedelta(days=20)).isoformat()})
    assert edit.status_code in {403, 409}, edit.text
    late = await client.post(f"{LEADS}/{own}/follow-up", headers=REP,
                             json={"outcome": "no_answer", "notes": "销售刚看到未接通回执"})
    assert late.status_code in {403, 409}, late.text
    working = await queue(client, stage="working", source_sales_id=11)
    assert [item["lead_id"] for item in working["items"]] == [own]
    assert datetime.fromisoformat(working["items"][0]["next_follow_up_at"].replace("Z", "+00:00")) == due
    assert (await client.get(f"{LEADS}/{own}", headers=REP)).json()["assigned_sales_id"] == 11
    history = (await client.get(f"{LEADS}/{own}/call-history", headers=REP)).json()
    assert [item["outcome"] for item in history] == ["interested"]
    lost = await client.post(
        f"{CLOSING}/{own}", headers=MANAGER,
        json={"action": "lost", "revision": saved.json()["revision"], "note": "店主明确决定暂不合作"},
    )
    assert lost.status_code == 200, lost.text
    assert not (await queue(client, source_sales_id=11))["items"]
    assert (await queue(client, stage="lost"))["items"][0]["lead_id"] == own


@pytest.mark.asyncio
async def test_source_rep_can_record_explicit_do_not_contact_after_claim(sales_app_client):
    client = sales_app_client
    lead_id = await create_merchant(client, "Stop Calling Salon", "+12125558001")
    await first_result(client, lead_id)
    route = f"{CLOSING}/{lead_id}"
    claimed = await client.post(route, headers=MANAGER, json={"action": "claim", "revision": 0})
    assert claimed.status_code == 200, claimed.text
    await follow_up(client, lead_id, "do_not_contact")
    assert not (await queue(client, stage="all"))["items"]
    lead = (await client.get(f"{LEADS}/{lead_id}", headers=OWNER)).json()
    assert lead["do_not_contact"] is True
    response = await client.post(route, headers=MANAGER, json={
        "action": "follow_up", "revision": claimed.json()["revision"], "note": "约店主再联系",
        "next_follow_up_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
    })
    assert response.status_code in {404, 409}


@pytest.mark.asyncio
async def test_two_closers_cannot_take_the_same_lead_or_bypass_protection(dossier_api):
    client, sessions = dossier_api
    await seed_historical_contacts(sessions)
    owner_queue = partial(queue, client, actor=dossier_auth(1))
    today = (await client.get(f"{LEADS}/workbench/today", headers=REP)).json()["target_date"]
    manual_task = f"{LEADS}/workbench/manual-task/601"
    started = await client.post(manual_task, headers=REP, params={"target_date": today})
    assert started.status_code == 200, started.text
    claim = {"action": "claim", "revision": 0}
    responses = await asyncio.gather(*(
        client.post(f"{CLOSING}/601", headers=dossier_auth(eid), json=claim)
        for eid in (1, 10)
    ))
    assert sorted(r.status_code for r in responses) == [200, 409]
    winner = next(r.json() for r in responses if r.status_code == 200)
    assert (await client.post(manual_task, headers=REP, params={"target_date": today})).status_code == 409
    assert (await client.post(f"{LEADS}/workbench/prepare", headers=REP)).status_code == 200
    today_tasks = (await client.get(f"{LEADS}/workbench/today", headers=REP)).json()["items"]
    assert not any(task["lead"]["id"] == 601 and task["task_status"] == "pending" for task in today_tasks)
    async with sessions() as db:
        db.add(SalesPhoneSuppression(phone_key="+12125550601", blocked=True, reason="另一线索拒绝联系"))
        await db.commit()
    dial_target = f"{CLOSING}/601/dial-target"
    denied = await client.get(dial_target, headers=dossier_auth(winner["closer_id"]))
    assert denied.status_code == 409, denied.text
    assert "+12125550601" not in denied.text
    async with sessions() as db:
        suppression = await db.get(SalesPhoneSuppression, "+12125550601")
        suppression.blocked = False
        lead = await db.get(SalesLeads, 601)
        lead.converted_customer_id = 80
        db.add(SalesPhoneSuppression(phone_key="+12125550602", blocked=True, reason="测试商家明确拒绝来电"))
        await db.commit()
    converted = await owner_queue(stage="won")
    row = next(item for item in converted["items"] if item["lead_id"] == 601)
    assert row["source_sales_id"] == 11
    assert row["closer_id"] == winner["closer_id"]
    assert (await client.get(dial_target, headers=dossier_auth(winner["closer_id"]))).status_code in {403, 409}
    active = await owner_queue()
    assert 601 not in {item["lead_id"] for item in active["items"]}
    protected = next(item for item in active["items"] if item["lead_id"] == 602)
    assert not protected["can_contact"]
    assert (await client.post(f"{CLOSING}/602", headers=dossier_auth(1), json=claim)).status_code == 409


@pytest.mark.asyncio
async def test_owner_explicit_takeover_keeps_source_and_manager_history(dossier_api):
    client, sessions = dossier_api
    await seed_historical_contacts(sessions)
    route = f"{CLOSING}/601"
    manager, owner = dossier_auth(10), dossier_auth(1)
    claimed = await client.post(route, headers=manager, json={"action": "claim", "revision": 0})
    assert claimed.status_code == 200, claimed.text
    original_note = "主管已发方案，需老板确认细节"
    progress = {"action": "follow_up", "revision": claimed.json()["revision"], "note": original_note,
                "next_follow_up_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}
    followed = await client.post(route, headers=manager, json=progress)
    assert followed.status_code == 200, followed.text
    takeover = {"action": "take_over", "revision": followed.json()["revision"]}
    missing_reason = await client.post(route, headers=owner, json=takeover)
    assert missing_reason.status_code in {400, 422}
    reason = "商家希望由老板沟通合同条款"
    ordinary_admin = await client.post(route, headers=dossier_auth(2), json={**takeover, "note": reason})
    assert ordinary_admin.status_code in {403, 409}
    handed = await client.post(route, headers=owner, json={**takeover, "note": reason})
    assert handed.status_code == 200, handed.text
    assert (handed.json()["closer_id"], handed.json()["source_sales_id"]) == (1, 11)
    assert handed.json()["stage"] == "working"
    progress["revision"] = handed.json()["revision"]
    assert (await client.post(route, headers=manager, json=progress)).status_code in {403, 409}
    async with sessions() as db:
        lead = await db.get(SalesLeads, 601)
        assert lead.assigned_sales_id == 11
        events = (await db.scalars(select(SalesInsightEvents).where(SalesInsightEvents.lead_id == 601)
                                   .order_by(SalesInsightEvents.id))).all()
        assert [(event.kind, event.actor_id) for event in events] == [
            ("closing_claim", 10), ("closing_follow_up", 10), ("closing_take_over", 1),
        ]


@pytest.mark.asyncio
async def test_deferred_lead_reminds_its_owner_and_keeps_attribution_after_takeover(dossier_api, monkeypatch):
    client, sessions = dossier_api
    await seed_historical_contacts(sessions)
    clock = datetime(2031, 1, 14, 14, tzinfo=timezone.utc)

    class WorkflowClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.astimezone(tz) if tz else clock.replace(tzinfo=None)

    monkeypatch.setattr(sales_closing_queue, "datetime", WorkflowClock)
    manager, owner = dossier_auth(10), dossier_auth(1)
    route = f"{CLOSING}/601"
    claimed = (await client.post(route, headers=manager, json={"action": "claim", "revision": 0})).json()
    reminder = datetime(2031, 1, 14, 18, tzinfo=timezone.utc)  # Jan 15 at 02:00 Beijing
    pause = {"action": "pause", "revision": claimed["revision"], "note": "现有合同到期前再联系",
             "next_follow_up_at": reminder.isoformat()}
    assert (await client.post(route, headers=manager, json={**pause, "next_follow_up_at": clock.isoformat()})).status_code == 422
    response = await client.post(route, headers=manager, json=pause)
    assert response.status_code == 200, response.text
    paused = response.json()
    assert (paused["stage"], paused["closer_id"], paused["source_sales_id"]) == ("nurturing", 10, 11)
    assert 601 not in {row["lead_id"] for row in (await queue(client, actor=manager))["items"]}
    assert [row["lead_id"] for row in (await queue(client, actor=manager, stage="nurturing", mine=True))["items"]] == [601]
    assert (await client.get(f"{route}/dial-target", headers=manager)).status_code == 409
    assert (await client.post(route, headers=owner, json={"action": "resume", "revision": paused["revision"]})).status_code == 403
    takeover = await client.post(route, headers=owner, json={
        "action": "take_over", "revision": paused["revision"], "note": "老板接手换系统意向",
    })
    assert takeover.status_code == 200, takeover.text
    reassigned = takeover.json()
    assert (reassigned["stage"], reassigned["closer_id"], reassigned["source_sales_id"]) == ("nurturing", 1, 11)
    assert (reassigned["note"], reassigned["next_follow_up_at"]) == (paused["note"], paused["next_follow_up_at"])

    clock += timedelta(hours=3)
    following_today = await queue(client, actor=owner, stage="today", mine=True)
    assert [row["lead_id"] for row in following_today["items"]] == [601]
    assert not (await queue(client, actor=manager, stage="today", mine=True))["items"]
    clock += timedelta(hours=2)
    assert not (await queue(client, actor=owner, stage="today", mine=True))["items"]
    assert [row["lead_id"] for row in (await queue(client, actor=owner, stage="overdue", mine=True))["items"]] == [601]
    resumed = await client.post(route, headers=owner, json={"action": "resume", "revision": reassigned["revision"]})
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["stage"] == "working"
    assert (await client.get(f"{route}/dial-target", headers=owner)).status_code == 200

    async with sessions() as db:
        actions = (await db.scalars(select(SalesInsightEvents.kind).where(SalesInsightEvents.lead_id == 601)
                                   .order_by(SalesInsightEvents.id))).all()
        assert actions == ["closing_claim", "closing_pause", "closing_take_over_paused", "closing_resume"]


@pytest.mark.asyncio
async def test_explicit_stop_contact_at_close_uses_contact_protection(dossier_api):
    client, sessions = dossier_api
    await seed_historical_contacts(sessions)
    manager = dossier_auth(10)
    route = f"{CLOSING}/601"
    claimed = (await client.post(route, headers=manager, json={"action": "claim", "revision": 0})).json()
    stopped = await client.post(route, headers=manager, json={
        "action": "lost", "revision": claimed["revision"], "loss_reason": "do_not_contact",
        "note": "客户明确要求停止电话联系",
    })
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["loss_reason"] == "do_not_contact"
    assert not stopped.json()["can_contact"]
    all_leads = await queue(client, actor=dossier_auth(1), stage="all")
    assert 601 not in {row["lead_id"] for row in all_leads["items"]}
    async with sessions() as db:
        lead = await db.get(SalesLeads, 601)
        suppression = await db.get(SalesPhoneSuppression, lead.phone)
        assert lead.do_not_contact and lead.next_follow_up_at is None
        assert suppression.blocked


@pytest.mark.asyncio
async def test_owner_delegates_paused_closing_to_scoped_manager_without_changing_origination(dossier_api):
    client, sessions = dossier_api
    await seed_historical_contacts(sessions)
    async with sessions() as db:
        db.add(Employees(id=20, name="Elsewhere", role="sales_manager", status="active", user_id="20"))
        await db.commit()
    mine, supervisor = dossier_auth(1), dossier_auth(10)
    route = f"{CLOSING}/601"
    claimed = await client.post(route, headers=mine, json={"action": "claim", "revision": 0})
    assert claimed.status_code == 200, claimed.text
    paused = await client.post(route, headers=mine, json={
        "action": "pause", "revision": claimed.json()["revision"], "note": "约到合同到期前回访",
        "next_follow_up_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
    })
    assert paused.status_code == 200, paused.text
    row = paused.json()
    roster = await client.get(f"{route}/managers", headers=mine)
    assert roster.json() == [{"id": 10, "name": "Manager"}]
    assert (await client.get(f"{route}/managers", headers=supervisor)).status_code == 403
    delegate = {"action": "delegate", "revision": row["revision"], "note": "请主管继续联系", "manager_id": 10}
    assert (await client.post(route, headers=supervisor, json=delegate)).status_code == 403
    assert (await client.post(route, headers=mine, json={**delegate, "manager_id": 20})).status_code == 409
    sent = await client.post(route, headers=mine, json=delegate)
    assert sent.status_code == 200, sent.text
    update = sent.json()
    assert (update["stage"], update["closer_id"], update["source_sales_id"]) == ("nurturing", 10, 11)
    assert (update["note"], update["next_follow_up_at"]) == (row["note"], row["next_follow_up_at"])
    assert update["handoff_note"] == delegate["note"]
    assert [item["lead_id"] for item in (await queue(client, actor=supervisor, mine=True, stage="nurturing"))["items"]] == [601]
    resume = await client.post(route, headers=supervisor, json={"action": "resume", "revision": update["revision"]})
    assert resume.status_code == 200, resume.text

    async with sessions() as db:
        lead = await db.get(SalesLeads, 601)
        assert lead.assigned_sales_id == 11
        event = await db.scalar(select(SalesInsightEvents).where(SalesInsightEvents.id == update["revision"]))
        assert (event.kind, event.actor_id, event.owner_id) == ("closing_delegate_paused", 1, 11)
