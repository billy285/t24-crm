from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from backend.main import app
from backend.tests.test_merchant_imports import imports_client, auth, preview, GOOD
from backend.tests.test_sales_lead_isolation import sales_app_client, _auth_headers
from core.database import get_db
from models.customers import Customers
from models.deals import Deals
from models.payments import Payments
from models.subscriptions import Subscriptions
from models.sales_leads import SalesLeads


async def financial_snapshot(maker):
    async with maker() as db:
        result = {}
        for model in (Deals, Payments, Subscriptions, Customers):
            omitted = {"needs_group", "is_handed_over", "is_transferred_ops", "notes"} if model is Deals else set()
            result[model.__tablename__] = [
                {column.name: getattr(row, column.name) for column in model.__table__.columns if column.name not in omitted}
                for row in (await db.scalars(select(model).order_by(model.id))).all()
            ]
        return result


@pytest.mark.asyncio
@pytest.mark.parametrize("linked_payment", [False, True])
async def test_handoff_patch_preserves_all_financial_values_and_links(imports_client, linked_payment):
    client, maker = imports_client
    async with maker() as db:
        db.add(Customers(id=91, business_name="交接测试客户", contact_name="负责人", phone="+12125550123", status="active", sales_employee_id=10))
        db.add(Deals(id=81, customer_id=91, customer_name="交接测试客户", product_type="website", package_name="官网",
                     deal_amount=299.50, is_paid=True, billing_cycle="monthly", source_payment_id=71 if linked_payment else None,
                     deal_date=datetime(2026, 1, 5), service_start_date=datetime(2026, 1, 1), service_end_date=datetime(2026, 2, 1)))
        if linked_payment:
            db.add(Payments(id=71, source_deal_id=81, customer_id=91, amount_due=299.50, amount_paid=289.50,
                            stripe_fee_amount=9.70, net_amount=279.80, management_amount=289.50, ads_recharge_amount=0,
                            user_id="1", payment_date=datetime(2026, 1, 6), transaction_reference="preserve-this-reference"))
        db.add(Subscriptions(id=61, customer_id=91, deal_id=81, package_name="官网", package_price=299.50,
                             auto_renew=True, last_payment_date=datetime(2026, 1, 6), status="active"))
        await db.commit()
    before = await financial_snapshot(maker)
    response = await client.patch("/api/v1/entities/deals/81/handoff", headers=auth("admin", 1),
                                  json={"needs_group": True, "is_handed_over": True, "is_transferred_ops": False, "notes": "交给运营核对素材"})
    assert response.status_code == 200, response.text
    assert response.json()["notes"] == "交给运营核对素材"
    assert response.json()["is_handed_over"] is True
    assert await financial_snapshot(maker) == before
    # A retry changes no financial records and creates no missing payment.
    assert (await client.patch("/api/v1/entities/deals/81/handoff", headers=auth("admin", 1), json={"notes": "交给运营核对素材"})).status_code == 200
    assert await financial_snapshot(maker) == before
    for forbidden in ({"deal_amount": 1}, {"is_paid": False}, {"customer_id": 99}, {"source_payment_id": 99}):
        denied = await client.patch("/api/v1/entities/deals/81/handoff", headers=auth("admin", 1), json=forbidden)
        assert denied.status_code == 422, denied.text
    assert await financial_snapshot(maker) == before
    for role in ("sales", "sales_manager", "operations"):
        denied = await client.patch("/api/v1/entities/deals/81/handoff", headers=auth(role, 10), json={"notes": "不能放宽角色"})
        assert denied.status_code == 403


@pytest.mark.asyncio
async def test_batch_filter_returns_only_authorized_receipt_and_real_pagination(imports_client):
    client, _ = imports_client
    first = await preview(client, [GOOD, ["Second", "+12125550124", "", "New York, NY, US", "Maps"]])
    await client.post(f"/api/v1/merchant-imports/{first['id']}/confirm", headers=auth())
    other = await preview(client, [["Outside batch", "+12125550125", "", "New York, NY, US", "Maps"]])
    await client.post(f"/api/v1/merchant-imports/{other['id']}/confirm", headers=auth())
    url = f"/api/v1/merchant-pool?batch_id={first['id']}&limit=1"
    first_page = await client.get(url, headers=auth())
    second_page = await client.get(url + "&skip=1", headers=auth())
    assert first_page.status_code == second_page.status_code == 200
    assert first_page.json()["total"] == second_page.json()["total"] == 2
    assert {first_page.json()["items"][0]["business_name"], second_page.json()["items"][0]["business_name"]} == {GOOD[0], "Second"}
    assert (await client.get(url, headers=auth("sales_manager", 20))).status_code in {403, 404}
    assert (await client.get(url, headers=auth("admin", 1))).json()["total"] == 2
    uncommitted = await preview(client, [["Draft only", "+12125550126", "", "New York, NY, US", "Maps"]])
    assert (await client.get(f"/api/v1/merchant-pool?batch_id={uncommitted['id']}", headers=auth())).status_code == 409
    await client.post(f"/api/v1/merchant-imports/{first['id']}/revert", headers=auth())
    assert (await client.get(url, headers=auth())).status_code == 409


@pytest.mark.asyncio
async def test_due_range_uses_beijing_boundaries_complete_totals_and_sales_scope(sales_app_client):
    start = datetime.now(ZoneInfo("Asia/Shanghai")).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
    async for db in app.dependency_overrides[get_db]():
        db.add_all([
            SalesLeads(business_name=name, phone=f"+1212555{1000+i}", assigned_sales_id=owner, status="follow_up",
                       next_follow_up_at=callback, do_not_contact=protected, is_blacklisted=False)
            for i, (name, callback, owner, protected) in enumerate([
                ("Yesterday", start-timedelta(microseconds=1), 11, False),
                ("Midnight", start, 11, False),
                ("Before tomorrow", start+timedelta(days=1)-timedelta(microseconds=1), 11, False),
                ("Tomorrow", start+timedelta(days=1), 11, False),
                ("Other sales", start, 12, False),
                ("Protected", start, 11, True),
            ])
        ])
        await db.commit()
    headers = _auth_headers("sales", 11, "Sales A")
    today = await sales_app_client.get("/api/v1/sales-leads?due_range=today&limit=1", headers=headers)
    later = await sales_app_client.get("/api/v1/sales-leads?due_range=today&limit=1&skip=1", headers=headers)
    assert today.status_code == later.status_code == 200
    assert today.json()["total"] == later.json()["total"] == 2
    assert {today.json()["items"][0]["business_name"], later.json()["items"][0]["business_name"]} == {"Midnight", "Before tomorrow"}
    overdue = await sales_app_client.get("/api/v1/sales-leads?due_range=overdue", headers=headers)
    assert [row["business_name"] for row in overdue.json()["items"]] == ["Yesterday"]
    assert (await sales_app_client.get("/api/v1/sales-leads?due_range=all", headers=headers)).status_code == 422
    all_rows = await sales_app_client.get("/api/v1/sales-leads", headers=headers)
    assert all_rows.json()["total"] == 5  # Filters remain read-only and keep original scope.
