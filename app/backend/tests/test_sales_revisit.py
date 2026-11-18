"""Saved and verified contact evidence feeds one actionable row per owned merchant."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete

from backend.tests.test_sales_enrichment import API, auth, enrichment_api
from models.ringcentral_call_records import RingCentralCallRecords
from models.sales_call_activities import SalesCallActivities
from models.sales_contact_protection import SalesPhoneSuppression
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_dossiers import SalesDossierHandoff
from models.sales_intelligence import SalesInsightEvents
from models.sales_leads import SalesLeads

NOW = datetime.now(timezone.utc)
FUTURE = (NOW + timedelta(days=3)).isoformat()
NOTE = {"id": "materials", "label": "先看资料", "text": "周三先发介绍。"}
NEXT = {"id": "front_desk", "label": "前台接听", "text": "前台接听，请午后再联系。"}


def lead(ident, *, owner=11, **changes):
    return SalesLeads(id=ident, business_name=f"测试门店 {ident}", phone=f"+1212555{ident:04d}",
                      country="US", assigned_sales_id=owner, **changes)


def activity(ident, outcome, when=NOW, owner=11, **rest):
    return SalesCallActivities(lead_id=ident, sales_employee_id=owner, outcome=outcome, called_at=when, **rest)


def official(ident, when=NOW, owner=11, **rest):
    fields = dict(lead_id=ident, provider_key=f"call:{ident}:{owner}:{when.timestamp()}", started_at=when,
                  sales_employee_id=owner, direction="Outbound", sync_status="verified", provider_result="No Answer",
                  connected=False)
    return RingCentralCallRecords(**{**fields, **rest})


async def read(client, headers=None, **filters):
    result = await client.get(API, headers=headers or auth(), params={"contacted_only": "true", **filters})
    assert result.status_code == 200, result.text
    return result.json()


def ids(result):
    return [item["id"] for item in result["items"]]


@pytest.mark.asyncio
async def test_save_automatic_multiselect_buckets_notes_and_unanswered_after_interest(enrichment_api):
    client, _ = enrichment_api
    assert (await read(client))["total"] == 0
    payload = {"outcome": "interested", "outcomes": ["interested", "callback"], "quick_notes": [NOTE],
               "notes": "周三先发介绍。", "next_follow_up_at": FUTURE}
    saved = await client.post(f"{API}/workbench/tasks/101/result", headers=auth(), json=payload)
    assert saved.status_code == 200, saved.text
    for group in ["interested", "follow_up"]:
        result = await read(client, revisit_group=group, latest_note_id="materials")
        assert ids(result) == [1] and result["note_options"] == [{"id": "materials", "label": "先看资料"}]
        current = result["items"][0]["last_communication"]
        assert current["outcome_labels"] == ["有意向", "待回访"] and current["source"] == "crm"
        assert current["provider_connected"] is None and current["notes"] == payload["notes"]
    additional = await client.post(f"{API}/1/follow-up", headers=auth(), json={"outcome": "no_answer"})
    assert additional.status_code == 200, additional.text
    assert ids(await read(client, revisit_group="interested")) == ids(await read(client, revisit_group="no_answer")) == [1]
    assert (await read(client, revisit_group="follow_up"))["total"] == 0
    assert ids(await read(client, latest_note_id="materials")) == []
    assert (await read(client))["items"][0]["last_communication"]["outcome_labels"] == ["未接通"]
    ordinary = (await client.get(API, headers=auth())).json()
    assert "last_communication" not in ordinary["items"][0] and "note_options" not in ordinary


@pytest.mark.asyncio
async def test_recent_evidence_scope_no_button_clicks_or_unverified_or_reassigned_history(enrichment_api):
    client, sessions = enrichment_api
    async with sessions() as db:
        db.add_all([lead(i) for i in range(31, 39)])
        db.add_all([official(31), official(32,direction="Inbound"), official(33,sync_status="event_received"),
                    activity(34,"interested", owner=12), official(35,owner=12),
                    official(36,provider_result="Unspecified"), official(37,connected=True,provider_result="Accepted"),
                    activity(2,"callback",owner=12),
                    activity(38, "callback", NOW - timedelta(hours=1), communication_record={
                        "outcomes": ["callback"], "quick_notes": [NOTE]}), official(38)])
        (await db.get(SalesDailyDialTasks,101)).dial_started_at = NOW
        await db.commit()
    personal = await read(client)
    assert set(ids(personal)) == {31, 36, 37, 38}
    assert set(ids(await read(client, revisit_group="no_answer"))) == {31, 38}
    summaries = {row["id"]: row["last_communication"] for row in personal["items"]}
    assert summaries[31]["source"] == "ringcentral" and summaries[31]["provider_connected"] is False
    assert summaries[36]["outcome"] == "dialed" and summaries[36]["provider_connected"] is None
    assert summaries[37]["provider_connected"] is True
    assert summaries[38]["outcome_labels"] == ["未接通"] and summaries[38]["note_at"] < summaries[38]["at"]
    assert ids(await read(client, latest_note_id="materials", revisit_group="follow_up")) == [38]
    assert ids(await read(client,headers=auth("sales",12,"Sales B"))) == [2]
    assert set(ids(await read(client,headers=auth("sales_manager",10,"Manager A")))) == set(ids(personal))
    assert (await client.get(API, headers=auth(), params={"revisit_group":"no_answer"})).status_code == 422


@pytest.mark.asyncio
async def test_protection_before_pagination_and_beijing_dates_and_historical_note_choices(enrichment_api):
    client, sessions = enrichment_api
    midnight = datetime.now(ZoneInfo("Asia/Shanghai")).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
    async with sessions() as db:
        db.add_all([
            lead(40,status="appointment",next_follow_up_at=midnight-timedelta(seconds=1)),
            lead(41,status="follow_up",next_follow_up_at=midnight),
            lead(42,status="interested",next_follow_up_at=midnight+timedelta(days=1)),
            lead(43,cooldown_until=NOW+timedelta(days=2)), lead(44,is_blacklisted=True),
            lead(45,do_not_contact=True), lead(46,converted_customer_id=8), lead(47,status="lost"),
            lead(48), lead(49), lead(50)])
        db.add_all([activity(i,"appointment",NOW,communication_record={"outcomes":["appointment","interested"],
                     "quick_notes":[{**NOTE,"label":"旧标签"}]}) for i in (40,)])
        db.add(activity(41,"callback",NOW+timedelta(seconds=1),communication_record={"outcomes":["callback"],
            "quick_notes":[NOTE,NEXT]}))
        db.add_all([activity(i,"interested") for i in range(42,51)])
        db.add(SalesPhoneSuppression(phone_key="+12125550048",reason="保护",blocked=True,source_lead_id=48))
        db.add(SalesInsightEvents(lead_id=49,kind="closing_claim",actor_id=10,owner_id=11,payload_json="{}"))
        db.add(SalesDossierHandoff(lead_id=50,to_sales_id=11,from_sales_id=12,status="pending",
                                   summary={}, note="交接", created_by_id=12))
        await db.commit()
    result = await read(client,skip=1,limit=1)
    assert result["total"] == 3 and ids(result) == [41]
    assert {n["id"]:n["label"] for n in result["note_options"]} == {"materials":"先看资料","front_desk":"前台接听"}
    assert ids(await read(client,due_range="today")) == [41]
    assert ids(await read(client,due_range="overdue")) == [40]
    assert ids(await read(client,latest_note_id="materials")) == [40,41]
    assert ids(await read(client,revisit_group="appointment")) == [40]
    assert set(ids(await read(client,revisit_group="interested"))) == {40,42}


@pytest.mark.asyncio
async def test_official_call_without_saved_result_requires_daily_task_if_present(enrichment_api):
    client,sessions = enrichment_api
    async with sessions() as db:
        db.add(official(1))
        await db.commit()
    assert (await read(client))["items"][0]["last_communication"]["pending_task_id"] == 101
    body={"outcome":"callback","next_follow_up_at":FUTURE,"notes":"明天午后联系"}
    assert (await client.post(f"{API}/1/follow-up",headers=auth(),json=body)).status_code==400
    async with sessions() as db:
        await db.execute(delete(SalesDailyDialTasks).where(SalesDailyDialTasks.id==101))
        await db.commit()
    assert (await read(client))["items"][0]["last_communication"]["pending_task_id"] is None
    assert (await client.post(f"{API}/1/follow-up",headers=auth(),json=body)).status_code==200
    assert (await read(client,revisit_group="follow_up"))["items"][0]["last_communication"]["notes"]==body["notes"]
