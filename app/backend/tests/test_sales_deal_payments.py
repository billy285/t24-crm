"""Real isolated API regression: external evidence never becomes a receipt itself."""
import hashlib
import hmac
import json
import time
from datetime import date

import pytest
from sqlalchemy import func, select

from backend.tests.test_sales_catalog_handoffs import PREFIX, draft, grant, headers, payment, registered, sale_api
from models.customer_access_grants import CustomerAccessGrant
from models.deals import Deals
from models.finance_profit_closes import MonthlyProfitClose
from models.management_decisions import CustomerEngagement, ProductPlan
from models.payments import Payments
from models.sales_deal_handoffs import SalesDealHandoff
from models.sales_deal_payments import SalesPaymentRequest, SalesReceiptEvidence, SalesStripeEvent, SalesStripeObservation
from models.sales_dossiers import SalesDossierGrant
from models.sales_leads import SalesLeads
from models.subscriptions import Subscriptions
from services import sales_deal_payments as service
from services.sales_payment_catalog import APPROVED_LINKS, approved_link

PAYMENTS = "/api/v1/sales-deal-payments"
SECRET = "whsec_SYNTHETIC_ONLY_not_a_real_stripe_secret"


async def sale_with_link(client, sessions):
    async with sessions() as db:
        (await db.get(ProductPlan, 1)).code = "t24-managed-basic-stripe-auto-monthly-202610"
        await db.commit()
    handoff = await registered(client)
    response = await client.post(f"{PAYMENTS}/{handoff['id']}/request", headers=headers())
    assert response.status_code == 200, response.text
    return handoff, response.json()["payment_request"]


def event(request, *, event_id="evt_synthetic001", session_id="cs_live_synthetic001", kind="checkout.session.completed", at=None, **changes):
    at = int(time.time()) if at is None else at
    link = next(row for row in APPROVED_LINKS if row["url"] == request["url"].split("?")[0])
    obj = {"id": session_id, "object": "checkout.session", "mode": "subscription", "livemode": True,
        "created": at - 60, "client_reference_id": request["reference"], "payment_link": link["payment_link_id"],
        "amount_subtotal": 19800, "amount_total": 21533, "total_details": {"amount_tax": 1733, "amount_discount": 0, "amount_shipping": 0},
        "currency": "usd", "payment_status": "paid", "subscription": "sub_synthetic001", "invoice": "in_synthetic001",
        "customer_details": {"business_name": "Synthetic Buyer LLC", "name": "Synthetic Payer", "email": "payer@example.com"}, **changes}
    return {"id": event_id, "object": "event", "type": kind, "livemode": True, "created": at, "data": {"object": obj}}


def signed(payload, *, secret=SECRET, timestamp=None):
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = int(time.time()) if timestamp is None else timestamp
    signature = hmac.new(secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
    return body, {"stripe-signature": f"t={timestamp},v1={signature}", "Content-Type": "application/json"}


async def deliver(client, payload, **kwargs):
    body, hdrs = signed(payload, **kwargs)
    return await client.post(PAYMENTS + "/webhook", content=body, headers=hdrs)


def taxed_receipt(**updates):
    return {**payment(), "service_amount": "198.00", "tax_amount": "17.33", "fee_amount": "6.50",
        "gross_amount": "215.33", "net_amount": "208.83", **updates}


def test_catalog_requires_complete_approved_identity_and_exact_cents():
    assert len(APPROVED_LINKS) == 12 and len({item["url"] for item in APPROVED_LINKS}) == 12
    for item in APPROVED_LINKS:
        plan = {"plan_code": item["plan_code"], "standard_price": str(item["amount_minor"] / 100),
            "default_currency": item["currency"], "default_billing_cycle": item["billing_cycle"], "required_collection_method": "stripe_auto"}
        assert approved_link(plan) == item
        for altered in ({"plan_code": item["plan_code"].upper()}, {"standard_price": "0.01"},
                        {"default_currency": "CNY"}, {"default_billing_cycle": "one_time"},
                        {"required_collection_method": "manual"}, {"standard_price": "198.001"}):
            assert approved_link({**plan, **altered}) is None
    assert approved_link({"name": "基础版", "standard_price": 198}) is None


@pytest.mark.asyncio
async def test_link_snapshot_idempotence_no_finance_grants_and_reassignment_revokes_sender(sale_api):
    client, sessions = sale_api
    handoff, request = await sale_with_link(client, sessions)
    assert request["url"].endswith("client_reference_id=" + request["reference"])
    assert len(request["reference"]) == 47 and request["amount"] == 198
    repeated = await client.post(f"{PAYMENTS}/{handoff['id']}/request", headers=headers())
    assert repeated.json()["payment_request"]["url"] == request["url"]
    for actor in (12, 13, 15, 16, 17):
        response = await client.post(f"{PAYMENTS}/{handoff['id']}/request", headers=headers(actor))
        assert response.status_code in {403, 404}, response.text
        assert request["reference"] not in response.text
    async with sessions() as db:
        db.add(SalesDossierGrant(lead_id=1, employee_id=12, access="collaborate", status="active", revision=1, invited_by_id=1))
        await db.commit()
    assert (await client.post(f"{PAYMENTS}/{handoff['id']}/request", headers=headers(12))).status_code == 404
    async with sessions() as db:
        # Changing current catalog price cannot silently alter the frozen request.
        (await db.get(ProductPlan, 1)).standard_price = 199
        assert await db.scalar(select(func.count()).select_from(SalesPaymentRequest)) == 1
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0
        assert await db.scalar(select(func.count()).select_from(CustomerAccessGrant)) == 0
        lead = await db.get(SalesLeads, 1)
        lead.assigned_sales_id, lead.assigned_sales_name = 12, "User 12"
        await db.commit()
    assert (await client.post(f"{PAYMENTS}/{handoff['id']}/request", headers=headers())).status_code == 404
    assert (await client.get(f"{PAYMENTS}/{handoff['id']}/request", headers=headers())).status_code == 404
    owner = await client.get(f"{PAYMENTS}/{handoff['id']}/request", headers=headers(1))
    assert owner.json()["payment_request"]["amount"] == 198
    assert request["reference"] in owner.text


@pytest.mark.asyncio
async def test_unmapped_plan_or_forged_price_never_gets_fallback_link(sale_api):
    client, sessions = sale_api
    handoff = await registered(client)
    response = await client.post(f"{PAYMENTS}/{handoff['id']}/request", headers=headers())
    assert response.status_code == 409
    assert not (await client.get(f"{PREFIX}/{handoff['id']}", headers=headers())).json()["handoff"]["can_request_payment"]
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(SalesPaymentRequest)) == 0


@pytest.mark.asyncio
async def test_signed_callback_only_observes_deduplicates_and_preserves_paid_on_late_events(sale_api, monkeypatch):
    client, sessions = sale_api
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET", SECRET)
    handoff, request = await sale_with_link(client, sessions)
    paid = event(request)
    assert (await deliver(client, paid)).status_code == 200
    assert (await deliver(client, paid)).status_code == 200
    at = paid["created"]
    for index, kind in enumerate(("checkout.session.async_payment_failed", "checkout.session.expired", "checkout.session.completed")):
        late = event(request, event_id=f"evt_late{index}", kind=kind, at=at + index + 1, payment_status="unpaid")
        assert (await deliver(client, late)).status_code == 200
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(SalesStripeObservation)) == 1
        assert await db.scalar(select(func.count()).select_from(SalesStripeEvent)) == 4
        observed = await db.scalar(select(SalesStripeObservation))
        assert observed.status == "paid_observed" and observed.tax_minor == 1733
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0
        assert await db.scalar(select(func.count()).select_from(CustomerAccessGrant)) == 0
        assert not (await db.get(Deals, handoff["deal_id"])).is_paid
        assert (await db.get(Subscriptions, handoff["subscription_id"])).status == "pending"
        assert (await db.get(CustomerEngagement, handoff["engagement_id"])).status == "pending_setup"
    for actor in (11, 12, 13, 15, 16, 17):
        hidden = await client.get(f"{PAYMENTS}/{handoff['id']}/observations", headers=headers(actor))
        assert hidden.status_code == 403 and "payer@example.com" not in hidden.text
    owner = await client.get(f"{PAYMENTS}/{handoff['id']}/observations", headers=headers(1))
    assert owner.status_code == 200 and owner.json()["items"][0]["gross_amount"] == 215.33
    assert "payer@example.com" in owner.text and owner.json()["duplicate_warnings"]


@pytest.mark.asyncio
async def test_bad_signature_old_timestamp_wrong_mode_reference_link_and_size_fail_closed(sale_api, monkeypatch):
    client, sessions = sale_api
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET", SECRET)
    handoff, request = await sale_with_link(client, sessions)
    valid = event(request)
    assert (await deliver(client, valid, secret="whsec_not_the_correct_secret")).status_code == 400
    assert (await deliver(client, valid, timestamp=int(time.time()) - 301)).status_code == 400
    body, hdrs = signed(valid)
    assert (await client.post(PAYMENTS + "/webhook", content=body + b" ", headers=hdrs)).status_code == 400
    assert (await client.post(PAYMENTS + "/webhook", content=b"x" * (service.MAX_BODY_BYTES + 1), headers=hdrs)).status_code == 413
    for changed in ({"client_reference_id": "t24_" + "a" * 43}, {"payment_link": "plink_other"}, {"livemode": False}, {"mode": "payment"}):
        response = await deliver(client, event(request, **changed))
        assert response.status_code == 200 and response.json() == {"received": True}
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(SalesStripeObservation)) == 0
    monkeypatch.delenv("T24_SALES_STRIPE_WEBHOOK_SECRET")
    assert (await deliver(client, valid)).status_code == 503


def test_secret_file_private_absolute_regular_only(tmp_path, monkeypatch):
    monkeypatch.delenv("T24_SALES_STRIPE_WEBHOOK_SECRET", raising=False)
    secret_path = tmp_path / "secret"
    secret_path.write_text(SECRET + "\n")
    secret_path.chmod(0o600)
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET_FILE", str(secret_path))
    assert service.webhook_secret() == SECRET
    secret_path.chmod(0o644)
    assert service.webhook_secret() is None
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET_FILE", "relative/secret")
    assert service.webhook_secret() is None
    secret_path.chmod(0o600)
    alias = tmp_path / "alias"
    alias.symlink_to(secret_path)
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET_FILE", str(alias))
    assert service.webhook_secret() is None


@pytest.mark.asyncio
async def test_tax_evidence_owner_only_preserves_original_base_financial_formula_and_lock(sale_api, monkeypatch):
    client, sessions = sale_api
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET", SECRET)
    handoff, request = await sale_with_link(client, sessions)
    assert (await deliver(client, event(request))).status_code == 200
    observation = (await client.get(f"{PAYMENTS}/{handoff['id']}/observations", headers=headers(1))).json()["items"][0]
    receipt = taxed_receipt(stripe_observation_id=observation["id"])
    url = f"{PREFIX}/{handoff['id']}/finance-confirmation"
    for actor in (11, 12, 13, 15, 16, 17):
        assert (await client.post(url, headers=headers(actor), json=receipt)).status_code == 403
    async with sessions() as db:
        db.add(MonthlyProfitClose(year_month="2026-10", status="locked", snapshot_json="{}"))
        await db.commit()
    assert (await client.post(url, headers=headers(1), json=receipt)).status_code == 409
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(SalesReceiptEvidence)) == 0
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0
        close = await db.scalar(select(MonthlyProfitClose))
        close.status = "open"
        await db.commit()
    result = await client.post(url, headers=headers(1), json=receipt)
    assert result.status_code == 200, result.text
    assert (await client.post(url, headers=headers(1), json=receipt)).json()["idempotent_replay"]
    assert (await client.post(url, headers=headers(1), json={**receipt, "fee_amount": "7.00", "net_amount": "208.33"})).status_code == 409
    async with sessions() as db:
        evidence = await db.scalar(select(SalesReceiptEvidence))
        assert (evidence.service_minor, evidence.tax_minor, evidence.fee_minor, evidence.gross_minor, evidence.net_minor) == (19800, 1733, 650, 21533, 20883)
        posted = await db.scalar(select(Payments))
        assert posted.amount_paid == 198 and posted.amount_due == 198 and posted.management_amount == 198
        assert posted.stripe_fee_amount == 6.04  # existing formula, not independently observed 6.50
        assert posted.payment_date.date() == date(2026, 10, 2)
        assert await db.scalar(select(func.count()).select_from(CustomerAccessGrant)) == 0
    assert (await client.post(f"{PAYMENTS}/{handoff['id']}/request", headers=headers())).status_code == 409
    owner = (await client.get(f"{PAYMENTS}/{handoff['id']}/observations", headers=headers(1))).json()
    assert owner["receipt_evidence"]["accounting_amount"] == 198 and owner["receipt_evidence"]["tax_amount"] == 17.33


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [
    {"service_amount": "215.33"}, {"gross_amount": "198.00"}, {"net_amount": "200.00"},
    {"tax_amount": "-1"}, {"fee_amount": "300"}, {"tax_amount": "17.331"},
    {"amount_received": "215.33"}, {"stripe_observation_id": 999}, {"tax_amount": None},
])
async def test_tax_mismatch_partial_or_forged_observation_never_posts(sale_api, invalid):
    client, sessions = sale_api
    handoff, request = await sale_with_link(client, sessions)
    result = await client.post(f"{PREFIX}/{handoff['id']}/finance-confirmation", headers=headers(1), json=taxed_receipt(**invalid))
    assert result.status_code in {400, 422}, result.text
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0
        assert await db.scalar(select(func.count()).select_from(SalesReceiptEvidence)) == 0


@pytest.mark.asyncio
async def test_payment_processing_and_mismatch_observations_cannot_be_confirmed(sale_api, monkeypatch):
    client, sessions = sale_api
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET", SECRET)
    handoff, request = await sale_with_link(client, sessions)
    pending = event(request, payment_status="unpaid")
    assert (await deliver(client, pending)).status_code == 200
    observation = (await client.get(f"{PAYMENTS}/{handoff['id']}/observations", headers=headers(1))).json()["items"][0]
    assert observation["status"] == "processing"
    result = await client.post(f"{PREFIX}/{handoff['id']}/finance-confirmation", headers=headers(1), json=taxed_receipt(stripe_observation_id=observation["id"]))
    assert result.status_code == 409
    mismatch = event(request, event_id="evt_mismatch", session_id="cs_live_mismatch", amount_subtotal=19900, amount_total=21633)
    assert (await deliver(client, mismatch)).status_code == 200
    items = (await client.get(f"{PAYMENTS}/{handoff['id']}/observations", headers=headers(1))).json()["items"]
    assert items[0]["status"] == "needs_review" and "service_amount_mismatch" in items[0]["match_issues"]
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0


@pytest.mark.asyncio
async def test_existing_active_customer_warning_no_old_subscription_changes(sale_api):
    client, sessions = sale_api
    handoff, request = await sale_with_link(client, sessions)
    async with sessions() as db:
        db.add(Subscriptions(customer_id=handoff["customer_id"], package_name="Old unchanged plan", package_price=99, status="active", auto_renew=True))
        await db.commit()
    response = await client.get(f"{PAYMENTS}/{handoff['id']}/request", headers=headers())
    assert response.json()["payment_request"]["duplicate_warnings"]
    assert "Stripe 全部历史" in response.text
    async with sessions() as db:
        old = await db.scalar(select(Subscriptions).where(Subscriptions.package_name == "Old unchanged plan"))
        assert old.package_price == 99 and old.auto_renew and old.status == "active"


@pytest.mark.asyncio
async def test_session_or_invoice_cross_request_never_auto_relinks_or_posts(sale_api, monkeypatch):
    client, sessions = sale_api
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET", SECRET)
    handoff, request = await sale_with_link(client, sessions)
    assert (await deliver(client, event(request))).status_code == 200
    async with sessions() as db:
        original = await db.scalar(select(SalesPaymentRequest))
        other = SalesDealHandoff(lead_id=222, customer_id=222, engagement_id=222, deal_id=222,
            idempotency_key="other-synthetic-handoff", payload_digest="x" * 64, catalog_token="x" * 64,
            plan_snapshot={}, source_snapshot={}, amount=198, currency="USD", collection_method="stripe_auto",
            operations_owner_employee_id=13, operations_owner_name="User 13", registered_by_id=11)
        db.add(other)
        await db.flush()
        other_request = SalesPaymentRequest(handoff_id=other.id, reference="t24_" + "z" * 43,
            link_snapshot=dict(original.link_snapshot), created_by_id=1)
        db.add(other_request)
        await db.commit()
        second_request = service.request_data(other_request, [])
    # Same Checkout session cannot move to a second deal even when a new signed event has its ref.
    same_session = event(second_request, event_id="evt_crossSession")
    assert (await deliver(client, same_session)).status_code == 409
    # A separate session reusing the invoice/subscription is quarantined for review.
    cross_invoice = event(second_request, event_id="evt_crossInvoice", session_id="cs_live_second")
    assert (await deliver(client, cross_invoice)).status_code == 200
    async with sessions() as db:
        items = (await db.scalars(select(SalesStripeObservation).order_by(SalesStripeObservation.id))).all()
        assert items[0].status == "paid_observed" and items[1].status == "needs_review"
        assert "cross_request_identity" in items[1].match_issues
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0


@pytest.mark.asyncio
async def test_async_success_after_processing_stays_observation_and_event_id_reuse_is_rejected(sale_api, monkeypatch):
    client, sessions = sale_api
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET", SECRET)
    handoff, request = await sale_with_link(client, sessions)
    pending = event(request, payment_status="unpaid")
    assert (await deliver(client, pending)).status_code == 200
    success = event(request, event_id="evt_asyncSuccess", kind="checkout.session.async_payment_succeeded", at=pending["created"] + 1)
    assert (await deliver(client, success)).status_code == 200
    changed = {**success, "data": {"object": {**success["data"]["object"], "amount_total": 19900}}}
    assert (await deliver(client, changed)).status_code == 409
    async with sessions() as db:
        observed = await db.scalar(select(SalesStripeObservation))
        assert observed.status == "paid_observed" and observed.gross_minor == 21533
        assert await db.scalar(select(func.count()).select_from(SalesStripeEvent)) == 2
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0
        assert (await db.get(SalesDealHandoff, handoff["id"])).payment_status == "pending"
        assert (await db.get(Subscriptions, handoff["subscription_id"])).status == "pending"


@pytest.mark.asyncio
async def test_pre_extension_paid_fingerprint_replays_without_creating_new_evidence(sale_api):
    from routers.sales_deal_handoffs import VerifyReceipt
    from services.sales_deal_handoffs import digest
    client, sessions = sale_api
    handoff = await registered(client)
    url = f"{PREFIX}/{handoff['id']}/finance-confirmation"
    assert (await client.post(url, headers=headers(1), json=payment())).status_code == 200
    old_fields = ("amount_received", "payment_date", "currency", "payment_method", "transaction_reference")
    model = VerifyReceipt(**payment()).model_dump(mode="json")
    async with sessions() as db:
        row = await db.get(SalesDealHandoff, handoff["id"])
        row.payment_fingerprint = digest({key: model[key] for key in old_fields})
        await db.commit()
    replay = await client.post(url, headers=headers(1), json=payment())
    assert replay.status_code == 200 and replay.json()["idempotent_replay"]
    assert (await client.post(url, headers=headers(1), json=taxed_receipt())).status_code == 409
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Payments)) == 1
        assert await db.scalar(select(func.count()).select_from(SalesReceiptEvidence)) == 0


@pytest.mark.asyncio
async def test_manual_stripe_evidence_reference_cannot_verify_two_deals_case_insensitively(sale_api):
    client, sessions = sale_api
    handoff, request = await sale_with_link(client, sessions)
    async with sessions() as db:
        db.add(SalesLeads(id=2, business_name="Different Synthetic Merchant", contact_name="Second Owner",
            phone="+12125550114", country="US", assigned_sales_id=11, assigned_sales_name="User 11"))
        await db.commit()
    second = await client.post(PREFIX + "/leads/2", headers=headers(), json=await draft(client, idempotency_key="synthetic-request-second"))
    assert second.status_code == 200, second.text
    other = second.json()["handoff"]
    first_receipt = await client.post(f"{PREFIX}/{handoff['id']}/finance-confirmation", headers=headers(1), json=taxed_receipt(transaction_reference="Pi_REAL_SYNTHETIC_RECEIPT"))
    assert first_receipt.status_code == 200, first_receipt.text
    duplicate = await client.post(f"{PREFIX}/{other['id']}/finance-confirmation", headers=headers(1), json=taxed_receipt(transaction_reference="pi_real_synthetic_receipt"))
    assert duplicate.status_code == 409, duplicate.text
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Payments)) == 1
        assert await db.scalar(select(func.count()).select_from(SalesReceiptEvidence)) == 1
        assert not (await db.get(Deals, other["deal_id"])).is_paid


@pytest.mark.asyncio
async def test_sales_handoff_todo_reports_owner_progress_without_financial_details(sale_api):
    client, sessions = sale_api
    handoff, request = await sale_with_link(client, sessions)
    await grant(sessions, handoff["customer_id"])
    accepted = await client.post(f"{PREFIX}/{handoff['id']}/operations-acknowledgment", headers=headers(13), json={"note": "已核对服务资料，由本人接收"})
    assert accepted.status_code == 200
    assert "receipt_review_status" not in accepted.json()["handoff"]
    queue = (await client.get(PREFIX + "/queue", headers=headers())).json()
    assert queue["counts"]["pending_payment"] == 1 and queue["counts"]["completed"] == 0
    assert queue["items"][0]["receipt_review_status"] == "pending_owner_review"
    assert "payment_status" not in queue["items"][0] and "payment_id" not in queue["items"][0]
    assert (await client.post(f"{PREFIX}/{handoff['id']}/finance-confirmation", headers=headers(1), json=taxed_receipt())).status_code == 200
    queue = (await client.get(PREFIX + "/queue", headers=headers())).json()
    assert queue["counts"]["pending_payment"] == 0 and queue["counts"]["completed"] == 1
    item = queue["items"][0]
    assert item["receipt_review_status"] == "owner_verified" and not item["can_request_payment"]
    for field in ("payment_status", "payment_id", "payment_confirmed_at", "tax_amount", "fee_amount", "gross_amount", "payer_email"):
        assert field not in item
    async with sessions() as db:
        lead = await db.get(SalesLeads, 1)
        lead.assigned_sales_id, lead.assigned_sales_name = 12, "User 12"
        await db.commit()
    assert (await client.get(PREFIX + "/queue", headers=headers())).json()["items"] == []
    assert (await client.get(f"{PREFIX}/{handoff['id']}", headers=headers())).status_code == 404


@pytest.mark.asyncio
async def test_unknown_or_irrelevant_signed_events_ack_without_storing_customer_data(sale_api, monkeypatch):
    client, sessions = sale_api
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET", SECRET)
    for payload in ({"type": "invoice.paid", "data": {"object": {"customer_email": "other@example.com"}}},
                    {"type": ["bad", "type"]}, {"type": "customer.created"}):
        response = await deliver(client, payload)
        assert response.status_code == 200 and response.json() == {"received": True}
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(SalesStripeEvent)) == 0
        assert await db.scalar(select(func.count()).select_from(SalesStripeObservation)) == 0


@pytest.mark.asyncio
async def test_abandoned_checkout_missing_tax_or_subscription_is_expired_not_payment_anomaly(sale_api, monkeypatch):
    client, sessions = sale_api
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET", SECRET)
    handoff, request = await sale_with_link(client, sessions)
    abandoned = event(request, kind="checkout.session.expired", subscription=None, invoice=None,
        amount_total=None, total_details={}, payment_status="unpaid")
    assert (await deliver(client, abandoned)).status_code == 200
    async with sessions() as db:
        row = await db.scalar(select(SalesStripeObservation))
        assert row.status == "expired" and row.match_issues == [] and row.paid_at is None
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0
        assert (await db.get(SalesDealHandoff, handoff["id"])).payment_status == "pending"
