"""One communication record drives exactly one follow-up action and one history row."""
import asyncio
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, func, inspect, select

from backend.tests.test_sales_enrichment import API, auth, enrichment_api
from models.sales_call_activities import SalesCallActivities
from models.sales_contact_protection import SalesPhoneSuppression
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_leads import SalesLeads

RESULT = f"{API}/workbench/tasks/101/result"
EXISTING = {"id": "provider", "label": "现用系统", "text": "门店已有点餐系统。"}
NEXT = "2027-01-20T03:00:00Z"


@pytest.mark.asyncio
async def test_compatible_selections_preserve_snapshots_with_one_qualified_record(enrichment_api):
    client, sessions = enrichment_api
    payload = {"outcome": "appointment", "outcomes": ["existing_provider", "interested", "callback", "appointment"],
               "notes": "门店已有点餐系统。周三和店主演示。", "quick_notes": [EXISTING], "next_follow_up_at": NEXT}
    assert (await client.post(RESULT, headers=auth("sales", 12, "Sales B"), json=payload)).status_code in {403, 404}
    result = await client.post(RESULT, headers=auth(), json=payload)
    assert result.status_code == 200, result.text
    lead = result.json()["lead"]
    assert lead["status"] == "appointment" and lead["assigned_sales_id"] == 11 and not lead["cooldown_until"]
    assert (await client.post(RESULT, headers=auth(), json=payload)).status_code == 400
    history = (await client.get(f"{API}/1/call-history", headers=auth())).json()
    assert len(history) == 1 and history[0]["outcome"] == "appointment"
    assert history[0]["outcomes"] == payload["outcomes"] and history[0]["quick_notes"] == [EXISTING]
    assert history[0]["notes"] == payload["notes"]
    async with sessions() as db:
        assert (await db.get(SalesDailyDialTasks, 101)).completed_activity_id == history[0]["id"]
    queue = (await client.get(f"{API}/workbench/today", headers=auth())).json()
    assert queue["completed_count"] == 1
    assert queue["performance"]["attempted"] == queue["performance"]["interested"] == queue["performance"]["appointments"] == 1


@pytest.mark.asyncio
async def test_invalid_combinations_roll_back_and_only_explicit_opt_out_blocks(enrichment_api):
    client, sessions = enrichment_api
    reminder = {"id": "do_not_contact", "label": "老板自定义备注", "text": "尚未明确要求禁止再联系。"}
    for primary, outcomes in (
        ("no_answer", ["no_answer", "interested"]),
        ("appointment", ["appointment", "not_now"]),
        ("do_not_contact", ["do_not_contact", "callback"]),
        ("existing_provider", ["existing_provider", "callback"]),
        ("callback", ["callback", "callback"]),
    ):
        response = await client.post(RESULT, headers=auth(), json={"outcome": primary, "outcomes": outcomes})
        assert response.status_code == 422
    assert (await client.post(RESULT, headers=auth(), json={
        "outcome": "callback", "outcomes": ["existing_provider", "callback"], "quick_notes": [EXISTING]})).status_code == 400
    async with sessions() as db:
        assert (await db.get(SalesDailyDialTasks, 101)).status == "pending"
        assert await db.scalar(select(func.count()).select_from(SalesCallActivities)) == 0
    result = await client.post(RESULT, headers=auth(), json={
        "outcome": "callback", "outcomes": ["callback", "existing_provider"], "quick_notes": [reminder],
        "notes": reminder["text"], "next_follow_up_at": NEXT})
    assert result.status_code == 200 and not result.json()["lead"]["do_not_contact"]
    result = await client.post(f"{API}/1/follow-up", headers=auth(), json={
        "outcome": "do_not_contact", "outcomes": ["do_not_contact"], "notes": "老板要求停止联系此店。"})
    assert result.status_code == 200 and result.json()["lead"]["do_not_contact"]
    async with sessions() as db:
        assert (await db.get(SalesPhoneSuppression, "+12125550111")).blocked


@pytest.mark.asyncio
async def test_historical_result_and_concurrent_supplemental_retry(enrichment_api):
    client, sessions = enrichment_api
    assert (await client.post(RESULT, headers=auth(), json={"outcome": "no_answer"})).status_code == 200
    payload = {"outcome": "callback", "outcomes": ["not_now", "callback", "existing_provider"],
               "quick_notes": [EXISTING], "submission_id": str(uuid4()), "notes": "下月再沟通。",
               "next_follow_up_at": NEXT}
    results = await asyncio.gather(*(client.post(f"{API}/1/follow-up", headers=auth(), json=payload) for _ in range(2)))
    assert [result.status_code for result in results] == [200, 200]
    assert sorted(bool(result.json().get("replayed")) for result in results) == [False, True]
    assert results[0].json()["next_follow_up_at"] == results[1].json()["next_follow_up_at"]
    conflict = await client.post(f"{API}/1/follow-up", headers=auth(), json={**payload, "notes": "与已保存的内容不同"})
    assert conflict.status_code == 409
    history = (await client.get(f"{API}/1/call-history", headers=auth())).json()
    assert [event["outcome"] for event in history] == ["callback", "no_answer"]
    assert history[1]["outcomes"] == ["no_answer"] and history[1]["quick_notes"] == []
    assert history[0]["outcomes"] == payload["outcomes"] and history[0]["quick_notes"] == [EXISTING]
    async with sessions() as db:
        lead = await db.get(SalesLeads, 1)
        assert lead.assigned_sales_id == 11 and lead.cooldown_until is None
        assert lead.next_follow_up_at.replace(tzinfo=timezone.utc) == datetime.fromisoformat(NEXT)


@pytest.mark.asyncio
async def test_retry_after_cooldown_returns_only_own_receipt(enrichment_api):
    client, sessions = enrichment_api
    assert (await client.post(RESULT, headers=auth(), json={"outcome": "no_answer"})).status_code == 200
    payload = {"outcome": "not_now", "outcomes": ["not_now", "existing_provider"], "submission_id": str(uuid4())}
    path = f"{API}/1/follow-up"
    first = await client.post(path, headers=auth(), json=payload)
    assert first.status_code == 200 and first.json()["lead"]["assigned_sales_id"] is None
    replay = await client.post(path, headers=auth(), json=payload)
    assert replay.status_code == 200 and replay.json()["replayed"] and "lead" not in replay.json()
    assert replay.json()["next_follow_up_at"] == first.json()["next_follow_up_at"]
    assert (await client.post(path, headers=auth("sales", 12, "Sales B"), json=payload)).status_code == 404
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(SalesCallActivities)) == 2
        assert (await db.get(SalesLeads, 1)).rotation_count == 1


@pytest.mark.asyncio
async def test_quick_notes_alone_count_as_work_but_not_as_a_connection(enrichment_api):
    client, _ = enrichment_api
    record = {"outcome": "recorded", "outcomes": [], "quick_notes": [EXISTING]}
    assert (await client.post(RESULT, headers=auth(), json={**record, "quick_notes": []})).status_code == 422
    assert (await client.post(RESULT, headers=auth(), json={**record, "outcomes": ["appointment"]})).status_code == 422
    assert (await client.post(RESULT, headers=auth(), json={**record, "next_follow_up_at": NEXT})).status_code == 400
    stop = {**EXISTING, "id": "do_not_contact"}
    assert (await client.post(RESULT, headers=auth(), json={**record, "quick_notes": [stop]})).status_code == 400
    saved = await client.post(RESULT, headers=auth(), json=record)
    assert saved.status_code == 200, saved.text
    lead = saved.json()["lead"]
    assert lead["status"] == "contacted" and lead["assigned_sales_id"] == 11
    assert not lead["next_follow_up_at"] and not lead["do_not_contact"]
    history = (await client.get(f"{API}/1/call-history", headers=auth())).json()
    assert len(history) == 1 and history[0]["outcome_label"] == "已记录沟通" and history[0]["outcomes"] == []
    assert history[0]["quick_notes"] == [EXISTING]
    queue = (await client.get(f"{API}/workbench/today", headers=auth())).json()
    assert queue["completed_count"] == queue["performance"]["attempted"] == 1
    assert queue["performance"]["connected"] == queue["performance"]["interested"] == queue["performance"]["appointments"] == 0


@pytest.mark.asyncio
async def test_fact_only_follow_up_keeps_the_prior_appointment_and_sales_evidence(enrichment_api):
    client, _ = enrichment_api
    first = await client.post(RESULT, headers=auth(), json={
        "outcome": "appointment", "notes": "约好门店演示", "next_follow_up_at": NEXT})
    assert first.status_code == 200
    more = await client.post(f"{API}/1/follow-up", headers=auth(), json={
        "outcome": "recorded", "outcomes": [], "quick_notes": [EXISTING]})
    assert more.status_code == 200, more.text
    before = first.json()["lead"]
    after = more.json()["lead"]
    for key in ("status", "next_follow_up_at", "assigned_sales_id", "cooldown_until", "automation_state",
                "contact_attempt_count", "last_recycle_reason", "do_not_contact"):
        assert before[key] == after[key]
    dossier = (await client.get("/api/v1/sales-intelligence/leads/1", headers=auth())).json()
    assert dossier["potential"] == "priority" and dossier["connected"] == 0
    assert any(event["label"] == "已记录沟通" and event["quick_notes"] == [EXISTING] for event in dossier["timeline"])


def test_migration_keeps_historical_data_and_indexes():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/p18f9a3c0453_sales_call_selections.py"
    spec = spec_from_file_location("sales_call_selections_migration", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    with create_engine("sqlite://").begin() as db:
        db.exec_driver_sql("CREATE TABLE sales_call_activities (id INTEGER PRIMARY KEY, lead_id INTEGER, outcome TEXT, notes TEXT)")
        db.exec_driver_sql("CREATE INDEX call_lead ON sales_call_activities(lead_id)")
        db.exec_driver_sql("INSERT INTO sales_call_activities VALUES (1, 8, 'no_answer', '首次联系')")
        before = inspect(db).get_indexes("sales_call_activities")
        with Operations.context(MigrationContext.configure(db)):
            migration.upgrade()
        assert db.exec_driver_sql("SELECT * FROM sales_call_activities").one() == (1, 8, "no_answer", "首次联系", None)
        assert inspect(db).get_indexes("sales_call_activities") == before
        column = inspect(db).get_columns("sales_call_activities")[-1]
        assert column["name"] == "communication_record" and column["nullable"]
