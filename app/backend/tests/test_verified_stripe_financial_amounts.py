"""Synthetic new-receipt accounting; no runtime database or provider is used."""
from copy import deepcopy
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from backend.tests.test_deal_payment_sync import db_session, seed_customer, seed_deal
from models.commissions import CommissionAgreement, CommissionEntry, CustomerCommissionAttribution, SalesPartner
from services.business_intelligence import _service_amount
from services.commissions import eligible_service_amount, sync_payment_commission
from services.deal_payment_sync import _derive_income_split, infer_payment_income_type, sync_payment_from_deal
from services.stripe_history_reconciliation import accounting_payload


@pytest.mark.parametrize("product_type,expected", [
    ("beauty_os", "other_income"), ("restaurant_os", "ordering_fee"),
    ("managed_service", "management_fee"), ("one_time_project", "other_income"),
])
def test_explicit_catalog_service_type_is_not_reclassified_by_marketing_name(product_type, expected):
    assert infer_payment_income_type(product_type, "Synthetic Ads integration 官网") == expected


def test_service_split_needs_explicit_context_and_never_changes_ad_funds():
    assert _derive_income_split("other_income", 198) == (0, 0)
    assert _derive_income_split("unknown", 198, service_revenue=True) == (0, 0)
    assert _derive_income_split("other_income", 198, service_revenue=True) == (None, 0)
    assert _derive_income_split("website_fee", 198, service_revenue=True) == (None, 0)
    assert _derive_income_split("management_fee", 198, service_revenue=True) == (198, 0)
    assert _derive_income_split("ads_fee", 198, service_revenue=True) == (0, 198)


@pytest.mark.asyncio
async def test_known_beauty_os_receipt_enters_service_revenue_and_existing_commission_once(db_session):
    customer = await seed_customer(db_session, business_name="Synthetic Beauty OS")
    deal = await seed_deal(db_session, customer, product_type="beauty_os", package_name="Synthetic Beauty OS",
        deal_amount=198, service_start_date=datetime(2026, 1, 1), service_end_date=datetime(2026, 2, 1))
    partner = SalesPartner(partner_code="SYNTHETIC-OS", name="Synthetic Channel", partner_type="agency",
        status="active", joined_at=date(2026, 1, 1))
    db_session.add(partner)
    await db_session.flush()
    db_session.add(CommissionAgreement(partner_id=partner.id, version=1, first_order_rate=.3, renewal_rate=.1,
        calculation_version="service_month_v2", renewal_policy="fixed", activity_decay_json="{}",
        refund_guard_days=0, effective_from=date(2026, 1, 1), status="active"))
    db_session.add(CustomerCommissionAttribution(customer_id=customer.id, partner_id=partner.id,
        attribution_role="primary", commission_mode="first_month_then_renewal", first_service_start=date(2026, 1, 1),
        commission_start_date=date(2026, 1, 1), effective_from=date(2026, 1, 1), is_active=True))
    await db_session.commit()
    payment = await sync_payment_from_deal(db_session, deal)
    assert payment.amount_paid == 198 and payment.management_amount is None and payment.ads_recharge_amount == 0
    assert _service_amount(payment) == eligible_service_amount(payment) == 198
    commission = await sync_payment_commission(db_session, payment)
    await db_session.commit()
    assert commission.status == "pending_confirmation" and commission.commission_amount == 59.4
    assert commission.contract_rate == .3  # the existing synthetic agreement, never a new policy
    await sync_payment_commission(db_session, payment)
    await db_session.commit()
    assert await db_session.scalar(select(func.count()).select_from(CommissionEntry)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("product_type,income_type,management,ads", [
    ("ads", "ads_fee", 0, 198), ("unclassified", "other_income", 0, 0),
])
async def test_ads_and_unknown_receipts_do_not_gain_service_revenue(db_session, product_type, income_type, management, ads):
    customer = await seed_customer(db_session)
    deal = await seed_deal(db_session, customer, product_type=product_type, package_name="Synthetic generic",
        deal_amount=198)
    payment = await sync_payment_from_deal(db_session, deal)
    assert (payment.income_type, payment.management_amount, payment.ads_recharge_amount) == (income_type, management, ads)
    assert _service_amount(payment) == eligible_service_amount(payment) == 0
    assert await sync_payment_commission(db_session, payment) is None


def verified_payload(*, income_type="other_income", complete_scope=True, tax=1733, fee=650):
    binding = SimpleNamespace(customer_id=1, income_type=income_type,
        crm_snapshot={"customer_name": "Synthetic", "package_name": "Synthetic Beauty OS", "engagement_id": 1 if complete_scope else None,
            "business_line_id": 3 if complete_scope else None, "product_id": 8 if complete_scope else None},
        price_snapshot={"billing_cycle": "monthly"})
    snapshot = {"service_minor": 19800, "tax_minor": tax, "gross_minor": 19800 + tax,
        "fee_minor": fee, "net_minor": 19800 + tax - fee, "currency": "USD", "issues": [],
        "payment_date": "2026-01-03", "coverage_start": "2026-01-01", "coverage_end": "2026-02-01",
        "stripe_invoice_id": "in_synthetic_actual"}
    return binding, snapshot, SimpleNamespace(id=1, name="Synthetic Owner")


@pytest.mark.parametrize("tax,fee", [(1733, 650), (1733, 158), (0, 0)])
def test_verified_actual_fee_and_platform_net_preserve_tax_exclusive_service_income(tax, fee):
    binding, snapshot, user = verified_payload(tax=tax, fee=fee)
    before = deepcopy(snapshot)
    payload = accounting_payload(binding, snapshot, user)
    assert payload["amount_due"] == payload["amount_paid"] == 198
    assert payload["stripe_fee_amount"] == fee / 100
    assert payload["net_amount"] == (19800 + tax - fee) / 100
    assert payload["management_amount"] is None and payload["ads_recharge_amount"] == 0
    payment = SimpleNamespace(**payload)
    assert _service_amount(payment) == eligible_service_amount(payment) == 198
    assert "非银行到账" in payload["notes"]
    assert snapshot == before  # the original gross/tax/fee/net proof is retained


def test_unknown_other_binding_without_complete_project_scope_keeps_original_split():
    binding, snapshot, user = verified_payload(complete_scope=False)
    payload = accounting_payload(binding, snapshot, user)
    assert payload["management_amount"] == payload["ads_recharge_amount"] == 0
    assert eligible_service_amount(SimpleNamespace(**payload)) == 0


@pytest.mark.parametrize("change", [
    {"fee_minor": None}, {"net_minor": None}, {"fee_minor": -1}, {"net_minor": 1},
    {"gross_minor": 19800}, {"tax_minor": True}, {"fee_minor": 22000, "net_minor": 0},
    {"issues": ["cash_unverified"]},
])
def test_missing_or_inconsistent_verified_amounts_never_fall_back_to_estimated_fee(change):
    binding, snapshot, user = verified_payload()
    snapshot.update(change)
    with pytest.raises(HTTPException) as caught:
        accounting_payload(binding, snapshot, user)
    assert caught.value.status_code == 409
