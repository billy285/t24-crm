from datetime import datetime, time, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from backend.tests.test_sales_manual_contact import ADMIN, MANAGER, OTHER, ROOT, SALES, manual_contact
from models.employees import Employees
from models.merchant_pool import MerchantPool
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_intelligence import SalesInsightEvents
from models.sales_lead_assignment_logs import SalesLeadAssignmentLogs
from models.sales_leads import SalesLeads
from services.sales_queue_policy import contact_queue_context

PATH = f"{ROOT}/workbench/owned"


@pytest.mark.asyncio
async def test_owned_visibility_receipt_scopes_and_read_only_paging(manual_contact):
    client, sessions, day = manual_contact
    async with sessions.begin() as db:
        db.add(MerchantPool(id=5, business_name="Second store", country="US", phone="+12125550145",
                            industry="restaurant", created_by_id=10))
    submitted = await client.post("/api/v1/merchant-pool/bulk-convert-to-lead", headers=MANAGER,
                                  json={"assigned_sales_id": 11, "merchant_ids": [4, 5, 4]})
    assert submitted.status_code == 200, submitted.text
    receipt = submitted.json()
    assert receipt["assigned_count"] == receipt["converted_count"] == 2
    assert len(receipt["lead_ids"]) == 2 and receipt["today_queued_count"] == 0
    assert receipt["first_lead_id"] == receipt["lead_ids"][0]
    assert "scope=assigned" in receipt["workbench_url"] and "sales_employee_id=11" in receipt["workbench_url"]
    assert (await client.get(PATH, headers=OTHER, params={"sales_employee_id": 11})).status_code == 403
    assert (await client.get(PATH, headers=MANAGER, params={"sales_employee_id": 12})).status_code == 403
    for headers in (SALES, MANAGER, ADMIN):
        exact = (await client.get(PATH, headers=headers, params={
            "sales_employee_id": 11, "lead_id": receipt["first_lead_id"], "limit": 1})).json()
        assert [row["lead"]["id"] for row in exact["items"]] == [receipt["first_lead_id"]]
        assert exact["counts"]["assigned"] == 5 and exact["counts"]["pending"] == 1
        assert exact["items"][0]["task_status"] is None
    other = (await client.get(PATH, headers=OTHER, params={"lead_id": receipt["first_lead_id"]})).json()
    assert other["total"] == other["counts"]["assigned"] == 0

    pages = [(await client.get(PATH, headers=SALES, params={"skip": skip, "limit": 2})).json()
             for skip in (0, 2, 4)]
    assert [p["has_more"] for p in pages] == [True, True, False]
    assert len({item["lead"]["id"] for page in pages for item in page["items"]}) == 5
    searched = (await client.get(PATH, headers=SALES, params={"industry": "restaurant", "q": "555-0145"})).json()
    assert searched["total"] == 1 and searched["items"][0]["lead"]["id"] == receipt["lead_ids"][1]
    assert searched["counts"]["assigned"] == 5
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(SalesDailyDialTasks)) == 1
        logs = (await db.scalars(select(SalesLeadAssignmentLogs))).all()
        assert {(log.lead_id, log.to_sales_employee_id, log.operated_by_id) for log in logs} == {
            (lead_id, 11, 10) for lead_id in receipt["lead_ids"]}


@pytest.mark.asyncio
async def test_now_callable_changes_with_local_clock_preserves_daily_and_all_owned(manual_contact):
    client, sessions, day = manual_contact
    async with sessions.begin() as db:
        for i, state in ((1, "CA"), (2, "NY"), (3, "")):
            lead = await db.get(SalesLeads, i)
            lead.state, lead.industry = state, "餐厅"
        db.add_all([SalesLeads(id=i, assigned_sales_id=11, country="US", state="NY", industry="beauty",
                               business_name=f"Store {i}", phone=f"+121255501{i:02d}") for i in range(4, 11)])
        db.add_all([
            SalesDailyDialTasks(sales_employee_id=11, task_date=day, lead_id=5, status="completed"),
            SalesDailyDialTasks(sales_employee_id=12, task_date=day, lead_id=7, status="pending"),
            SalesDailyDialTasks(sales_employee_id=11, task_date=day, lead_id=8, status="industry_deferred"),
            SalesDailyDialTasks(sales_employee_id=11, task_date=day, lead_id=9, status="cancelled"),
        ])
        await db.flush()
        (await db.get(SalesLeads, 4)).do_not_contact = True
        (await db.get(SalesLeads, 6)).converted_customer_id = 22
        db.add(SalesInsightEvents(kind="closing_claim", lead_id=10, actor_id=10, payload_json="{}"))
    east_open = datetime.combine(day, time(15), tzinfo=timezone.utc)
    with patch("routers.sales_owned_workbench.datetime", wraps=datetime) as clock:
        clock.now.return_value = east_open
        summary = await client.get(PATH, headers=SALES, params={"view": "summary"})
        assert summary.status_code == 200, summary.text
        assert summary.json()["counts"] == {"assigned": 10, "pending": 1, "callable": 2}
        assert summary.json()["items"] == []
        callable_items = (await client.get(PATH, headers=SALES, params={"view": "callable"})).json()["items"]
        assert {item["lead"]["id"] for item in callable_items} == {2, 8}
        assigned = (await client.get(PATH, headers=SALES)).json()["items"]
        by_id = {item["lead"]["id"]: item for item in assigned}
        assert by_id[1]["task_status"] == "pending" and by_id[1]["can_start"]
        assert by_id[1]["contact_queue"]["next_window_at"] is not None
        assert by_id[3]["contact_queue"]["next_window_at"] is None
        assert by_id[3]["can_start"] and "号码待核实" in by_id[3]["unavailable_reason"]
        assert all(not by_id[key]["can_start"] for key in (4, 5, 6, 7, 9, 10))
        clock.now.return_value = datetime.combine(day, time(8), tzinfo=timezone.utc)
        after = (await client.get(PATH, headers=SALES, params={"view": "callable"})).json()
        assert after["items"] == [] and after["counts"] == {"assigned": 10, "pending": 1, "callable": 0}
        earlier = (await client.get(PATH, headers=SALES, params={"target_date": str(day - timedelta(days=1))})).json()
        assert earlier["counts"] == {"assigned": 10, "pending": 0, "callable": 0}
        assert all(not record["can_start"] for record in earlier["items"])


def test_next_window_follows_merchant_day_across_dst():
    east = SalesLeads(country="US", state="NY")
    before_spring_clock_change = datetime(2026, 3, 8, 4, tzinfo=timezone.utc)
    info = contact_queue_context(east, now=before_spring_clock_change)
    assert info["local_time"].endswith("-05:00")
    assert info["next_window_at"] == "2026-03-08T10:00:00-04:00"
    assert contact_queue_context(east, now=before_spring_clock_change, start=2)["next_window_at"] == "2026-03-08T03:00:00-04:00"


@pytest.mark.asyncio
async def test_agreed_callback_enters_callable_at_its_exact_time_and_unknown_zone_uses_beijing(manual_contact):
    client, sessions, _ = manual_contact
    agreed = datetime(2026, 11, 18, 15, 30, tzinfo=timezone.utc)
    async with sessions.begin() as db:
        for lead_id, state in [(1, "NY"), (2, None)]:
            lead = await db.get(SalesLeads, lead_id)
            lead.state, lead.status, lead.next_follow_up_at = state, "follow_up", agreed
    with patch("routers.sales_owned_workbench.datetime", wraps=datetime) as clock:
        clock.now.return_value = agreed - timedelta(seconds=1)
        before = (await client.get(PATH, headers=SALES, params={"view": "callable"})).json()
        assert before["counts"]["callable"] == 0 and before["items"] == []
        assigned = (await client.get(PATH, headers=SALES)).json()
        rows = {item["lead"]["id"]: item for item in assigned["items"]}
        assert rows[1]["contact_queue"]["in_contact_window"] is True and rows[1]["can_start"]
        assert rows[1]["unavailable_reason"] == "约定回访 · 当地 2026-11-18 10:30"
        assert rows[2]["unavailable_reason"] == "约定回访 · 北京时间 2026-11-18 23:30"
        clock.now.return_value = agreed
        due = (await client.get(PATH, headers=SALES, params={"view": "callable"})).json()
        assert due["counts"]["assigned"] == 3 and due["counts"]["callable"] == 1
        assert [item["lead"]["id"] for item in due["items"]] == [1]


@pytest.mark.asyncio
async def test_manager_and_current_owner_agree_after_transfer_even_with_stale_task(manual_contact):
    client, sessions, day = manual_contact
    async with sessions.begin() as db:
        (await db.get(Employees, 12)).supervisor = "Manager"
        (await db.get(SalesLeads, 1)).assigned_sales_id = 12
        (await db.get(SalesLeads, 2)).assigned_sales_id = 12
        db.add(SalesDailyDialTasks(lead_id=1, sales_employee_id=12, task_date=day, status="pending"))
        db.add(SalesDailyDialTasks(lead_id=2, sales_employee_id=11, task_date=day, status="completed"))
    for employee_id, headers, expected in [(11, MANAGER, 0), (11, SALES, 0), (12, MANAGER, 1), (12, OTHER, 1)]:
        params = {"target_date": str(day), "sales_employee_id": employee_id}
        queue = (await client.get(f"{ROOT}/workbench/today", headers=headers, params=params)).json()
        owned = (await client.get(PATH, headers=headers, params={**params, "view": "summary"})).json()
        assert queue["remaining_count"] == owned["counts"]["pending"] == expected
        if employee_id == 11 and headers == MANAGER:
            assert [(item["lead"]["id"], item["task_status"]) for item in queue["items"]] == [(2, "completed")]
