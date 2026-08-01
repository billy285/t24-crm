import pytest

from backend.tests.test_sales_lead_isolation import _auth_headers, sales_app_client


@pytest.mark.asyncio
async def test_post_call_analysis_and_manager_conversion_keep_lead_history(sales_app_client):
    admin = _auth_headers("admin", 1, "Admin")
    manager = _auth_headers("sales_manager", 10, "Manager A")
    sales = _auth_headers("sales", 11, "Sales A")

    created = await sales_app_client.post(
        "/api/v1/sales-leads",
        headers=admin,
        json={"business_name": "Conversion Cafe", "contact_name": "Owner", "phone": "+16265550100", "address": "1 Main St", "assigned_sales_id": 11},
    )
    assert created.status_code == 201
    lead_id = created.json()["id"]

    workbench = await sales_app_client.get("/api/v1/sales-leads/workbench/today", headers=sales)
    task = next(item for item in workbench.json()["items"] if item["lead"]["id"] == lead_id)
    recorded = await sales_app_client.post(
        f"/api/v1/sales-leads/workbench/tasks/{task['task_id']}/result",
        headers=sales,
        json={"outcome": "interested", "notes": "需要报价，约下周回访", "next_follow_up_at": "2026-08-08T15:00:00+08:00"},
    )
    assert recorded.status_code == 200
    history = await sales_app_client.get(f"/api/v1/sales-leads/{lead_id}/call-history", headers=sales)
    activity_id = history.json()[0]["id"]

    generated = await sales_app_client.post(
        f"/api/v1/sales-leads/call-activities/{activity_id}/ai-analysis",
        headers=sales,
        json={"transcript": "商家表示希望了解报价，预算需要和合伙人讨论，下周可以再联系。"},
    )
    assert generated.status_code == 200
    assert generated.json()["editable"] is True

    blocked = await sales_app_client.post(
        f"/api/v1/sales-leads/{lead_id}/convert-to-customer",
        headers=manager,
        json={"confirmation_notes": "客户确认合作"},
    )
    assert blocked.status_code == 400
    assert blocked.json()["detail"]["message"] == "成交审核尚未完成"

    quote = await sales_app_client.post(
        f"/api/v1/sales-deal-controls/{lead_id}/quotes",
        headers=sales,
        json={"package_name": "基础套餐", "selected_platforms": ["Google"], "billing_mode": "subscription", "payment_method": "stripe", "list_amount": 198, "service_start_date": "2026-07-01", "service_end_date": "2026-08-01"},
    )
    assert quote.status_code == 201
    quote_id = quote.json()["id"]
    approved = await sales_app_client.post(
        f"/api/v1/sales-deal-controls/quotes/{quote_id}/review",
        headers=manager,
        json={"decision": "approved", "review_notes": "价格和交付范围已确认"},
    )
    assert approved.status_code == 200
    handoff = await sales_app_client.put(
        f"/api/v1/sales-deal-controls/{lead_id}/handoff",
        headers=sales,
        json={"quote_id": quote_id, "customer_goal": "提升本地曝光", "key_contacts": "Owner / +16265550100", "operations_owner": "运营 A", "operations_group_created": True, "generate_service_board": True},
    )
    assert handoff.status_code == 200
    deposit = await sales_app_client.post(
        f"/api/v1/sales-deal-controls/{lead_id}/handoff/finance-confirmation",
        headers=manager,
        json={"payment_status": "deposit_paid", "amount_received": 50, "payment_date": "2026-06-28", "payment_reference": "DEP-001"},
    )
    assert deposit.status_code == 200
    assert deposit.json()["finance_payment_confirmed"] is False
    readiness = await sales_app_client.get(f"/api/v1/sales-deal-controls/{lead_id}/readiness", headers=manager)
    assert "已收订金，仍待尾款" in readiness.json()["blockers"]

    confirmed = await sales_app_client.post(
        f"/api/v1/sales-deal-controls/{lead_id}/handoff/finance-confirmation",
        headers=manager,
        json={"payment_status": "paid", "amount_received": 198, "payment_date": "2026-07-01", "payment_reference": "FULL-001"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["finance_payment_confirmed"] is True

    converted = await sales_app_client.post(
        f"/api/v1/sales-leads/{lead_id}/convert-to-customer",
        headers=manager,
        json={"confirmation_notes": "客户确认合作", "generate_service_board": True},
    )
    assert converted.status_code == 200
    assert converted.json()["customer_code"].startswith("C")
    assert converted.json()["deal_id"]
    assert converted.json()["payment_id"]
    assert converted.json()["subscription_id"]
    assert converted.json()["service_progress_id"]

    deals = await sales_app_client.get(
        "/api/v1/entities/deals",
        headers=admin,
        params={"query": '{"customer_id":' + str(converted.json()["customer_id"]) + '}'},
    )
    assert deals.status_code == 200
    assert deals.json()["total"] == 1
    assert deals.json()["items"][0]["package_name"] == "基础套餐"
    assert deals.json()["items"][0]["deal_amount"] == 198

    payments = await sales_app_client.get(
        "/api/v1/entities/payments/all",
        headers=admin,
        params={"query": '{"customer_id":' + str(converted.json()["customer_id"]) + '}'},
    )
    assert payments.status_code == 200
    assert payments.json()["total"] == 1
    assert payments.json()["items"][0]["amount_paid"] == 198
    assert payments.json()["items"][0]["payment_method"] == "stripe"

    duplicate_conversion = await sales_app_client.post(
        f"/api/v1/sales-leads/{lead_id}/convert-to-customer",
        headers=manager,
        json={"confirmation_notes": "再次确认合作"},
    )
    assert duplicate_conversion.status_code == 409

    dashboard = await sales_app_client.get("/api/v1/sales-leads/dashboard/management", headers=manager)
    assert dashboard.status_code == 200
    assert dashboard.json()["metrics"]["converted"] == 1
    assert dashboard.json()["deal_pipeline"]["approved_quotes"] == 1
    assert dashboard.json()["deal_pipeline"]["approved_quote_amount"] == 198
    assert dashboard.json()["deal_pipeline"]["confirmed_received_amount"] == 198
    assert dashboard.json()["owner_attention"]["pending_quotes"] == 0


@pytest.mark.asyncio
async def test_newly_approved_quote_supersedes_previous_approved_quote(sales_app_client):
    admin = _auth_headers("admin", 1, "Admin")
    manager = _auth_headers("sales_manager", 10, "Manager A")
    sales = _auth_headers("sales", 11, "Sales A")
    created = await sales_app_client.post(
        "/api/v1/sales-leads",
        headers=admin,
        json={"business_name": "Versioned Quote Spa", "contact_name": "Owner", "phone": "+12125550199", "assigned_sales_id": 11},
    )
    lead_id = created.json()["id"]

    quote_ids = []
    for package_name, amount in [("基础套餐", 198), ("进阶套餐", 398)]:
        quote = await sales_app_client.post(
            f"/api/v1/sales-deal-controls/{lead_id}/quotes",
            headers=sales,
            json={"package_name": package_name, "selected_platforms": ["Google"], "billing_mode": "manual", "payment_method": "check", "list_amount": amount},
        )
        quote_ids.append(quote.json()["id"])
        approved = await sales_app_client.post(
            f"/api/v1/sales-deal-controls/quotes/{quote.json()['id']}/review",
            headers=manager,
            json={"decision": "approved"},
        )
        assert approved.status_code == 200
        if len(quote_ids) == 1:
            handoff = await sales_app_client.put(
                f"/api/v1/sales-deal-controls/{lead_id}/handoff",
                headers=sales,
                json={"quote_id": quote_ids[0], "customer_goal": "提升曝光", "key_contacts": "Owner", "operations_owner": "运营 A", "operations_group_created": True},
            )
            assert handoff.status_code == 200
            paid = await sales_app_client.post(
                f"/api/v1/sales-deal-controls/{lead_id}/handoff/finance-confirmation",
                headers=manager,
                json={"payment_status": "paid", "amount_received": 198, "payment_date": "2026-07-01"},
            )
            assert paid.status_code == 200

    readiness = await sales_app_client.get(f"/api/v1/sales-deal-controls/{lead_id}/readiness", headers=manager)
    statuses = {item["id"]: item["status"] for item in readiness.json()["quotes"]}
    assert statuses[quote_ids[0]] == "superseded"
    assert statuses[quote_ids[1]] == "approved"
    assert readiness.json()["handoff"]["payment_status"] == "pending"
    assert readiness.json()["handoff"]["finance_payment_confirmed"] is False
