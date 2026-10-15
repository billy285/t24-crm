"""Isolated sale -> customer -> independently verified payment and delivery."""
from datetime import date, datetime, timezone
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.main import app
from core.database import Base, get_db
from models.commissions import CommissionAgreement, CustomerCommissionAttribution, SalesPartner
from models.customer_access_grants import CustomerAccessGrant
from models.customer_contacts import Customer_contacts
from models.customers import Customers
from models.deals import Deals
from models.employees import Employees
from models.finance_profit_closes import MonthlyProfitClose
from models.management_decisions import BusinessLine, CustomerEngagement, ProductCatalog, ProductPlan
from models.payments import Payments
from models.sales_call_activities import SalesCallActivities
from models.sales_deal_handoffs import SalesDealHandoff, SalesDealPlanPolicy
from models.sales_deal_controls import SalesQuoteRequests
from models.sales_dossiers import SalesDossierSummary
from models.sales_lead_enrichments import SalesLeadEnrichment
from models.sales_leads import SalesLeads
from models.subscriptions import Subscriptions
from services.deal_payment_sync import backfill_missing_payments_from_deals
from services.emp_auth import create_access_token
from backend.tests.test_sales_account_acceptance import acceptance_credential, strict_sales_accounts

PREFIX = "/api/v1/sales-deal-handoffs"
ROLES = {1: "super_admin", 11: "sales", 12: "sales", 13: "operations", 14: "operations", 15: "finance", 16: "sales_manager", 17: "admin"}


def headers(actor=11):
    return {"Authorization": "Bearer " + create_access_token({"emp_id": actor, "email": f"{actor}@example.com", "role": ROLES[actor], "name": f"User {actor}"})}


@pytest_asyncio.fixture
async def sale_api(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sale.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        db.add_all([Employees(id=i, user_id=f"u{i}", name=f"User {i}", role=role, status="active", supervisor="User 16") for i, role in ROLES.items()])
        db.add(BusinessLine(id=1, code="managed_service", name="代运营", is_recurring=True, is_active=True))
        await db.flush()
        db.add(ProductCatalog(id=1, business_line_id=1, code="managed", name="代运营产品", billing_kind="recurring", is_active=True))
        await db.flush()
        db.add(ProductPlan(id=1, product_id=1, code="monthly-pro", name="专业套餐", pricing_status="published", standard_price=198, default_currency="USD", default_billing_cycle="monthly", platform_limit=2, scope_type="platforms", is_active=True))
        db.add(SalesDealPlanPolicy(plan_id=1, collection_policy="stripe_auto", revision=1, updated_by_id=1, updated_by_name="User 1"))
        db.add(SalesLeads(id=1, business_name="Synthetic Merchant", contact_name="老板", phone="+12125550111", country="US", assigned_sales_id=11, assigned_sales_name="User 11", notes="售前原始备注"))
        db.add(SalesLeadEnrichment(lead_id=1, contacts=[
            {"id": "owner", "name": "老板", "role": "决策人", "phone": "+12125550112", "email": "owner@example.com", "wechat": "owner-wechat", "verification": "confirmed"},
            {"id": "front", "name": "前台", "role": "前台", "phone": "+12125550113", "email": None, "wechat": None, "verification": "confirmed"}],
            preferred_contact_id="owner", interest_product_ids=[1], need_summary="需要增加预约", best_contact_time="下午三点", verification="confirmed", updated_by_id=11))
        db.add(SalesDossierSummary(lead_id=1, revision=1, payload={"latest_conclusion": "老板已同意合作", "objections": "担心交付周期", "promises": "先建群", "next_step": "运营联系"}, updated_by_id=11))
        db.add(SalesCallActivities(lead_id=1, sales_employee_id=11, sales_employee_name="User 11", outcome="interested", notes="希望先做Google", called_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
        await db.commit()
    async def override():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, sessions
    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


async def draft(client, **updates):
    response = await client.get(PREFIX + "/catalog", headers=headers())
    assert response.status_code == 200, response.text
    plan = response.json()["plans"][0]
    return {"idempotency_key": "synthetic-request-0001", "plan_id": plan["id"], "catalog_token": plan["catalog_token"],
        "selected_platforms": ["Google Business Profile"], "service_start_date": "2026-10-01", "service_end_date": "2026-11-01",
        "collection_method": "stripe_auto", "operations_owner_employee_id": 13, "customer_goal": "增加预约量",
        "handoff_notes": "先安排开户资料", "special_commitments": "每周反馈", "confirmation_notes": "客户已确认标准套餐", **updates}


async def registered(client, **updates):
    response = await client.post(PREFIX + "/leads/1", headers=headers(), json=await draft(client, **updates))
    assert response.status_code == 200, response.text
    return response.json()["handoff"]


def payment(**updates):
    return {"amount_received": 198, "payment_date": "2026-10-02", "currency": "USD", "payment_method": "stripe", "transaction_reference": "SYNTHETIC-RECEIPT-001", **updates}


async def grant(sessions, customer_id, employee_id=13, **updates):
    async with sessions() as db:
        db.add(CustomerAccessGrant(customer_id=customer_id, employee_id=employee_id, access_level="read_only",
            scopes={"basic": "read_only", "contacts": "read_only", "delivery": "read_only", "deals": "read_only"},
            finance_access="none", invitation_source="owner_invitation", invitation_status="active", **updates))
        await db.commit()


@pytest.mark.asyncio
async def test_sales_registers_without_quote_or_payment_and_preserves_all_handoff_sources(sale_api):
    client, sessions = sale_api
    payload = await draft(client)
    first = await client.post(PREFIX + "/leads/1", headers=headers(), json=payload)
    assert first.status_code == 200, first.text
    row = first.json()["handoff"]
    assert "payment_status" not in row and row["operations_access_status"] == "pending"
    assert not row["can_view_customer"] and not row["can_finance_confirm"]
    assert row["source"]["history"][0]["notes"] == "希望先做Google"
    assert row["source"]["summary"]["latest_conclusion"] == "老板已同意合作"
    assert row["source"]["interest_product_ids"] == [1]
    retry = await client.post(PREFIX + "/leads/1", headers=headers(), json=payload)
    assert retry.status_code == 200 and retry.json()["idempotent_replay"]
    assert retry.json()["handoff"]["id"] == row["id"]
    changed = await client.post(PREFIX + "/leads/1", headers=headers(), json={**payload, "customer_goal": "不同目标"})
    assert changed.status_code == 409
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Customers)) == 1
        assert await db.scalar(select(func.count()).select_from(CustomerEngagement)) == 1
        assert await db.scalar(select(func.count()).select_from(CustomerCommissionAttribution)) == 1
        assert await db.scalar(select(func.count()).select_from(CustomerAccessGrant)) == 0
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0
        assert not (await db.get(Deals, row["deal_id"])).is_paid
        subscription = await db.get(Subscriptions, row["subscription_id"])
        assert subscription.status == "pending" and not subscription.auto_renew and subscription.last_payment_date is None
        contacts = (await db.scalars(select(Customer_contacts))).all()
        assert {item.contact_phone for item in contacts} == {"+12125550112", "+12125550113"}
        assert "owner@example.com" in contacts[0].notes and "owner-wechat" in contacts[0].notes
        assert (await db.get(Customers, row["customer_id"])).email == "owner@example.com"
        assert await backfill_missing_payments_from_deals(db) == 0
        assert await backfill_missing_payments_from_deals(db) == 0
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0
    blocked_sync = await client.put(f"/api/v1/entities/deals/{row['deal_id']}", headers=headers(1), json={"is_paid": True})
    assert blocked_sync.status_code == 409, blocked_sync.text
    async with sessions() as db:
        assert not (await db.get(Deals, row["deal_id"])).is_paid
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0


@pytest.mark.asyncio
async def test_fixed_price_rejects_tampering_stale_price_and_foreign_sales(sale_api):
    client, sessions = sale_api
    payload = await draft(client)
    for forged in ({"amount": 1}, {"price": 1}, {"currency": "CNY"}, {"finance_payment_confirmed": True}):
        response = await client.post(PREFIX + "/leads/1", headers=headers(), json={**payload, **forged})
        assert response.status_code == 422
    assert (await client.post(PREFIX + "/leads/1", headers=headers(12), json=payload)).status_code == 404
    async with sessions() as db:
        (await db.get(ProductPlan, 1)).standard_price = 199
        await db.commit()
    assert (await client.post(PREFIX + "/leads/1", headers=headers(), json=payload)).status_code == 409
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Customers)) == 0


@pytest.mark.asyncio
async def test_owner_verifies_actual_full_receipt_once_and_lock_failure_rolls_back(sale_api):
    client, sessions = sale_api
    row = await registered(client)
    url = f"{PREFIX}/{row['id']}/finance-confirmation"
    for actor in (11, 12, 13, 15, 16, 17):
        assert (await client.post(url, headers=headers(actor), json=payment())).status_code == 403
    for invalid in (payment(amount_received=50), payment(currency="CNY"), payment(payment_date="2099-01-01"), payment(payment_date="")):
        assert (await client.post(url, headers=headers(1), json=invalid)).status_code in {400, 422}
    async with sessions() as db:
        db.add(MonthlyProfitClose(year_month="2026-10", status="locked", snapshot_json="{}"))
        await db.commit()
    locked = await client.post(url, headers=headers(1), json=payment())
    assert locked.status_code == 409 and "月结" in locked.text
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0
        assert not (await db.get(Deals, row["deal_id"])).is_paid
        assert (await db.get(SalesDealHandoff, row["id"])).payment_status == "pending"
        close = await db.scalar(select(MonthlyProfitClose))
        close.status = "open"
        await db.commit()
    verified = await client.post(url, headers=headers(1), json=payment())
    assert verified.status_code == 200, verified.text
    replay = await client.post(url, headers=headers(1), json=payment())
    assert replay.status_code == 200 and replay.json()["idempotent_replay"]
    assert (await client.post(url, headers=headers(1), json=payment(transaction_reference="DIFFERENT"))).status_code == 409
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Payments)) == 1
        receipt = await db.scalar(select(Payments))
        assert receipt.amount_paid == 198 and receipt.management_amount == 198 and receipt.stripe_fee_amount == 6.04
        assert receipt.payment_date.date() == date(2026, 10, 2)
        assert (await db.get(Subscriptions, row["subscription_id"])).status == "active"
        assert (await db.get(CustomerEngagement, row["engagement_id"])).status == "active_paid"


@pytest.mark.asyncio
async def test_only_invited_designated_operator_can_receive_and_customer_data_is_filtered(sale_api):
    client, sessions = sale_api
    row = await registered(client)
    url = f"{PREFIX}/{row['id']}/operations-acknowledgment"
    for actor in (1, 11, 12, 13, 14):
        assert (await client.post(url, headers=headers(actor), json={"note": "运营已经核对"})).status_code == 403
    assert (await client.get(PREFIX + "/queue", headers=headers(13))).json()["items"] == []
    await grant(sessions, row["customer_id"])
    summary = await client.get(f"{PREFIX}/customers/{row['customer_id']}", headers=headers(13))
    assert summary.status_code == 200
    item = summary.json()["items"][0]
    assert item["can_operations_ack"] and not item["can_view_history"] and item["history_url"] is None
    for field in ("amount", "currency", "payment_id", "payment_status", "payment_confirmed_at", "payment_confirmed_by_name"):
        assert field not in item
    assert item["source"]["customer_goal"] == "增加预约量"
    assert (await client.post(url, headers=headers(14), json={"note": "其他运营试图代收"})).status_code == 403
    accepted = await client.post(url, headers=headers(13), json={"note": "运营已经核对"})
    assert accepted.status_code == 200 and accepted.json()["handoff"]["operations_status"] == "accepted"
    assert (await client.post(url, headers=headers(13), json={"note": "再次确认不覆盖"})).status_code == 200
    async with sessions() as db:
        grant_row = await db.scalar(select(CustomerAccessGrant))
        grant_row.invitation_status = "revoked"
        await db.commit()
    assert (await client.post(url, headers=headers(13), json={"note": "撤销后尝试接收"})).status_code == 403
    assert (await client.get(f"{PREFIX}/{row['id']}", headers=headers(13))).status_code == 404


@pytest.mark.asyncio
async def test_duplicate_existing_customer_requires_owner_and_preserves_owner_attribution(sale_api):
    client, sessions = sale_api
    async with sessions() as db:
        db.add(Customers(id=99, business_name="Existing Merchant", contact_name="旧联系人", phone="+12125550111", sales_employee_id=12, sales_person="User 12"))
        db.add(CustomerCommissionAttribution(customer_id=99, partner_id=999, effective_from=date(2020, 1, 1), attribution_role="primary", is_active=True, source_note="DO-NOT-CHANGE"))
        await db.commit()
    payload = await draft(client)
    duplicate = await client.post(PREFIX + "/leads/1", headers=headers(), json=payload)
    assert duplicate.status_code == 409 and "Existing Merchant" not in duplicate.text
    assert (await client.post(PREFIX + "/leads/1", headers=headers(), json={**payload, "existing_customer_id": 99})).status_code == 403
    linked = await client.post(PREFIX + "/leads/1", headers=headers(1), json={**payload, "existing_customer_id": 99})
    assert linked.status_code == 200, linked.text
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Customers)) == 1
        assert (await db.get(Customers, 99)).sales_employee_id == 12
        assert await db.scalar(select(func.count()).select_from(Customer_contacts)) == 2
        links = (await db.scalars(select(CustomerCommissionAttribution))).all()
        assert len(links) == 1 and links[0].source_note == "DO-NOT-CHANGE" and links[0].partner_id == 999


@pytest.mark.asyncio
async def test_queue_scope_and_catalog_empty_do_not_guess_prices(sale_api):
    client, sessions = sale_api
    row = await registered(client)
    owner = (await client.get(PREFIX + "/queue", headers=headers(1))).json()
    assert owner["counts"] == {"all": 1, "pending_payment": 1, "pending_operations": 1, "pending_access": 1, "completed": 0}
    assert len((await client.get(PREFIX + "/queue", headers=headers())).json()["items"]) == 1
    assert (await client.get(PREFIX + "/queue", headers=headers(12))).json()["items"] == []
    assert (await client.get(f"{PREFIX}/{row['id']}", headers=headers(12))).status_code == 404
    async with sessions() as db:
        (await db.get(ProductPlan, 1)).pricing_status = "draft"
        await db.commit()
    catalog = (await client.get(PREFIX + "/catalog", headers=headers())).json()
    assert catalog["plans"] == [] and catalog["status"] == "no_published_prices" and not catalog["can_manage_catalog"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "value"), [("standard_price", 198.999), ("standard_price", None),
    ("default_currency", "usd"), ("default_billing_cycle", None), ("is_active", False),
    ("effective_from", date(2099, 1, 1))])
async def test_catalog_never_exposes_incomplete_unpublished_or_invalid_price_versions(sale_api, field, value):
    client, sessions = sale_api
    async with sessions() as db:
        setattr(await db.get(ProductPlan, 1), field, value)
        await db.commit()
    result = await client.get(PREFIX + "/catalog", headers=headers())
    assert result.status_code == 200 and result.json()["plans"] == []


@pytest.mark.parametrize(("line", "name", "expected"), [
    ("managed_service", "专业套餐", "social_media"), ("managed_service", "广告投放", "ads"),
    ("one_time_project", "品牌官网", "website"), ("restaurant_os", "餐饮OS", "restaurant_os"), ("beauty_os", "美业OS", "beauty_os")])
def test_payment_product_vocabulary_preserves_existing_financial_classification(line, name, expected):
    from services.sales_deal_handoffs import _financial_product_type
    from services.deal_payment_sync import infer_payment_income_type
    kind = _financial_product_type({"name": name, "business_line_code": line}, ["Google Ads"])
    assert kind == expected
    assert infer_payment_income_type(kind, name) == {"social_media": "management_fee", "ads": "ads_fee", "website": "website_fee", "restaurant_os": "other_income", "beauty_os": "other_income"}[expected]


@pytest.mark.asyncio
async def test_new_employee_channel_uses_first_service_month_then_existing_fixed_renewal_formula(sale_api):
    client, sessions = sale_api
    async with sessions() as db:
        db.add(SalesPartner(id=50, partner_code="EMP-SYNTHETIC", name="Synthetic employee channel", partner_type="employee",
            employee_id=11, status="active", joined_at=date(2026, 1, 1)))
        await db.flush()
        db.add(CommissionAgreement(partner_id=50, version=1, first_order_rate=.5, renewal_rate=.2,
            calculation_version="service_month_v2", renewal_policy="fixed", activity_decay_json='{"0":1}',
            refund_guard_days=0, effective_from=date(2026, 1, 1), status="active"))
        await db.commit()
    row = await registered(client)
    confirmed = await client.post(f"{PREFIX}/{row['id']}/finance-confirmation", headers=headers(1), json=payment())
    assert confirmed.status_code == 200, confirmed.text
    from services.commissions import preview_payment_commission
    async with sessions() as db:
        link = await db.scalar(select(CustomerCommissionAttribution))
        assert link.commission_mode == "first_month_then_renewal" and link.first_service_start == date(2026, 10, 1)
        receipt = await db.scalar(select(Payments))
        preview = await preview_payment_commission(db, receipt)
        assert preview["issues"] == [] and preview["segments"][0]["entry_type"] == "first_order", preview
        # A later paid service period uses the same immutable agreement's fixed rate.
        renewal = Payments(customer_id=row["customer_id"], customer_name="Synthetic Merchant", income_type="management_fee",
            amount_due=198, amount_paid=198, management_amount=198, currency="USD", payment_date=datetime(2026, 11, 2),
            created_at=datetime(2026, 11, 2), user_id="fixture", engagement_id=row["engagement_id"],
            business_line_id=1, product_id=1, billing_cycle="monthly", coverage_start=datetime(2026, 11, 1), coverage_end=datetime(2026, 12, 1))
        db.add(renewal)
        await db.flush()
        later = await preview_payment_commission(db, renewal)
        assert later["issues"] == [] and later["segments"][0]["entry_type"] == "renewal", later
        assert preview["segments"][0]["contract_rate"] == .5 and later["segments"][0]["contract_rate"] == .2


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["basic", "delivery", "contacts", "followups", "deals"])
async def test_customer_handoff_obeys_each_module_and_never_exposes_financial_receipts(sale_api, scope):
    client, sessions = sale_api
    row = await registered(client)
    async with sessions() as db:
        db.add(CustomerAccessGrant(customer_id=row["customer_id"], employee_id=12, access_level="read_only",
            scopes={scope: "read_only"}, finance_access="none", invitation_source="owner_invitation", invitation_status="active"))
        await db.commit()
    response = await client.get(f"{PREFIX}/customers/{row['customer_id']}", headers=headers(12))
    assert response.status_code == 200
    if scope == "basic":
        assert response.json() == {"items": []}
        return
    item = response.json()["items"][0]
    assert not {"amount", "payment_id", "currency", "payment_status", "payment_confirmed_at", "payment_confirmed_by_name"} & set(item)
    source = item.get("source", {})
    assert ("contacts" in source) == (scope == "contacts")
    assert ("history" in source) == (scope == "followups")
    assert ("customer_goal" in source) == (scope == "delivery")
    assert ("package_name" in item) == (scope in {"deals", "delivery"})
    assert not item["can_view_history"]


@pytest.mark.asyncio
async def test_concurrent_register_and_verify_are_single_effect_and_sales_never_sees_receipt(sale_api):
    import asyncio
    client, sessions = sale_api
    payload = await draft(client)
    first, second = await asyncio.gather(*[client.post(PREFIX + "/leads/1", headers=headers(), json=payload) for _ in range(2)])
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    row = first.json()["handoff"]
    assert row["id"] == second.json()["handoff"]["id"]
    receipts = await asyncio.gather(*[client.post(f"{PREFIX}/{row['id']}/finance-confirmation", headers=headers(1), json=payment()) for _ in range(2)])
    assert [item.status_code for item in receipts] == [200, 200], [item.text for item in receipts]
    sales_view = (await client.get(f"{PREFIX}/{row['id']}", headers=headers())).json()["handoff"]
    assert not {"payment_status", "payment_id", "payment_confirmed_at", "payment_confirmed_by_name"} & set(sales_view)
    assert (await client.get(PREFIX + "/queue", headers=headers())).json()["counts"]["pending_payment"] == 0
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Customers)) == 1
        assert await db.scalar(select(func.count()).select_from(Deals)) == 1
        assert await db.scalar(select(func.count()).select_from(Payments)) == 1


@pytest.mark.asyncio
async def test_unverified_secondary_contact_keeps_raw_evidence_without_blocking_registration(sale_api):
    client, sessions = sale_api
    async with sessions() as db:
        profile = await db.get(SalesLeadEnrichment, 1)
        profile.contacts = [profile.contacts[0], {**profile.contacts[1], "phone": "old-number-unknown"}]
        await db.commit()
    row = await registered(client)
    secondary = row["source"]["contacts"][1]
    assert secondary["phone"] is None and secondary["raw_phone"] == "old-number-unknown" and secondary["verification"] == "pending"
    async with sessions() as db:
        contact = await db.scalar(select(Customer_contacts).where(Customer_contacts.contact_name == "前台"))
        assert contact.contact_phone is None and "old-number-unknown" in contact.notes


@pytest.mark.asyncio
async def test_actual_sales_password_session_can_register_only_owned_merchant_and_no_financial_or_private_access(strict_sales_accounts):
    a = strict_sales_accounts
    async with a.sessions() as db:
        db.add(Employees(id=21, user_id="catalog-ops", name="Synthetic Ops", role="operations", status="active"))
        db.add(BusinessLine(id=1, code="managed_service", name="Synthetic", is_recurring=True, is_active=True))
        await db.flush()
        db.add(ProductCatalog(id=1, business_line_id=1, code="strict-product", name="Synthetic product", billing_kind="recurring", is_active=True))
        await db.flush()
        db.add(ProductPlan(id=1, product_id=1, code="strict-plan", name="专业套餐", pricing_status="published", standard_price=198,
            default_currency="USD", default_billing_cycle="monthly", is_active=True))
        lead = await db.get(SalesLeads, 202)
        lead.contact_name = "Synthetic owner"
        await db.commit()
    response = await a.request("GET", PREFIX + "/catalog")
    await a.request("PUT", PREFIX + "/plan-policies/1", actor=1, json_body={"collection_policy": "stripe_auto"})
    response = await a.request("GET", PREFIX + "/catalog")
    token = response.json()["plans"][0]["catalog_token"]
    payload = {"idempotency_key": "strict-login-request-202", "plan_id": 1, "catalog_token": token,
        "selected_platforms": ["Google Business Profile"], "service_start_date": "2026-10-01", "service_end_date": "2026-11-01",
        "collection_method": "stripe_auto", "operations_owner_employee_id": 21, "customer_goal": "Synthetic goal",
        "confirmation_notes": "Synthetic confirmed sale"}
    await a.request("POST", PREFIX + "/leads/101", expected=404, json_body=payload)
    registered = await a.request("POST", PREFIX + "/leads/202", json_body=payload)
    row = registered.json()["handoff"]
    assert "payment_status" not in row and not row["can_view_customer"] and row["amount"] == 198
    await a.request("POST", f"{PREFIX}/{row['id']}/finance-confirmation", expected=403, json_body=payment())
    await a.request("POST", f"{PREFIX}/{row['id']}/operations-acknowledgment", expected=403, json_body={"note": "Cannot accept"})
    await a.request("GET", "/api/v1/entities/payments/all", expected=403)
    await a.request("GET", "/api/v1/private-workspace", expected=403, private=True)
    async with a.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Payments)) == 1  # Only the fixture's protected old payment.
        assert await db.scalar(select(func.count()).select_from(CustomerAccessGrant)) == 0


@pytest.mark.asyncio
async def test_new_registration_freezes_old_quote_write_routes_but_not_unfinished_legacy(sale_api):
    client, sessions = sale_api
    async with sessions() as db:
        db.add(SalesQuoteRequests(id=70, lead_id=1, package_name="Old proposal", status="submitted", submitted_by_id=11, final_amount=100, list_amount=100))
        db.add(SalesLeads(id=2, business_name="Unfinished legacy", phone="+12125550199", country="US", assigned_sales_id=11, assigned_sales_name="User 11"))
        db.add(SalesQuoteRequests(id=71, lead_id=2, package_name="Unfinished old proposal", status="submitted", submitted_by_id=11, final_amount=100, list_amount=100))
        await db.commit()
    row = await registered(client)
    for method, path, payload in [
        ("POST", "/api/v1/sales-deal-controls/1/quotes", {"package_name": "Attempted old price", "list_amount": 1}),
        ("PUT", "/api/v1/sales-deal-controls/1/handoff", {"customer_goal": "Attempted old handoff"}),
        ("POST", "/api/v1/sales-leads/1/convert-to-customer", {"confirmation_notes": "Attempted old conversion"}),
        ("POST", "/api/v1/sales-deal-controls/quotes/70/review", {"decision": "approved"}),
        ("POST", "/api/v1/sales-deal-controls/1/handoff/finance-confirmation", {"payment_status": "paid", "amount_received": 100}),
    ]:
        response = await client.request(method, path, headers=headers(1), json=payload)
        assert response.status_code == 409, (path, response.text)
    compatible = await client.post("/api/v1/sales-deal-controls/quotes/71/review", headers=headers(1), json={"decision": "approved"})
    assert compatible.status_code == 200
    async with sessions() as db:
        assert (await db.get(SalesQuoteRequests, 70)).status == "submitted"
        assert not (await db.get(Deals, row["deal_id"])).is_paid
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0


@pytest.mark.asyncio
async def test_catalog_policy_is_owner_only_stale_tokens_reject_and_manual_cannot_buy_stripe_price(sale_api):
    client, sessions = sale_api
    old = await draft(client)
    assert (await client.post(PREFIX + "/leads/1", headers=headers(), json={**old, "collection_method": "check"})).status_code == 400
    assert (await client.get(PREFIX + "/plan-policies", headers=headers())).status_code == 403
    assert (await client.put(PREFIX + "/plan-policies/1", headers=headers(), json={"collection_policy": "manual"})).status_code == 403
    assert (await client.put(PREFIX + "/plan-policies/1", headers=headers(1), json={"collection_policy": "manual", "price": 1})).status_code == 422
    policy = await client.put(PREFIX + "/plan-policies/1", headers=headers(1), json={"collection_policy": "manual"})
    assert policy.status_code == 200 and policy.json()["revision"] == 2
    assert (await client.post(PREFIX + "/leads/1", headers=headers(), json=old)).status_code == 409
    fresh = await draft(client, collection_method="check")
    assert (await client.post(PREFIX + "/leads/1", headers=headers(), json={**fresh, "collection_method": "stripe_auto"})).status_code == 400
    accepted = await client.post(PREFIX + "/leads/1", headers=headers(), json=fresh)
    assert accepted.status_code == 200
    row = accepted.json()["handoff"]
    wrong = await client.post(f"{PREFIX}/{row['id']}/finance-confirmation", headers=headers(1), json=payment())
    assert wrong.status_code == 400
    # Later policy changes affect new sales, not the frozen manual agreement.
    await client.put(PREFIX + "/plan-policies/1", headers=headers(1), json={"collection_policy": "stripe_auto"})
    paid = await client.post(f"{PREFIX}/{row['id']}/finance-confirmation", headers=headers(1), json=payment(payment_method="check"))
    assert paid.status_code == 200, paid.text
    async with sessions() as db:
        assert (await db.get(SalesDealHandoff, row["id"])).plan_snapshot["required_collection_method"] == "manual"


@pytest.mark.asyncio
async def test_missing_policy_defaults_manual_and_service_period_is_server_derived(sale_api):
    client, sessions = sale_api
    async with sessions() as db:
        await db.delete(await db.get(SalesDealPlanPolicy, 1))
        await db.commit()
    plans = (await client.get(PREFIX + "/catalog", headers=headers())).json()["plans"]
    assert plans[0]["required_collection_method"] == "manual" and plans[0]["service_period_months"] == 1
    payload = await draft(client, collection_method="check", service_start_date="2028-01-31", service_end_date=None)
    good = await client.post(PREFIX + "/leads/1", headers=headers(), json=payload)
    assert good.status_code == 200 and good.json()["handoff"]["source"]["service_end_date"] == "2028-02-29"


@pytest.mark.parametrize(("start", "cycle", "end"), [
    ("2027-01-31", "monthly", "2027-02-28"), ("2028-01-31", "monthly", "2028-02-29"),
    ("2028-02-29", "annual", "2029-02-28"), ("2026-01-31", "quarterly", "2026-04-30"),
    ("2026-08-31", "semi_annual", "2027-02-28"), ("2026-10-01", "annual", "2027-10-01")])
def test_fixed_period_calendar_math_handles_month_end_and_leap_year(start, cycle, end):
    from services.sales_deal_handoffs import period_end
    assert period_end(date.fromisoformat(start), cycle) == date.fromisoformat(end)


@pytest.mark.asyncio
async def test_wrong_service_span_and_generic_handoff_cannot_override_new_operator_receipt(sale_api):
    client, sessions = sale_api
    bad = await client.post(PREFIX + "/leads/1", headers=headers(), json=await draft(client, service_end_date="2027-10-01"))
    assert bad.status_code == 400
    row = await registered(client)
    for method, path in [("PATCH", f"/api/v1/entities/deals/{row['deal_id']}/handoff"), ("PUT", f"/api/v1/entities/deals/{row['deal_id']}")]:
        response = await client.request(method, path, headers=headers(1), json={"is_handed_over": True})
        assert response.status_code == 409, response.text
    old_finalize = await client.post(f"/api/v1/entities/deals/{row['deal_id']}/finalize", headers=headers(1),
        json={"ensure_subscription": True, "auto_renew": True, "create_service_board": False})
    assert old_finalize.status_code == 200 and not old_finalize.json()["complete"]
    async with sessions() as db:
        assert not (await db.get(Deals, row["deal_id"])).is_handed_over
        assert (await db.get(SalesDealHandoff, row["id"])).operations_status == "pending"
        assert (await db.get(Subscriptions, row["subscription_id"])).status == "pending"
