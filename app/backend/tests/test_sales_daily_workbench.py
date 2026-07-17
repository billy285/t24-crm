from datetime import date, timedelta

import pytest

from backend.tests.test_sales_lead_isolation import _auth_headers, sales_app_client


@pytest.mark.asyncio
async def test_daily_workbench_fixed_batch_quota_and_call_history(sales_app_client):
    admin = _auth_headers("admin", 1, "Admin")
    manager = _auth_headers("sales_manager", 10, "Manager A")
    sales = _auth_headers("sales", 11, "Sales A")

    for index in range(101):
        created = await sales_app_client.post(
            "/api/v1/sales-leads",
            headers=admin,
            json={"business_name": f"Daily Cafe {index}", "phone": f"900-{index:03d}", "assigned_sales_id": 11},
        )
        assert created.status_code == 201

    initial = await sales_app_client.get("/api/v1/sales-leads/workbench/today", headers=sales)
    assert initial.status_code == 200
    assert initial.json()["quota"] == 100
    assert initial.json()["assigned_count"] == 100
    assert initial.json()["completed_count"] == 0
    next_follow_up = date.fromisoformat(initial.json()["target_date"]) + timedelta(days=1)

    task = initial.json()["items"][0]
    dial_started = await sales_app_client.post(
        f"/api/v1/sales-leads/workbench/tasks/{task['task_id']}/dial-started",
        headers=sales,
    )
    assert dial_started.status_code == 200
    assert dial_started.json()["phone"] == task["lead"]["phone"]
    result = await sales_app_client.post(
        f"/api/v1/sales-leads/workbench/tasks/{task['task_id']}/result",
        headers=sales,
        json={"outcome": "callback", "notes": "下午回访", "next_follow_up_at": f"{next_follow_up.isoformat()}T09:00:00Z"},
    )
    assert result.status_code == 200
    assert result.json()["used_suggested_follow_up"] is False
    history = await sales_app_client.get(f"/api/v1/sales-leads/{task['lead']['id']}/call-history", headers=sales)
    assert history.status_code == 200
    assert history.json()[0]["outcome"] == "callback"

    after = await sales_app_client.get("/api/v1/sales-leads/workbench/today", headers=sales)
    assert after.status_code == 200
    assert after.json()["assigned_count"] == 100
    assert after.json()["completed_count"] == 1
    assert after.json()["categories"]["callback"] == 1
    assert after.json()["performance"]["attempted"] == 1
    assert after.json()["performance"]["callbacks_due"] == 0

    next_task = after.json()["items"][1]
    no_answer = await sales_app_client.post(
        f"/api/v1/sales-leads/workbench/tasks/{next_task['task_id']}/result",
        headers=sales,
        json={"outcome": "no_answer", "notes": "无人接听"},
    )
    assert no_answer.status_code == 200
    assert no_answer.json()["used_suggested_follow_up"] is True
    assert no_answer.json()["next_follow_up_at"] is not None
    assert "回拨" in no_answer.json()["next_action_label"]

    quota = await sales_app_client.put(
        "/api/v1/sales-leads/workbench/quota",
        headers=manager,
        json={"sales_employee_id": 11, "target_count": 80},
    )
    assert quota.status_code == 200
    assert quota.json()["target_count"] == 80

    blocked = await sales_app_client.get("/api/v1/sales-leads/workbench/today", headers=_auth_headers("sales", 12, "Sales B"))
    assert blocked.status_code == 200
    assert blocked.json()["assigned_count"] == 0


@pytest.mark.asyncio
async def test_interested_lead_can_record_supplemental_follow_up_after_daily_task_completed(sales_app_client):
    admin = _auth_headers("admin", 1, "Admin")
    sales = _auth_headers("sales", 11, "Sales A")

    created = await sales_app_client.post(
        "/api/v1/sales-leads",
        headers=admin,
        json={"business_name": "Repeat Follow Up Cafe", "phone": "555-4400", "assigned_sales_id": 11},
    )
    assert created.status_code == 201
    lead_id = created.json()["id"]

    workbench = await sales_app_client.get("/api/v1/sales-leads/workbench/today", headers=sales)
    task = next(item for item in workbench.json()["items"] if item["lead"]["id"] == lead_id)
    first_call = await sales_app_client.post(
        f"/api/v1/sales-leads/workbench/tasks/{task['task_id']}/result",
        headers=sales,
        json={"outcome": "interested", "notes": "商家愿意了解套餐，希望今天晚些时候再次沟通。"},
    )
    assert first_call.status_code == 200

    before = await sales_app_client.get("/api/v1/sales-leads/workbench/today", headers=sales)
    assert before.json()["completed_count"] == 1

    follow_up = await sales_app_client.post(
        f"/api/v1/sales-leads/{lead_id}/follow-up",
        headers=sales,
        json={"outcome": "appointment", "notes": "已确认周五下午三点线上预约，发送案例后再次确认。"},
    )
    assert follow_up.status_code == 200
    assert follow_up.json()["status"] == "appointment"
    assert "不会重复增加今日任务完成数" in follow_up.json()["message"]

    after = await sales_app_client.get("/api/v1/sales-leads/workbench/today", headers=sales)
    assert after.json()["completed_count"] == 1

    history = await sales_app_client.get(f"/api/v1/sales-leads/{lead_id}/call-history", headers=sales)
    assert history.status_code == 200
    assert [item["outcome"] for item in history.json()] == ["appointment", "interested"]
