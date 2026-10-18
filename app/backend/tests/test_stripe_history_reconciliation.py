"""Isolated owner pilot: suggestions never become ledger rows without confirmation."""
import copy
import json
import time
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from backend.tests.test_sales_catalog_handoffs import headers, sale_api
from backend.tests.test_sales_deal_payments import SECRET, deliver
from backend.tests.test_service_follow_through import lifecycle
from core.database import Base
from models.commissions import CommissionAgreement, CommissionEntry, CustomerCommissionAttribution, SalesPartner
from models.customers import Customers
from models.employees import Employees
from models.finance_profit_closes import MonthlyProfitClose
from models.management_decisions import CustomerEngagement
from models.payments import Payments
from models.stripe_history_reconciliation import (StripeHistoryBinding, StripeHistoryEvent, StripeHistoryInvoiceReview,
    StripeHistoryPolicy, StripeHistoryPosting, StripeHistoryPreview)
from models.subscriptions import Subscriptions
from services import stripe_history_provider as provider
from services import stripe_history_reconciliation as service
from services.deal_payment_sync import _calculate_stripe_fee, _derive_income_split

API = "/api/v1/stripe-history-reconciliation"
START = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())
END = int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp())


def remote_subscription(identity=100):
    return {"id": f"sub_history{identity}", "livemode": True, "status": "active",
        "customer": {"id": f"cus_history{identity}", "name": f"Synthetic History {identity}", "email": f"synthetic{identity}@example.com"},
        "items": {"data": [{"quantity": 1, "price": {"id": f"price_history{identity}", "unit_amount": 19800,
            "currency": "usd", "tax_behavior": "exclusive", "recurring": {"interval": "month", "interval_count": 1}}}], "has_more": False},
        "current_period_start": START, "current_period_end": END}


def remote_invoice(identity=100):
    invoice_id, charge_id, intent_id = f"in_history{identity}", f"ch_history{identity}", f"pi_history{identity}"
    return {"id": invoice_id, "object": "invoice", "livemode": True, "subscription": f"sub_history{identity}", "customer": f"cus_history{identity}",
        "created": START, "status": "paid", "paid": True, "paid_out_of_band": False, "currency": "usd",
        "total": 21533, "total_excluding_tax": 19800, "total_tax_amounts": [{"amount": 1733}], "tax": 1733,
        "amount_due": 21533, "amount_paid": 21533, "amount_remaining": 0, "starting_balance": 0, "ending_balance": 0,
        "pre_payment_credit_notes_amount": 0, "post_payment_credit_notes_amount": 0, "discounts": [], "total_discount_amounts": [],
        "status_transitions": {"paid_at": START + 100},
        "lines": {"has_more": False, "data": [{"description": "Synthetic service", "amount": 19800, "currency": "usd", "type": "subscription",
            "proration": False, "quantity": 1, "price": {"id": f"price_history{identity}"}, "period": {"start": START, "end": END}}]},
        "payment_intent": {"id": intent_id, "livemode": True, "status": "succeeded", "amount_received": 21533, "currency": "usd",
            "latest_charge": {"id": charge_id, "livemode": True, "payment_intent": intent_id, "invoice": invoice_id, "customer": f"cus_history{identity}",
                "paid": True, "captured": True, "amount": 21533, "amount_captured": 21533, "currency": "usd", "refunded": False,
                "amount_refunded": 0, "disputed": False, "balance_transaction": {"id": f"txn_history{identity}", "type": "charge", "source": charge_id,
                    "currency": "usd", "amount": 21533, "fee": 650, "net": 20883}}}}


class FakeReader:
    def __init__(self):
        self.subscription_rows = {f"sub_history{i}": remote_subscription(i) for i in range(100, 110)}
        self.invoice_rows = {f"in_history{i}": remote_invoice(i) for i in range(100, 110)}
        self.calls = []

    async def subscription(self, identity):
        self.calls.append(("subscription", identity))
        return copy.deepcopy(self.subscription_rows[identity])

    async def subscriptions(self, customer_id=None, starting_after=None):
        self.calls.append(("subscriptions", customer_id, starting_after))
        return [copy.deepcopy(row) for row in self.subscription_rows.values() if not customer_id or row["customer"]["id"] == customer_id], False

    async def invoices(self, subscription_id, date_start, date_end, starting_after=None):
        self.calls.append(("invoices", subscription_id, date_start, date_end, starting_after))
        return [copy.deepcopy(row) for row in self.invoice_rows.values() if row["subscription"] == subscription_id and date_start <= row["created"] < date_end], False

    async def invoice(self, identity):
        self.calls.append(("invoice", identity))
        return copy.deepcopy(self.invoice_rows[identity])


@pytest_asyncio.fixture
async def history_api(sale_api, monkeypatch):
    client, sessions = sale_api
    fake = FakeReader()
    monkeypatch.setattr(provider, "reader", lambda: fake)
    async with sessions() as db:
        db.add(SalesPartner(id=100, partner_code="SYNTHETIC-HISTORY", name="Synthetic Existing Partner", partner_type="agency", status="active", joined_at=date(2025, 1, 1)))
        await db.flush()
        db.add(CommissionAgreement(id=100, partner_id=100, version=1, calculation_version="service_month_v2", renewal_policy="fixed",
            first_order_rate=.3, renewal_rate=.1, activity_decay_json="{}", effective_from=date(2025, 1, 1), status="active"))
        for identity in range(100, 107):
            db.add(Customers(id=identity, business_name=f"Synthetic History {identity}", contact_name="Synthetic Owner", phone=f"+1212555{identity:04}", status="active"))
            await db.flush()
            db.add(CustomerEngagement(id=identity, customer_id=identity, business_line_id=1, product_id=1, product_plan_id=1,
                engagement_code=f"SYNTHETIC-HISTORY-{identity}", package_name="专业套餐", status="active_paid", billing_cycle="monthly", currency="USD"))
            await db.flush()
            db.add(Subscriptions(id=identity, customer_id=identity, customer_name=f"Synthetic History {identity}", package_name="专业套餐", package_price=198,
                status="active", billing_cycle="monthly", start_date=datetime(2025, 1, 1), end_date=datetime(2026, 11, 1),
                engagement_id=identity, business_line_id=1, product_id=1, product_plan_id=1))
            db.add(CustomerCommissionAttribution(customer_id=identity, engagement_id=identity, partner_id=100, attribution_role="primary", commission_mode="renewal_only",
                commission_start_date=date(2025, 1, 1), history_basis="历史首期已经结清", effective_from=date(2025, 1, 1), is_active=True))
        await db.commit()
    return client, sessions, fake


async def snapshot(sessions, excluding=()):
    async with sessions() as db:
        return {table.name: sorted(json.dumps(dict(row._mapping), sort_keys=True, default=str) for row in (await db.execute(select(table))).all())
            for table in Base.metadata.sorted_tables if not table.name.startswith("stripe_history_") and table.name not in excluding}


async def bind(client, identity=100):
    preview = await client.post(API + "/bindings/preview", headers=headers(1), json={"crm_subscription_id": identity,
        "stripe_subscription_id": f"sub_history{identity}", "sync_from": "2026-09-01", "income_type": "management_fee"})
    assert preview.status_code == 200, preview.text
    data = preview.json()
    response = await client.post(API + "/bindings", headers=headers(1), json={"token": data["token"], "owner_verified": True,
        "accepted_warning_codes": [item["code"] for item in data["warnings"]]})
    assert response.status_code == 200, response.text
    return response.json()["binding"]


async def sync(client, binding):
    response = await client.post(f"{API}/bindings/{binding['id']}/sync", headers=headers(1), json={"date_start": "2026-10-01", "date_end": "2026-10-19"})
    assert response.status_code == 200, response.text
    return response.json()


def confirmation(revision=1, **values):
    return {"revision": revision, "action": "create_payment", "owner_verified": True, "verification_note": "老板已核对实际扣款与服务", **values}


@pytest.mark.asyncio
async def test_get_readonly_owner_only_and_current_crm_options_no_provider_or_ledger_writes(history_api):
    client, sessions, fake = history_api
    before = await snapshot(sessions)
    for actor in (11, 12, 13, 14, 15, 16, 17):
        for path in ("/overview", "/crm-services", "/stripe-subscriptions", "/invoice-reviews"):
            assert (await client.get(API + path, headers=headers(actor))).status_code == 403
    assert fake.calls == []
    overview = await client.get(API + "/overview", headers=headers(1))
    assert overview.status_code == 200 and overview.json()["auto_accounting"] is False
    assert overview.json()["pilot"]["limit"] == 5 and not overview.json()["pilot"]["bulk_enabled"]
    assert "no-store" in overview.headers["cache-control"]
    assert len((await client.get(API + "/crm-services?search=History", headers=headers(1))).json()["items"]) == 7
    assert fake.calls == [] and await snapshot(sessions) == before


@pytest.mark.asyncio
async def test_binding_preview_explicit_confirmation_idempotence_and_no_old_rows_changed(history_api):
    client, sessions, fake = history_api
    before = await snapshot(sessions)
    binding = await bind(client)
    overview = (await client.get(API + "/overview", headers=headers(1))).json()
    assert len(overview["bindings"]) == 1 and binding["price_id"] == "price_history100" and binding["amount"] == 198
    assert await snapshot(sessions) == before
    duplicate = await client.post(API + "/bindings/preview", headers=headers(1), json={"crm_subscription_id": 100,
        "stripe_subscription_id": "sub_history100", "sync_from": "2026-09-01", "income_type": "management_fee"})
    assert duplicate.status_code == 409
    for actor in (11, 13, 15, 17):
        assert (await client.post(API + "/bindings", headers=headers(actor), json={"token": "a" * 43, "owner_verified": True})).status_code == 403
    assert not any("PRIVATE" in str(call) for call in fake.calls)


@pytest.mark.asyncio
async def test_sync_twice_stable_pending_cash_proof_then_explicit_owner_posts_original_math_once(history_api):
    client, sessions, fake = history_api
    binding = await bind(client)
    before = await snapshot(sessions)
    first = await sync(client, binding)
    second = await sync(client, binding)
    assert first["items"][0]["id"] == second["items"][0]["id"]
    assert second["binding"]["pilot_evidence"]["repeat_dedupe_verified"] is True
    assert second["binding"]["pilot_evidence"]["cash_evidence_verified"] is True
    assert await snapshot(sessions) == before
    review = (await client.get(f"{API}/invoice-reviews/{first['items'][0]['id']}", headers=headers(1))).json()["review"]
    assert review["can_create_payment"] and review["fee_amount"] == 6.5 and review["tax_amount"] == 17.33
    assert review["accounting_preview"]["stripe_fee_amount"] == _calculate_stripe_fee(198, "stripe", "subscription_auto") == 6.04
    assert review["accounting_preview"]["net_amount"] == 191.96
    response = await client.post(f"{API}/invoice-reviews/{review['id']}/confirm", headers=headers(1), json=confirmation(review["revision"]))
    assert response.status_code == 200, response.text
    assert response.json()["review"]["status"] == "confirmed"
    assert not response.json()["review"]["can_confirm"]
    replay = await client.post(f"{API}/invoice-reviews/{review['id']}/confirm", headers=headers(1), json=confirmation(review["revision"]))
    assert replay.status_code == 200 and replay.json()["idempotent_replay"]
    async with sessions() as db:
        payment = await db.get(Payments, response.json()["payment_id"])
        assert (payment.amount_paid, payment.management_amount, payment.ads_recharge_amount, payment.stripe_fee_amount, payment.net_amount) == (198, 198, 0, 6.04, 191.96)
        assert payment.source_deal_id is None and payment.transaction_reference == "in_history100"
        entries = (await db.scalars(select(CommissionEntry))).all()
        assert len(entries) == 1 and entries[0].entry_type == "renewal" and entries[0].commission_amount == 19.8
        assert await db.scalar(select(func.count()).select_from(StripeHistoryPosting)) == 1
        assert await db.scalar(select(func.count()).select_from(Payments)) == 1
    # A posting may add only its receipt and the original pending commission;
    # it must not reset service/cooperation dates, source ownership or invites.
    after = await snapshot(sessions)
    assert {key: value for key, value in after.items() if key not in {"payments", "commission_entries"}} == {key: value for key, value in before.items() if key not in {"payments", "commission_entries"}}
    assert [call for call in fake.calls if call[0] == "invoice"]  # Fresh confirmation read.


@pytest.mark.parametrize("case", ["out_of_band", "credit", "partial", "multiple", "proration", "discount", "currency", "tax", "fee", "refund", "dispute", "capture", "intent", "period", "price"])
@pytest.mark.asyncio
async def test_ambiguous_or_noncash_invoice_holds_pending_and_cannot_post(history_api, case):
    client, sessions, fake = history_api
    binding = await bind(client)
    raw = fake.invoice_rows["in_history100"]
    charge = raw["payment_intent"]["latest_charge"]
    if case == "out_of_band": raw["paid_out_of_band"] = True
    if case == "credit": raw["starting_balance"] = -100
    if case == "partial": raw["amount_paid"] = 10000
    if case == "multiple": raw["lines"]["data"].append(copy.deepcopy(raw["lines"]["data"][0]))
    if case == "proration": raw["lines"]["data"][0]["proration"] = True
    if case == "discount": raw["total_discount_amounts"] = [{"amount": 100}]
    if case == "currency": raw["currency"] = "cad"
    if case == "tax": raw["total_tax_amounts"] = []
    if case == "fee": charge["balance_transaction"]["net"] = 1
    if case == "refund": charge["amount_refunded"] = 1
    if case == "dispute": charge["disputed"] = True
    if case == "capture": charge["captured"] = False
    if case == "intent": raw["payment_intent"]["status"] = "processing"
    if case == "period": raw["lines"]["data"][0]["period"]["end"] = START
    if case == "price": raw["lines"]["data"][0]["price"]["id"] = "price_changed"
    before = await snapshot(sessions)
    result = await sync(client, binding)
    row = result["items"][0]
    assert row["status"] == "exception" and row["issues"]
    detail = (await client.get(f"{API}/invoice-reviews/{row['id']}", headers=headers(1))).json()["review"]
    assert not detail["can_confirm"]
    response = await client.post(f"{API}/invoice-reviews/{row['id']}/confirm", headers=headers(1), json=confirmation())
    assert response.status_code == 409
    assert await snapshot(sessions) == before


@pytest.mark.asyncio
async def test_cash_revalidated_at_confirmation_and_closed_month_rolls_back_everything(history_api):
    client, sessions, fake = history_api
    binding = await bind(client)
    data = await sync(client, binding)
    review = data["items"][0]
    fake.invoice_rows["in_history100"]["payment_intent"]["latest_charge"]["disputed"] = True
    before = await snapshot(sessions)
    assert (await client.post(f"{API}/invoice-reviews/{review['id']}/confirm", headers=headers(1), json=confirmation())).status_code == 409
    assert await snapshot(sessions) == before
    fake.invoice_rows["in_history100"] = remote_invoice()
    async with sessions() as db:
        db.add(MonthlyProfitClose(year_month="2026-10", status="locked", snapshot_json="{}"))
        await db.commit()
    before = await snapshot(sessions)
    detail = (await client.get(f"{API}/invoice-reviews/{review['id']}", headers=headers(1))).json()["review"]
    assert not detail["can_confirm"] and "月结" in detail["read_only_reason"]
    result = await client.post(f"{API}/invoice-reviews/{review['id']}/confirm", headers=headers(1), json=confirmation())
    assert result.status_code == 409 and "月结" in result.text
    assert await snapshot(sessions) == before
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(StripeHistoryPosting)) == 0


async def manual_payment(sessions, *, customer_id=100, reference="manual-original", **values):
    async with sessions() as db:
        row = Payments(customer_id=customer_id, customer_name="Synthetic Manual", product_name="专业套餐", amount_due=198, amount_paid=198,
            currency="USD", payment_date=datetime(2026, 10, 1), coverage_start=datetime(2026, 10, 1), coverage_end=datetime(2026, 11, 1),
            transaction_reference=reference, engagement_id=customer_id, business_line_id=1, product_id=1, income_type="management_fee", user_id="1", **values)
        db.add(row)
        await db.commit()
        return row.id


@pytest.mark.asyncio
async def test_existing_manual_receipt_blocks_new_post_and_explicit_link_keeps_old_ledger_unchanged(history_api):
    client, sessions, _ = history_api
    payment_id = await manual_payment(sessions)
    binding = await bind(client)
    row = (await sync(client, binding))["items"][0]
    before = await snapshot(sessions)
    detail = (await client.get(f"{API}/invoice-reviews/{row['id']}", headers=headers(1))).json()["review"]
    assert not detail["can_create_payment"] and detail["can_link_existing"]
    assert detail["existing_payment_candidates"][0]["id"] == payment_id
    assert (await client.post(f"{API}/invoice-reviews/{row['id']}/confirm", headers=headers(1), json=confirmation())).status_code == 409
    result = await client.post(f"{API}/invoice-reviews/{row['id']}/confirm", headers=headers(1), json=confirmation(action="link_existing", existing_payment_id=payment_id))
    assert result.status_code == 200, result.text
    assert result.json()["review"]["status"] == "linked_existing"
    assert await snapshot(sessions) == before


@pytest.mark.asyncio
async def test_global_manual_transaction_reference_and_scope_mismatch_never_duplicate(history_api):
    client, sessions, _ = history_api
    await manual_payment(sessions, customer_id=101, reference="Stripe pi_history100 receipt")
    binding = await bind(client)
    row = (await sync(client, binding))["items"][0]
    before = await snapshot(sessions)
    assert (await client.post(f"{API}/invoice-reviews/{row['id']}/confirm", headers=headers(1), json=confirmation())).status_code == 409
    async with sessions() as db:
        existing = await db.scalar(select(Payments))
    assert (await client.post(f"{API}/invoice-reviews/{row['id']}/confirm", headers=headers(1), json=confirmation(action="link_existing", existing_payment_id=existing.id))).status_code == 409
    assert await snapshot(sessions) == before


@pytest.mark.asyncio
async def test_pilot_five_limit_requires_three_explicit_verified_syncs_before_bulk_no_formal_post(history_api):
    client, sessions, _ = history_api
    bindings = [await bind(client, identity) for identity in range(100, 105)]
    assert (await client.post(API + "/pilot/bulk-activation", headers=headers(1), json={"owner_verified": True, "confirmation": "启用批量绑定", "verification_note": "试点均已人工检查"})).status_code == 409
    preview = (await client.post(API + "/bindings/preview", headers=headers(1), json={"crm_subscription_id": 105, "stripe_subscription_id": "sub_history105", "sync_from": "2026-09-01", "income_type": "management_fee"})).json()
    assert not preview["can_confirm"]
    payload = {"token": preview["token"], "owner_verified": True, "accepted_warning_codes": []}
    assert (await client.post(API + "/bindings", headers=headers(1), json=payload)).status_code == 409
    before = await snapshot(sessions)
    for binding in bindings[:3]:
        first = await sync(client, binding)
        assert (await client.post(f"{API}/bindings/{binding['id']}/validate-pilot", headers=headers(1), json={"revision": first["binding"]["revision"], "owner_verified": True, "verification_note": "已核对"})).status_code == 409
        second = await sync(client, binding)
        response = await client.post(f"{API}/bindings/{binding['id']}/validate-pilot", headers=headers(1), json={"revision": second["binding"]["revision"], "owner_verified": True, "verification_note": "重复同步去重与实际付款证据已一致"})
        assert response.status_code == 200, response.text
    response = await client.post(API + "/pilot/bulk-activation", headers=headers(1), json={"owner_verified": True, "confirmation": "启用批量绑定", "verification_note": "三家试点重复同步和凭据核对无误"})
    assert response.status_code == 200 and response.json()["pilot"]["bulk_enabled"]
    assert (await client.post(API + "/bindings", headers=headers(1), json=payload)).status_code == 200
    assert await snapshot(sessions) == before
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0
        assert await db.scalar(select(func.count()).select_from(StripeHistoryPosting)) == 0
        assert await db.scalar(select(func.count()).select_from(StripeHistoryBinding)) == 6


@pytest.mark.asyncio
async def test_mapped_webhook_creates_only_refresh_draft_unknown_ignored_and_signature_verified(history_api, monkeypatch):
    client, sessions, _ = history_api
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET", SECRET)
    unknown = lifecycle(sub="sub_unmapped", identity="in_unknown", created=START)
    assert (await deliver(client, unknown)).status_code == 200
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(StripeHistoryEvent)) == 0
    binding = await bind(client)
    before = await snapshot(sessions)
    payload = lifecycle("invoice.paid", sub="sub_history100", identity="in_history100", created=START)
    assert (await deliver(client, payload, secret="whsec_synthetic_incorrect_secret")).status_code == 400
    assert (await deliver(client, payload)).status_code == 200
    assert (await deliver(client, payload)).status_code == 200
    async with sessions() as db:
        draft = await db.scalar(select(StripeHistoryInvoiceReview))
        assert draft.status == "needs_refresh"
        assert "NEVER-PERSIST" not in json.dumps(draft.snapshot)
        assert await db.scalar(select(func.count()).select_from(StripeHistoryEvent)) == 1
    assert await snapshot(sessions) == before
    response = await client.post(f"{API}/invoice-reviews/{draft.id}/refresh", headers=headers(1))
    assert response.status_code == 200 and response.json()["review"]["status"] == "pending_review"
    assert await snapshot(sessions) == before

@pytest.mark.asyncio
async def test_postcommit_background_hydrates_bound_invoice_without_owner_click_or_ledger_write(history_api, monkeypatch):
    client, sessions, _ = history_api
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(service, "background_sessions", lambda: sessions)
    binding = await bind(client)
    before = await snapshot(sessions)
    payload = lifecycle("invoice.paid", sub="sub_history100", identity="in_history100", created=START)
    assert (await deliver(client, payload)).status_code == 200
    async with sessions() as db:
        row = await db.scalar(select(StripeHistoryInvoiceReview))
        assert row.status == "pending_review" and row.snapshot["stripe_charge_id"] == "ch_history100"
        assert row.snapshot["fee_minor"] == 650 and row.needs_refresh is False
        assert await db.scalar(select(func.count()).select_from(Payments)) == 0
    assert await snapshot(sessions) == before


@pytest.mark.asyncio
async def test_background_failure_keeps_durable_queue_next_owner_overview_recovers(history_api, monkeypatch):
    from fastapi import HTTPException
    client, sessions, fake = history_api
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(service, "background_sessions", lambda: sessions)
    await bind(client)
    original = fake.invoice
    async def unavailable(identity):
        raise HTTPException(503, "Synthetic unavailable")
    fake.invoice = unavailable
    payload = lifecycle("invoice.paid", sub="sub_history100", identity="in_history100", created=START)
    assert (await deliver(client, payload)).status_code == 200
    async with sessions() as db:
        row = await db.scalar(select(StripeHistoryInvoiceReview))
        assert row.status == "needs_refresh" and row.needs_refresh
    fake.invoice = original
    before = await snapshot(sessions)
    assert (await client.get(API + "/overview", headers=headers(1))).status_code == 200
    async with sessions() as db:
        row = await db.scalar(select(StripeHistoryInvoiceReview))
        assert row.status == "pending_review" and not row.needs_refresh
    assert await snapshot(sessions) == before

@pytest.mark.asyncio
async def test_legacy_gross_amount_without_provider_ids_blocks_duplicate_and_needs_original_correction(history_api):
    client, sessions, _ = history_api
    payment_id = await manual_payment(sessions)
    async with sessions() as db:
        old = await db.get(Payments, payment_id)
        old.amount_paid = old.amount_due = 215.33
        await db.commit()
    binding = await bind(client)
    row = (await sync(client, binding))["items"][0]
    before = await snapshot(sessions)
    detail = (await client.get(f"{API}/invoice-reviews/{row['id']}", headers=headers(1))).json()["review"]
    assert not detail["can_create_payment"] and detail["existing_payment_candidates"][0]["id"] == payment_id
    assert (await client.post(f"{API}/invoice-reviews/{row['id']}/confirm", headers=headers(1), json=confirmation())).status_code == 409
    assert (await client.post(f"{API}/invoice-reviews/{row['id']}/confirm", headers=headers(1), json=confirmation(action="link_existing", existing_payment_id=payment_id))).status_code == 409
    assert await snapshot(sessions) == before


@pytest.mark.asyncio
async def test_unrelated_closed_fuzzy_candidate_does_not_block_correct_explicit_open_record_link(history_api):
    client, sessions, _ = history_api
    correct = await manual_payment(sessions)
    old = await manual_payment(sessions, reference="other-period")
    async with sessions() as db:
        other = await db.get(Payments, old)
        other.coverage_start, other.coverage_end = datetime(2026, 9, 1), datetime(2026, 10, 1)
        db.add(MonthlyProfitClose(year_month="2026-09", status="locked", snapshot_json="{}"))
        await db.commit()
    binding = await bind(client)
    row = (await sync(client, binding))["items"][0]
    before = await snapshot(sessions)
    detail = (await client.get(f"{API}/invoice-reviews/{row['id']}", headers=headers(1))).json()["review"]
    assert detail["can_link_existing"] and not detail["can_create_payment"]
    response = await client.post(f"{API}/invoice-reviews/{row['id']}/confirm", headers=headers(1), json=confirmation(action="link_existing", existing_payment_id=correct))
    assert response.status_code == 200, response.text
    assert await snapshot(sessions) == before


@pytest.mark.asyncio
async def test_owner_renewal_coverage_historical_binding_unique_invoice_signals_and_fresh_cash_resolution(history_api, monkeypatch):
    client, sessions, _ = history_api
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET", SECRET)
    binding = await bind(client)
    before = await snapshot(sessions)
    endpoint = "/api/v1/service-follow-through/renewals"
    result = (await client.get(endpoint, headers=headers(1))).json()
    matched = next(row for row in result["items"] if row["customer_id"] == 100)
    assert matched["connection_status"] == "linked" and result["coverage"]["linked_subscriptions"] == 1
    at = int(time.time())
    failed = lifecycle(sub="sub_history100", identity="in_history100", event_id="evt_historyFailed", at=at, created=START)
    assert (await deliver(client, failed)).status_code == 200
    assert (await deliver(client, failed)).status_code == 200
    result = (await client.get(endpoint, headers=headers(1))).json()
    matched = next(row for row in result["items"] if row["customer_id"] == 100)
    assert matched["status"] == "payment_failed" and len(matched["signals"]) == 1
    assert result["coverage"]["received_event_count"] == 1 and "stripe_reconciliation" in matched["href"]
    await sync(client, binding)
    result = (await client.get(endpoint, headers=headers(1))).json()
    matched = next(row for row in result["items"] if row["customer_id"] == 100)
    assert matched["status"] == "payment_observed" and len(matched["signals"]) == 1
    assert (await deliver(client, lifecycle("customer.subscription.deleted", sub="sub_history100", event_id="evt_historyCancelled", at=at+1))).status_code == 200
    result = (await client.get(endpoint, headers=headers(1))).json()
    assert next(row for row in result["items"] if row["customer_id"] == 100)["status"] == "cancelled"
    assert await snapshot(sessions) == before


@pytest.mark.asyncio
async def test_new_notification_invalidates_pilot_proof_before_bulk_activation(history_api, monkeypatch):
    client, sessions, _ = history_api
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET", SECRET)
    bindings = [await bind(client, identity) for identity in range(100, 103)]
    before = await snapshot(sessions)
    for binding in bindings:
        await sync(client, binding)
        result = await sync(client, binding)
        verified = await client.post(f"{API}/bindings/{binding['id']}/validate-pilot", headers=headers(1), json={
            "revision": result["binding"]["revision"], "owner_verified": True, "verification_note": "试点凭据与重复同步一致"})
        assert verified.status_code == 200, verified.text
    event = lifecycle(sub="sub_history100", identity="in_history100", event_id="evt_historyProofChanged", created=START)
    assert (await deliver(client, event)).status_code == 200
    async with sessions() as db:
        binding = await db.get(StripeHistoryBinding, bindings[0]["id"])
        assert binding.needs_refresh and not binding.pilot_validated
        stale_revision = binding.revision
        assert not service.pilot_proof_current(binding)
    blocked = await client.post(f"{API}/bindings/{bindings[0]['id']}/validate-pilot", headers=headers(1), json={
        "revision": stale_revision, "owner_verified": True, "verification_note": "不能继续沿用旧同步证明"})
    assert blocked.status_code == 409
    activation = {"owner_verified": True, "confirmation": "启用批量绑定", "verification_note": "三家试点核验"}
    assert (await client.post(API + "/pilot/bulk-activation", headers=headers(1), json=activation)).status_code == 409
    first = await sync(client, bindings[0])
    assert not first["binding"]["pilot_evidence"]["repeat_dedupe_verified"]
    second = await sync(client, bindings[0])
    verified = await client.post(f"{API}/bindings/{bindings[0]['id']}/validate-pilot", headers=headers(1), json={
        "revision": second["binding"]["revision"], "owner_verified": True, "verification_note": "新通知后再次核验两次同步"})
    assert verified.status_code == 200, verified.text
    assert (await client.post(API + "/pilot/bulk-activation", headers=headers(1), json=activation)).status_code == 200
    assert await snapshot(sessions) == before


@pytest.mark.asyncio
async def test_renewal_exception_href_targets_failed_invoice_not_newer_paid_invoice(history_api, monkeypatch):
    client, sessions, fake = history_api
    monkeypatch.setenv("T24_SALES_STRIPE_WEBHOOK_SECRET", SECRET)
    binding = await bind(client)
    before = await snapshot(sessions)
    failed = fake.invoice_rows["in_history100"]
    failed["status"], failed["paid"], failed["amount_paid"], failed["amount_remaining"] = "open", False, 0, failed["total"]
    newer = fake.invoice_rows["in_history101"]
    newer["subscription"], newer["customer"] = "sub_history100", "cus_history100"
    newer["created"] += 1000
    newer["lines"]["data"][0]["price"]["id"] = "price_history100"
    newer["payment_intent"]["latest_charge"]["customer"] = "cus_history100"
    at = int(time.time())
    assert (await deliver(client, lifecycle(sub="sub_history100", identity="in_history100", event_id="evt_historyOlderFailure", at=at, created=START))).status_code == 200
    rows = (await sync(client, binding))["items"]
    failed_review = next(row for row in rows if row["stripe_invoice_id"] == "in_history100")
    paid_review = next(row for row in rows if row["stripe_invoice_id"] == "in_history101")
    assert failed_review["status"] == "exception" and paid_review["status"] == "pending_review"
    result = (await client.get("/api/v1/service-follow-through/renewals", headers=headers(1))).json()
    matched = next(row for row in result["items"] if row["customer_id"] == 100)
    assert matched["status"] == "payment_failed"
    assert matched["href"].endswith("&stripe_review=" + str(failed_review["id"]))
    assert (await deliver(client, lifecycle("customer.subscription.deleted", sub="sub_history100", event_id="evt_historyHrefCancelled", at=at+1))).status_code == 200
    result = (await client.get("/api/v1/service-follow-through/renewals", headers=headers(1))).json()
    matched = next(row for row in result["items"] if row["customer_id"] == 100)
    assert matched["status"] == "cancelled" and matched["href"] == "/finance?tab=stripe_reconciliation&stripe_view=reviews"
    assert await snapshot(sessions) == before
