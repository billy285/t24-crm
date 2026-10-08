from datetime import datetime, timezone
import pytest
from sqlalchemy import select, func
from backend.main import app
from backend.tests.test_sales_lead_isolation import _auth_headers, sales_app_client
from core.database import get_db
from models.sales_daily_dial_tasks import SalesDailyDialTasks
from models.sales_lead_assignment_logs import SalesLeadAssignmentLogs
from models.sales_leads import SalesLeads

async def db_count(model):
    async for db in app.dependency_overrides[get_db]():
        return await db.scalar(select(func.count()).select_from(model))

@pytest.mark.asyncio
async def test_read_workbench_has_no_assignment_side_effects_and_prepare_is_explicit(sales_app_client):
    admin = _auth_headers("admin", 1, "Admin")
    sales = _auth_headers("sales", 11, "Sales A")
    created = await sales_app_client.post("/api/v1/sales-leads", headers=admin,
        json={"business_name":"Read-only dashboard","phone":"+12125550124"})
    assert created.status_code == 201
    for _ in range(2):
        response = await sales_app_client.get("/api/v1/sales-leads/workbench/today", headers=sales)
        assert response.status_code == 200 and response.json()["assigned_count"] == 0
    assert await db_count(SalesDailyDialTasks) == 0
    assert await db_count(SalesLeadAssignmentLogs) == 0
    lead = await sales_app_client.get(f"/api/v1/sales-leads/{created.json()['id']}", headers=admin)
    assert lead.json()["assigned_sales_id"] is None
    assert (await sales_app_client.post("/api/v1/sales-leads/workbench/prepare", headers=sales)).status_code == 200
    assert (await sales_app_client.post("/api/v1/sales-leads/workbench/prepare", headers=sales)).json()["created"] == 0
    assert await db_count(SalesDailyDialTasks) == 1
    denied = await sales_app_client.post("/api/v1/sales-leads/workbench/prepare?sales_employee_id=12", headers=sales)
    assert denied.status_code == 403

@pytest.mark.asyncio
@pytest.mark.parametrize("via_form", [False, True])
async def test_transfer_moves_pending_task_and_preserves_original_dial_evidence(sales_app_client, via_form):
    admin = _auth_headers("admin", 1, "Admin")
    sales_a = _auth_headers("sales", 11, "Sales A")
    sales_b = _auth_headers("sales", 12, "Sales B")
    created = await sales_app_client.post("/api/v1/sales-leads", headers=admin,
        json={"business_name":"Transfer pending","phone":"+12125550125","assigned_sales_id":11})
    lead_id=created.json()["id"]
    await sales_app_client.post("/api/v1/sales-leads/workbench/prepare", headers=sales_a)
    task=(await sales_app_client.get("/api/v1/sales-leads/workbench/today", headers=sales_a)).json()["items"][0]
    dial = await sales_app_client.post(f"/api/v1/sales-leads/workbench/tasks/{task['task_id']}/dial-started", headers=sales_a)
    assert dial.status_code == 200
    if via_form:
        moved=await sales_app_client.put(f"/api/v1/sales-leads/{lead_id}", headers=admin,json={"assigned_sales_id":12})
    else:
        moved=await sales_app_client.post(f"/api/v1/sales-leads/{lead_id}/recovery/reassign", headers=admin,json={"assigned_sales_id":12,"reason":"客户需要新负责人"})
    assert moved.status_code == 200
    assert (await sales_app_client.get("/api/v1/sales-leads/workbench/today", headers=sales_a)).json()["items"] == []
    target=(await sales_app_client.get("/api/v1/sales-leads/workbench/today", headers=sales_b)).json()["items"]
    assert len(target) == 1 and target[0]["lead"]["id"] == lead_id
    async for db in app.dependency_overrides[get_db]():
        old=await db.get(SalesDailyDialTasks,task["task_id"])
        assert old.status == "cancelled" and old.sales_employee_id == 11 and old.dial_started_at is not None
    late = await sales_app_client.post(f"/api/v1/sales-leads/workbench/tasks/{task['task_id']}/result", headers=sales_a,json={"outcome":"no_answer","notes":"旧队列不能提交"})
    assert late.status_code == 400
    assert await db_count(SalesLeadAssignmentLogs) >= 1

@pytest.mark.asyncio
async def test_completed_call_remains_with_original_sales_after_transfer(sales_app_client):
    admin=_auth_headers("admin",1,"Admin"); sales=_auth_headers("sales",11,"Sales A")
    lead=(await sales_app_client.post("/api/v1/sales-leads",headers=admin,json={"business_name":"Completed transfer","phone":"+12125550126","assigned_sales_id":11})).json()
    await sales_app_client.post("/api/v1/sales-leads/workbench/prepare",headers=sales)
    task=(await sales_app_client.get("/api/v1/sales-leads/workbench/today",headers=sales)).json()["items"][0]
    assert (await sales_app_client.post(f"/api/v1/sales-leads/workbench/tasks/{task['task_id']}/result",headers=sales,json={"outcome":"interested","notes":"客户有需求","next_follow_up_at":"2026-10-10T02:00:00Z"})).status_code == 200
    assert (await sales_app_client.post(f"/api/v1/sales-leads/{lead['id']}/recovery/reassign",headers=admin,json={"assigned_sales_id":12,"reason":"运营要求转交","confirm_protected_transfer":True})).status_code == 200
    async for db in app.dependency_overrides[get_db]():
        old=await db.get(SalesDailyDialTasks,task["task_id"])
        assert old.status == "completed" and old.sales_employee_id == 11 and old.completed_activity_id
    history=(await sales_app_client.get(f"/api/v1/sales-leads/{lead['id']}/call-history",headers=admin)).json()
    assert history[0]["sales_employee_name"] == "Sales A"

@pytest.mark.asyncio
async def test_canonical_phone_duplicate_search_and_unchanged_legacy_preservation(sales_app_client):
    admin=_auth_headers("admin",1,"Admin")
    original=(await sales_app_client.post("/api/v1/sales-leads",headers=admin,json={"business_name":"Phone canonical","phone":"(212) 555-0127 ext. 9","country":"US"})).json()
    duplicate=await sales_app_client.post("/api/v1/sales-leads",headers=admin,json={"business_name":"Duplicate","phone":"+12125550127"})
    assert duplicate.status_code == 409
    found=(await sales_app_client.get("/api/v1/sales-leads?search=12125550127",headers=admin)).json()
    assert [row["id"] for row in found["items"]] == [original["id"]]
    async for db in app.dependency_overrides[get_db]():
        legacy=SalesLeads(business_name="Legacy incomplete",phone="555-0000",country=None,created_by_id=1)
        db.add(legacy);await db.commit();legacy_id=legacy.id
    edit=await sales_app_client.put(f"/api/v1/sales-leads/{legacy_id}",headers=admin,json={"notes":"仅更新摘要","phone":"555-0000","country":None})
    assert edit.status_code == 200 and edit.json()["phone"] == "555-0000"
    invalid=await sales_app_client.put(f"/api/v1/sales-leads/{legacy_id}",headers=admin,json={"phone":"2125550128 / 2125550129"})
    assert invalid.status_code == 422

@pytest.mark.asyncio
@pytest.mark.parametrize("target_id", [11, 12])
async def test_reclaim_then_assign_restores_cancelled_daily_work_without_deleting_history(sales_app_client, target_id):
    admin=_auth_headers("admin",1,"Admin"); sales=_auth_headers("sales",11,"Sales A")
    created=await sales_app_client.post("/api/v1/sales-leads",headers=admin,json={"business_name":"Reclaim then assign","phone":"+12125550129","assigned_sales_id":11})
    lead_id=created.json()["id"]
    await sales_app_client.post("/api/v1/sales-leads/workbench/prepare",headers=sales)
    old=(await sales_app_client.get("/api/v1/sales-leads/workbench/today",headers=sales)).json()["items"][0]
    assert (await sales_app_client.put(f"/api/v1/sales-leads/{lead_id}",headers=admin,json={"assigned_sales_id":None})).status_code == 200
    assert (await sales_app_client.put(f"/api/v1/sales-leads/{lead_id}",headers=admin,json={"assigned_sales_id":target_id})).status_code == 200
    target_headers=_auth_headers("sales",target_id,"Sales A" if target_id == 11 else "Sales B")
    items=(await sales_app_client.get("/api/v1/sales-leads/workbench/today",headers=target_headers)).json()["items"]
    assert len(items) == 1 and items[0]["lead"]["id"] == lead_id and items[0]["task_status"] == "pending"
    assert await db_count(SalesDailyDialTasks) == (1 if target_id == 11 else 2)

@pytest.mark.asyncio
async def test_next_day_followup_near_midnight_not_queued_on_previous_business_day(sales_app_client):
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    admin=_auth_headers("admin",1,"Admin"); sales=_auth_headers("sales",11,"Sales A")
    next_day=datetime.now(ZoneInfo("Asia/Shanghai")).date()+timedelta(days=1)
    followup=f"{next_day}T00:30:00+08:00"
    created=await sales_app_client.post("/api/v1/sales-leads",headers=admin,json={"business_name":"Tomorrow midnight","phone":"+12125550130","assigned_sales_id":11,"status":"follow_up","next_follow_up_at":followup})
    assert created.status_code == 201
    prepared=await sales_app_client.post("/api/v1/sales-leads/workbench/prepare",headers=sales)
    assert prepared.status_code == 200 and prepared.json()["created"] == 0
