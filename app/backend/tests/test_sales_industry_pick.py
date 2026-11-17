import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from backend.main import app
from backend.tests.test_sales_lead_isolation import _auth_headers, sales_app_client
from backend.tests.test_sales_pool_dispatch import db as dispatch_db, merchant, user
from core.database import get_db
from routers.sales_leads import _daily_quota
from services.sales_industry_queue import prepare_industry_batch
from models.employees import Employees
from models.merchant_pool import MerchantPool
from models.sales_call_activities import SalesCallActivities
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_daily_quotas import SalesDailyQuotas
from models.sales_leads import SalesLeads

TODAY = datetime.now(ZoneInfo("Asia/Shanghai")).date()
WORK = "/api/v1/sales-leads/workbench"
SALES = _auth_headers("sales", 11, "Sales A")
ADMIN = _auth_headers("admin", 1, "Admin")


async def pick(client, industry="restaurant", **kwargs):
    return await client.post(f"{WORK}/prepare-industry", headers=SALES,
        params={"industry": industry, "target_date": TODAY.isoformat()}, **kwargs)


def lead(ident, industry="美业", owner=11, **fields):
    return SalesLeads(id=ident, business_name=f"Merchant {ident}", phone=f"+1212555{ident:04d}",
        industry=industry, assigned_sales_id=owner, country="US", **fields)


def task(ident, **fields):
    return SalesDailyDialTasks(id=ident, lead_id=ident, sales_employee_id=11, task_date=TODAY, **fields)


@pytest.mark.asyncio
async def test_full_queue_swaps_only_untouched_and_keeps_owner_and_progress(sales_app_client):
    async for db in app.dependency_overrides[get_db]():
        db.add_all([SalesDailyQuotas(sales_employee_id=11, target_date=TODAY, target_count=7),
            lead(1), task(1, status="completed"),
            lead(2, status="follow_up", next_follow_up_at=datetime.now(timezone.utc)), task(2, queue_category="follow_up"),
            lead(3), task(3, dial_started_at=datetime.now(timezone.utc)),
            lead(4), task(4), lead(5), task(5),
            lead(6), task(6), lead(7), task(7), SalesCallActivities(lead_id=7, sales_employee_id=11, outcome="callback"),
            lead(8, "Chinese Restaurant", owner=None), lead(9, "餐饮", owner=None),
            lead(10, "restaurant", owner=12)])
        await db.commit()
    initial = await sales_app_client.get(f"{WORK}/today", headers=SALES)
    assert [i["lead"]["industry_group"] for i in initial.json()["items"]] == ["beauty"] * 7
    choice = await pick(sales_app_client, json={"preserve_task_ids": [6]})
    assert choice.status_code == 200, choice.text
    assert choice.json()["created"] == choice.json()["replaced"] == 2
    after = (await sales_app_client.get(f"{WORK}/today", headers=SALES)).json()
    assert after["assigned_count"] == 7 and after["completed_count"] == 1
    assert {i["lead"]["id"] for i in after["items"]} == {1, 2, 3, 6, 7, 8, 9}
    repeat = await pick(sales_app_client, json={"preserve_task_ids": [6]})
    assert repeat.json()["created"] == 0
    async for db in app.dependency_overrides[get_db]():
        assert (await db.get(SalesLeads, 5)).assigned_sales_id == 11
        assert (await db.get(SalesDailyDialTasks, 5)).status == "industry_deferred"
        assert (await db.get(SalesLeads, 10)).assigned_sales_id == 12
    manual = await sales_app_client.post(f"{WORK}/manual-task/5", params={"target_date": TODAY}, headers=SALES)
    assert manual.status_code == 200 and manual.json()["task_status"] == "pending"


@pytest.mark.asyncio
async def test_private_raw_sources_and_duplicate_numbers_cannot_block_a_later_eligible_merchant(sales_app_client):
    async for db in app.dependency_overrides[get_db]():
        db.add(Employees(id=20, user_id="external", name="Manager B", role="sales_manager", status="active"))
        def pool(ident, phone, owner, **values):
            return MerchantPool(id=ident, business_name=f"Cafe {ident}", industry="restaurants", country="US",
                                phone=phone, created_by_id=owner, **values)
        db.add_all([pool(1, "+12125556511", 20), pool(2, "+12125556512", None),
            pool(3, "+12125556513", 10, pool_status="archived"),
            pool(4, "+12125556514", 1, business_status="CLOSED"),
            pool(5, "+12125556515", 10), lead(800, "美业", owner=12)])
        for ident in range(6, 86):
            db.add(pool(ident, "(212) 555-6515", 1))
        db.add(pool(86, "+12125556516", 1))
        db.add(pool(87, "+12125550800", 1))
        db.add(lead(810, "餐厅", owner=None, team_manager_id=20))
        await db.commit()
    assert (await pick(sales_app_client)).json()["created"] == 2
    rows = (await sales_app_client.get(f"{WORK}/today", headers=SALES)).json()["items"]
    assert {item["lead"]["merchant_pool_id"] for item in rows} == {5, 86}
    assert all(item["lead"]["industry_group"] == "restaurant" for item in rows)
    assert (await pick(sales_app_client)).json()["created"] == 0
    raw = await sales_app_client.get("/api/v1/merchant-pool", headers=SALES)
    assert raw.status_code == 403
    assert (await sales_app_client.post(f"{WORK}/prepare-industry", headers=ADMIN,
        params={"industry":"restaurant", "target_date":TODAY})).status_code == 403
    assert (await sales_app_client.post(f"{WORK}/prepare-industry", headers=SALES,
        params={"industry":"restaurant", "target_date":TODAY-timedelta(days=1)})).status_code == 400


@pytest.mark.asyncio
async def test_pending_appointments_do_not_fill_first_call_batch_and_cold_picks_stay_bounded(sales_app_client):
    async for db in app.dependency_overrides[get_db]():
        for ident in range(1, 12):
            db.add_all([lead(ident, "餐厅", status="appointment"), task(ident, queue_category="follow_up")])
        for ident in range(21, 36):
            db.add(lead(ident, "餐厅", owner=None))
        await db.commit()
    first = await pick(sales_app_client)
    assert first.status_code == 200, first.text
    assert first.json()["created"] == 10 and first.json()["pending_in_industry"] == 21
    assert (await pick(sales_app_client)).json()["created"] == 0
    remaining = (await sales_app_client.get(f"{WORK}/today", headers=SALES)).json()
    assert remaining["performance"]["attempted"] == remaining["completed_count"] == 0


@pytest.mark.asyncio
async def test_concurrent_sellers_claim_distinct_merchants_and_retries_are_idempotent(dispatch_db):
    dispatch_db.add_all([merchant(ident, industry="餐厅") for ident in range(1, 24)])
    await dispatch_db.commit()
    sessions = dispatch_db.info["sessions"]

    async def claim(employee_id):
        async with sessions() as session:
            return await prepare_industry_batch(session, user("sales", str(employee_id), "Sales"),
                                                "restaurant", TODAY, _daily_quota, set())

    first, second = await asyncio.gather(claim(21), claim(22))
    assert first["created"] == second["created"] == 10
    repeated = await asyncio.gather(claim(21), claim(21))
    assert all(result["created"] == 0 for result in repeated)
    leads = (await dispatch_db.scalars(select(SalesLeads))).all()
    assert len({lead.phone for lead in leads}) == len(leads) == 20
    assert {lead.assigned_sales_id for lead in leads} == {21, 22}


@pytest.mark.asyncio
async def test_zone_stock_and_claim_share_local_hours_identity_and_permissions(sales_app_client, monkeypatch):
    from services import sales_industry_queue
    from models.sales_contact_protection import SalesPhoneSuppression

    class SummerClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 7, 8, 16, 30, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(sales_industry_queue, "datetime", SummerClock)
    day = SummerClock.now(ZoneInfo("Asia/Shanghai")).date()
    async for db in app.dependency_overrides[get_db]():
        def source(ident, state, city, owner=1, phone=None):
            return MerchantPool(id=ident, business_name=f"Test {ident}", phone=phone or f"+1212555{ident:04d}",
                                industry="餐厅", country="US", state=state, city=city, created_by_id=owner)
        db.add_all([source(31, "CO", "Denver"), source(32, "AZ", "Phoenix"), source(33, "NY", "New York"),
                    source(34, "CO", "Denver", phone="(212) 555-0031"), source(35, "CO", "Denver", owner=999),
                    source(36, "CO", "Denver"), source(37, "CA", "Los Angeles"),
                    SalesPhoneSuppression(phone_key="+12125550036", blocked=True, reason="test")])
        await db.commit()
    params = {"industry": "restaurant"}
    assert (await sales_app_client.get(f"{WORK}/industry-stock", params=params, headers=ADMIN)).status_code == 403
    async def read():
        res = await sales_app_client.get(f"{WORK}/industry-stock", params=params, headers=SALES)
        assert res.status_code == 200, res.text
        return {zone["group"]: zone for zone in res.json()["zones"]}
    stock = await read()
    assert stock["mountain"] == {"group":"mountain", "total":2, "in_window":1, "local_times":["09:30", "10:30"]}
    assert stock["pacific"]["total"] == 1 and stock["pacific"]["in_window"] == 0
    async for db in app.dependency_overrides[get_db]():
        assert not (await db.scalars(select(SalesDailyDialTasks))).all()

    async def take(group, window_only=True, size=1):
        res = await sales_app_client.post(f"{WORK}/prepare-industry", headers=SALES, params={
            **params, "target_date":day, "timezone_group":group, "window_only":window_only, "batch_size":size})
        assert res.status_code == 200, res.text
        return res.json()["created"]
    assert await take("pacific") == 0
    assert await take("mountain") == 1
    assert await take("mountain") == 0
    assert (await read())["mountain"]["in_window"] == 0
    snapshot = await sales_app_client.get(f"{WORK}/today", headers=SALES, params={"target_date":day})
    assert snapshot.json()["self_claimed_count"] == 1 and snapshot.json()["completed_count"] == 0
    assert await take("eastern") == 1
    assert await take("pacific", False) == 1
    async for db in app.dependency_overrides[get_db]():
        chosen = (await db.scalars(select(SalesLeads).where(SalesLeads.assigned_sales_id == 11))).all()
        assert {lead.merchant_pool_id for lead in chosen} == {31, 33, 37}
