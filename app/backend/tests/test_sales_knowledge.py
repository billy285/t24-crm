import pytest

from backend.tests.test_sales_lead_isolation import _auth_headers, sales_app_client


@pytest.mark.asyncio
async def test_sales_knowledge_separates_sales_reading_from_manager_maintenance(sales_app_client):
    sales = _auth_headers("sales", 11, "Sales A")
    manager = _auth_headers("sales_manager", 10, "Manager A")

    initial = await sales_app_client.get("/api/v1/sales-knowledge/articles", headers=sales)
    assert initial.status_code == 200
    assert any(item["title"] == "客户怎么付款？" for item in initial.json()["items"])

    draft = await sales_app_client.post(
        "/api/v1/sales-knowledge/articles?publish_now=false",
        headers=manager,
        json={
            "category": "其他",
            "title": "经理内部草稿",
            "customer_question": "客户问一个新问题",
            "standard_answer": "先由主管确认后回复。",
            "action_steps": ["核对现有资料", "提交主管确认"],
            "tags": ["草稿"],
        },
    )
    assert draft.status_code == 201

    sales_after = await sales_app_client.get("/api/v1/sales-knowledge/articles", headers=sales)
    assert "经理内部草稿" not in [item["title"] for item in sales_after.json()["items"]]

    manager_all = await sales_app_client.get(
        "/api/v1/sales-knowledge/articles?include_all=true",
        headers=manager,
    )
    assert "经理内部草稿" in [item["title"] for item in manager_all.json()["items"]]

    forbidden = await sales_app_client.post(
        "/api/v1/sales-knowledge/articles",
        headers=sales,
        json={"category": "其他", "title": "越权", "standard_answer": "不应创建"},
    )
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_sales_can_submit_question_and_manager_can_close_it(sales_app_client):
    sales = _auth_headers("sales", 11, "Sales A")
    manager = _auth_headers("sales_manager", 10, "Manager A")

    submitted = await sales_app_client.post(
        "/api/v1/sales-knowledge/questions",
        headers=sales,
        json={
            "question": "广告费用是否包含在代运营套餐中？",
            "context": "客户正在比较进阶版和专业版。",
        },
    )
    assert submitted.status_code == 201

    listed = await sales_app_client.get("/api/v1/sales-knowledge/questions", headers=manager)
    assert listed.status_code == 200
    item = next(entry for entry in listed.json()["items"] if entry["id"] == submitted.json()["id"])
    assert item["submitted_by_name"] == "Sales A"

    resolved = await sales_app_client.post(
        f"/api/v1/sales-knowledge/questions/{submitted.json()['id']}/resolve",
        headers=manager,
        json={},
    )
    assert resolved.status_code == 200
