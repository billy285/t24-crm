from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import select, func
from backend.tests.test_sales_lead_isolation import _auth_headers, sales_app_client
from backend.main import app
from core.database import get_db
from models.sales_leads import SalesLeads
from models.sales_call_activities import SalesCallActivities
from models.ringcentral_call_records import RingCentralCallRecords
from models.sales_intelligence import (
    SalesContactDetails,
    SalesInsightEvents,
    SalesOperatingSettings,
)
from services.sales_intelligence import (
    summarize_lead,
    canonical_calls,
    default_config,
    TZ,
)

ADMIN = _auth_headers("admin", 1, "Admin")
MANAGER = _auth_headers("sales_manager", 10, "Manager A")
A = _auth_headers("sales", 11, "Sales A")
B = _auth_headers("sales", 12, "Sales B")
BASE = "/api/v1/sales-intelligence"


async def create_lead(client, owner=11):
    r = await client.post(
        "/api/v1/sales-leads",
        headers=ADMIN,
        json={
            "business_name": f"Fixture shop {owner}",
            "phone": f"555-01{owner}",
            "assigned_sales_id": owner,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def db_write(callback):
    async for db in app.dependency_overrides[get_db]():
        result = await callback(db)
        await db.commit()
        return result


@pytest.mark.asyncio
async def test_visible_lead_summaries_keep_owner_scope(sales_app_client):
    client = sales_app_client
    own = await create_lead(client, 11)
    other = await create_lead(client, 12)
    params = [("lead_ids", own), ("lead_ids", other), ("limit", 100)]
    scoped = await client.get(f"{BASE}/leads", headers=A, params=params)
    assert scoped.status_code == 200
    assert [x["id"] for x in scoped.json()["items"]] == [own]
    assert scoped.json()["total"] == 1
    admin = await client.get(f"{BASE}/leads", headers=ADMIN, params=params)
    assert {x["id"] for x in admin.json()["items"]} == {own, other}
    missing = await client.get(f"{BASE}/leads", headers=A, params={"lead_ids": other})
    assert missing.json()["items"] == []
    invalid = await client.get(f"{BASE}/leads", headers=A, params={"lead_ids": "invalid"})
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_contact_details_persist_and_no_answer_rolls_back(sales_app_client):
    client = sales_app_client
    lead = await create_lead(client)
    work = (await client.get("/api/v1/sales-leads/workbench/today", headers=A)).json()
    task = next(x for x in work["items"] if x["lead"]["id"] == lead)
    url = f"/api/v1/sales-leads/workbench/tasks/{task['task_id']}/result"
    invalid = await client.post(
        url,
        headers=A,
        json={
            "outcome": "no_answer",
            "contact_details": {"reached_person": "decision_maker"},
        },
    )
    assert invalid.status_code == 422
    assert (await client.get(f"{BASE}/leads/{lead}", headers=A)).json()["records"] == 0
    saved = await client.post(
        url,
        headers=A,
        json={
            "outcome": "interested",
            "notes": "需要预约管理，下周演示",
            "next_follow_up_at": (
                datetime.now(timezone.utc) + timedelta(days=2)
            ).isoformat(),
            "contact_details": {
                "reached_person": "decision_maker",
                "need_summary": "预约管理",
                "next_step": "下周演示",
            },
        },
    )
    assert saved.status_code == 200, saved.text
    dossier = (await client.get(f"{BASE}/leads/{lead}", headers=A)).json()
    assert (
        dossier["calls"],
        dossier["manual_records"],
        dossier["decision_conversations"],
    ) == (0, 1, 1)
    assert dossier["first_interest_record_number"] == 1
    assert dossier["first_interest_call_number"] is None
    assert dossier["potential"] == "priority"
    assert dossier["timeline"][0]["details"]["need_summary"] == "预约管理"
    assert (await client.get(f"{BASE}/leads/{lead}", headers=B)).status_code == 404
    assert (await client.get(f"{BASE}/overview", headers=A)).status_code == 403
    assert (
        await client.get(
            f"{BASE}/leads", headers=_auth_headers("operations", 13, "Ops A")
        )
    ).status_code == 403


def call(
    i,
    session,
    *,
    connected=False,
    account="account",
    activity=None,
    direction="Outbound",
    verified=True,
):
    return NS(
        id=i,
        provider_key=f"p{i}",
        ringcentral_call_id=f"c{i}",
        ringcentral_session_id=session,
        telephony_session_id=None,
        ringcentral_account_id=account,
        sales_employee_id=11,
        sales_employee_name="Sales A",
        lead_id=1,
        activity_id=activity,
        direction=direction,
        sync_status="verified" if verified else "event_received",
        started_at=datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=i),
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        connected=connected,
        duration_seconds=60,
        provider_result="Accepted",
        synced_at=None,
    )


def activity(i, outcome, call_id=None):
    return NS(
        id=i,
        outcome=outcome,
        called_at=datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=i),
        ringcentral_call_id=call_id,
        ringcentral_session_id=None,
        notes="fixture",
        sales_employee_id=11,
        sales_employee_name="Sales A",
        next_follow_up_at=None,
    )


def lead():
    return NS(
        id=1,
        business_name="Fixture",
        phone="555",
        source="Fixture",
        industry="Beauty",
        city="",
        state="",
        assigned_sales_id=11,
        assigned_sales_name="Sales A",
        merchant_pool_id=None,
        converted_customer_id=None,
        status="new",
        is_blacklisted=False,
        do_not_contact=False,
        do_not_contact_reason=None,
        next_follow_up_at=None,
    )


def test_provider_sessions_deduplicate_without_guessing_history():
    calls = [
        call(1, "s1", connected=True, activity=1),
        call(2, "s1", connected=True, activity=1),
        call(3, "s2", connected=True),
        call(4, "s3", verified=False),
        call(5, "s4", direction="Inbound"),
    ]
    rows = [activity(1, "not_interested"), activity(3, "interested", "c3")]
    d = summarize_lead(
        lead(),
        rows,
        calls,
        {},
        None,
        [],
        default_config(),
        datetime(2026, 9, 5, tzinfo=timezone.utc),
    )
    assert (d["calls"], d["connected"], d["records"], d["manual_records"]) == (
        2,
        2,
        2,
        0,
    )
    assert (
        d["first_interest_call_number"] == 2 and d["first_interest_record_number"] == 2
    )
    assert d["connected_rejections"] == 1 and not d["all_connected_rejected"]
    assert d["turned_positive"]
    assert (
        len(
            canonical_calls(
                [call(1, "same", account="a"), call(2, "same", account="b")]
            )
        )
        == 2
    )
    unknown = summarize_lead(lead(), [rows[0]], calls, {}, None, [], default_config())
    assert (
        unknown["connected_without_result"] == 1
        and not unknown["all_connected_rejected"]
    )
    unopened = summarize_lead(
        lead(),
        [],
        [call(i, f"s{i}") for i in range(1, 7)],
        {},
        None,
        [],
        default_config(),
    )
    assert unopened["potential"] == "unknown" and unopened["calls"] == 6
    all_negative = summarize_lead(
        lead(),
        [activity(1, "not_now", "c1"), activity(3, "not_interested", "c3")],
        calls,
        {},
        None,
        [],
        default_config(),
    )
    assert all_negative["all_connected_rejected"]
    assert all_negative["potential"] == "nurture"


@pytest.mark.asyncio
async def test_profile_guards_revision_permissions_and_transfer_history(
    sales_app_client,
):
    c = sales_app_client
    lid = await create_lead(c)
    profile = {
        "revision": 0,
        "pipeline_key": "system",
        "stage_key": "needs",
        "evidence": "商家确认需要改善预约管理",
        "need_summary": "改善预约管理",
        "next_step": "安排演示",
        "next_step_date": (datetime.now(TZ).date() + timedelta(days=2)).isoformat(),
    }
    assert (
        await c.put(
            f"{BASE}/leads/{lid}", headers=A, json={**profile, "stage_key": "won"}
        )
    ).status_code == 422
    assert (
        await c.put(
            f"{BASE}/leads/{lid}",
            headers=A,
            json={
                **profile,
                "potential_override": "priority",
                "override_reason": "测试越权",
            },
        )
    ).status_code == 403
    saved = await c.put(f"{BASE}/leads/{lid}", headers=A, json=profile)
    assert saved.status_code == 200, saved.text
    deadline = (await c.get(f"{BASE}/leads/{lid}", headers=A)).json()["next_follow_up_at"]
    assert datetime.fromisoformat(deadline).astimezone(TZ).date().isoformat() == profile["next_step_date"]
    assert (
        await c.put(f"{BASE}/leads/{lid}", headers=A, json=profile)
    ).status_code == 409
    assert (
        await c.put(
            f"{BASE}/leads/{lid}",
            headers=A,
            json={**profile, "revision": 1, "stage_key": "demo"},
        )
    ).status_code == 422
    assert (
        await c.put(
            f"{BASE}/leads/{lid}",
            headers=MANAGER,
            json={
                **profile,
                "revision": 1,
                "potential_override": "low_fit",
                "override_reason": "需求与当前产品不匹配",
            },
        )
    ).status_code == 200

    async def transfer(db):
        row = await db.get(SalesLeads, lid)
        row.assigned_sales_id = 12
        row.assigned_sales_name = "Sales B"

    await db_write(transfer)
    assert (await c.get(f"{BASE}/leads/{lid}", headers=A)).status_code == 404
    after = await c.get(f"{BASE}/leads/{lid}", headers=B)
    assert after.status_code == 200
    assert after.json()["revision"] == 2 and len(after.json()["timeline"]) == 2
    assert after.json()["potential"] == "low_fit"


@pytest.mark.asyncio
async def test_settings_are_versioned_and_preview_never_writes(sales_app_client):
    c = sales_app_client
    await create_lead(c)
    config = default_config()
    config["weights"] = {"results": 50, "pipeline": 20, "execution": 15, "quality": 15}
    r = await c.post(f"{BASE}/settings/preview", headers=MANAGER, json=config)
    assert r.status_code == 200, r.text
    assert (await c.get(f"{BASE}/settings", headers=ADMIN)).json()["history"] == []
    payload = {
        "config": config,
        "effective_month": datetime.now(TZ).strftime("%Y-%m"),
        "reason": "本月调整销售管理口径",
    }
    assert (
        await c.post(f"{BASE}/settings", headers=MANAGER, json=payload)
    ).status_code == 403
    assert (
        await c.post(
            f"{BASE}/settings",
            headers=ADMIN,
            json={**payload, "effective_month": "2001-01"},
        )
    ).status_code == 422
    assert (
        await c.post(f"{BASE}/settings", headers=ADMIN, json=payload)
    ).status_code == 201
    assert (
        await c.post(f"{BASE}/settings", headers=ADMIN, json=payload)
    ).status_code == 409
    bad = {
        **config,
        "weights": {"results": 99, "pipeline": 0, "execution": 0, "quality": 0},
    }
    assert (
        await c.post(f"{BASE}/settings/preview", headers=ADMIN, json=bad)
    ).status_code == 422
    assert len((await c.get(f"{BASE}/settings", headers=ADMIN)).json()["history"]) == 1


@pytest.mark.asyncio
async def test_targets_saved_views_and_coaching_are_scoped(sales_app_client):
    c = sales_app_client
    month = datetime.now(TZ).strftime("%Y-%m")
    goal = {
        "employee_id": 11,
        "month": month,
        "calls": 100,
        "qualified": 10,
        "demos": 5,
        "wins": 2,
        "reason": "建立月度计划",
    }
    assert (
        await c.post(
            f"{BASE}/targets", headers=MANAGER, json={**goal, "employee_id": 12}
        )
    ).status_code == 403
    assert (
        await c.post(f"{BASE}/targets", headers=MANAGER, json=goal)
    ).status_code == 201
    assert (
        await c.post(f"{BASE}/targets", headers=MANAGER, json=goal)
    ).status_code == 409
    assert (
        await c.post(
            f"{BASE}/targets",
            headers=MANAGER,
            json={**goal, "previous_revision": 1, "calls": 120},
        )
    ).status_code == 201
    assert (
        await c.post(
            f"{BASE}/targets", headers=ADMIN, json={**goal, "month": "2001-01"}
        )
    ).status_code == 422
    t = (await c.get(f"{BASE}/team", headers=A)).json()
    assert (
        len(t["items"]) == 1
        and t["items"][0]["score"] is None
        and t["items"][0]["target"]["calls"] == 120
    )
    assert (
        await c.get(f"{BASE}/team?evidence_employee=12", headers=MANAGER)
    ).status_code == 403
    assert (
        await c.post(
            f"{BASE}/views",
            headers=A,
            json={"name": "优先跟进", "filters": {"potential": "priority"}},
        )
    ).status_code == 201
    assert (await c.get(f"{BASE}/views", headers=B)).json() == []
    coach = await c.post(
        f"{BASE}/coaching",
        headers=MANAGER,
        json={
            "employee_id": 11,
            "action": "复盘演示后明确下一步",
            "due_date": datetime.now(TZ).date().isoformat(),
        },
    )
    assert coach.status_code == 201, coach.text
    tid = coach.json()["id"]
    completion = {"revision": 1, "completion_note": "已复盘三次演示并记录客户反馈"}
    assert (
        await c.put(f"{BASE}/coaching/{tid}", headers=B, json=completion)
    ).status_code == 404
    assert (
        await c.put(f"{BASE}/coaching/{tid}", headers=A, json=completion)
    ).status_code == 200
    assert (
        await c.put(f"{BASE}/coaching/{tid}", headers=A, json=completion)
    ).status_code == 409


@pytest.mark.asyncio
async def test_monthly_evidence_counts_reconcile_and_small_samples_do_not_score(
    sales_app_client,
):
    c = sales_app_client
    lid = await create_lead(c)
    now = datetime.now(timezone.utc)

    async def seed(db):
        a = SalesCallActivities(
            lead_id=lid,
            sales_employee_id=11,
            sales_employee_name="Sales A",
            outcome="interested",
            notes="演示预约",
            called_at=now,
        )
        db.add(a)
        await db.flush()
        db.add(
            SalesContactDetails(
                activity_id=a.id,
                lead_id=lid,
                reached_person="decision_maker",
                need_summary="预约系统",
                next_step="演示",
                recorded_by_id=11,
            )
        )
        for i in range(2):
            db.add(
                RingCentralCallRecords(
                    provider_key=f"fixture-{i}",
                    ringcentral_call_id=f"call-{i}",
                    telephony_session_id="single-session",
                    sales_employee_id=11,
                    lead_id=lid,
                    activity_id=a.id,
                    direction="Outbound",
                    sync_status="verified",
                    connected=True,
                    started_at=now,
                )
            )

    await db_write(seed)
    t = (await c.get(f"{BASE}/team", headers=A)).json()["items"][0]
    assert (t["calls"], t["connected"], t["qualified"], t["quality"]) == (
        1,
        1,
        1,
        100.0,
    )
    assert t["score"] is None
    for metric in ["calls", "qualified", "quality"]:
        evidence = await c.get(
            f"{BASE}/team?evidence_employee=11&metric={metric}", headers=A
        )
        assert evidence.status_code == 200, evidence.text
        assert (
            len(evidence.json()["items"]) == 1
            and evidence.json()["items"][0]["lead_id"] == lid
        )


def test_additive_migration_preserves_all_legacy_tables_and_data(tmp_path):
    import importlib.util
    import sqlite3
    from pathlib import Path
    from sqlalchemy import create_engine, inspect, MetaData
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.autogenerate import compare_metadata
    from core.database import Base

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/e9c7a3f2b106_sales_intelligence.py"
    )
    spec = importlib.util.spec_from_file_location("sales_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path}/migration.db")
    new_names = {
        "sales_operating_settings",
        "sales_lead_profiles",
        "sales_contact_details",
        "sales_insight_events",
        "sales_monthly_targets",
        "sales_coaching_tasks",
        "sales_saved_views",
    }
    legacy = [t for t in Base.metadata.sorted_tables if t.name not in new_names]
    Base.metadata.create_all(engine, tables=legacy)
    with engine.begin() as conn:
        before = conn.exec_driver_sql(
            "select type,name,tbl_name,sql from sqlite_master where name not like 'sqlite_%' order by type,name"
        ).fetchall()
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        after = conn.exec_driver_sql(
            "select type,name,tbl_name,sql from sqlite_master where name not like 'sqlite_%' order by type,name"
        ).fetchall()
        assert [r for r in after if r[2] not in new_names] == before
        assert new_names <= set(inspect(conn).get_table_names())
        metadata = MetaData()
        for name in new_names:
            Base.metadata.tables[name].to_metadata(metadata)
        diffs = compare_metadata(
            MigrationContext.configure(
                conn,
                opts={
                    "include_object": lambda obj, name, type_, reflected, compare_to: type_
                    != "table"
                    or name in new_names
                },
            ),
            metadata,
        )
        assert not diffs, diffs
