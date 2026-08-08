from datetime import date, datetime, timezone
from types import SimpleNamespace

from services.partner_portal import build_partner_customer_status_rows, partner_status_summary


def row(**values):
    return SimpleNamespace(**values)


def service_payment(*, payment_id: int, customer_id: int, engagement_id: int | None, payment_date: date, coverage_end: date, income_type: str = "management_fee"):
    return row(
        id=payment_id,
        customer_id=customer_id,
        engagement_id=engagement_id,
        amount_paid=249,
        income_type=income_type,
        management_amount=249 if income_type != "ads_fee" else 0,
        ads_recharge_amount=249 if income_type == "ads_fee" else 0,
        product_name="基础套餐",
        payment_date=datetime.combine(payment_date, datetime.min.time(), tzinfo=timezone.utc),
        coverage_end=datetime.combine(coverage_end, datetime.min.time(), tzinfo=timezone.utc),
        created_at=None,
    )


def test_partner_status_uses_lifecycle_subscription_and_service_receipt():
    attribution = row(id=1, customer_id=10, engagement_id=101, effective_from=date(2026, 1, 1), effective_to=None, is_active=True)
    customer = row(id=10, customer_code="C-010", business_name="Test Merchant")
    engagement = row(id=101, customer_id=10, business_line_id=1, product_id=2, package_name="基础套餐", status="active_paid", billing_cycle="monthly")
    subscription = row(
        id=201, customer_id=10, engagement_id=101, package_name="基础套餐", status="active", auto_renew=False,
        next_payment_date=None, end_date=datetime(2026, 8, 1, tzinfo=timezone.utc), updated_at=None, created_at=None,
    )
    payment = service_payment(payment_id=301, customer_id=10, engagement_id=101, payment_date=date(2026, 7, 30), coverage_end=date(2026, 9, 1))

    rows = build_partner_customer_status_rows(
        attributions=[attribution], customer_map={10: customer}, engagements=[engagement], subscriptions=[subscription], payments=[payment],
        business_line_map={1: "代运营"}, product_map={2: "社媒代运营"}, as_of=date(2026, 8, 8),
    )

    assert rows[0]["cooperation_status"] == "active_paid"
    assert rows[0]["renewal_status"] == "active"
    assert rows[0]["next_due_at"] == date(2026, 9, 1)
    assert rows[0]["last_receipt_at"] == date(2026, 7, 30)
    assert "实收后自动计提" in rows[0]["commission_impact"]


def test_partner_status_stopped_lifecycle_overrides_stale_active_subscription():
    attribution = row(id=2, customer_id=20, engagement_id=102, effective_from=date(2026, 1, 1), effective_to=None, is_active=True)
    engagement = row(id=102, customer_id=20, business_line_id=1, product_id=2, package_name="投放套餐", status="stopped", billing_cycle="monthly")
    subscription = row(
        id=202, customer_id=20, engagement_id=102, package_name="投放套餐", status="active", auto_renew=True,
        next_payment_date=datetime(2026, 9, 1, tzinfo=timezone.utc), end_date=datetime(2026, 9, 1, tzinfo=timezone.utc), updated_at=None, created_at=None,
    )

    rows = build_partner_customer_status_rows(
        attributions=[attribution], customer_map={}, engagements=[engagement], subscriptions=[subscription], payments=[], as_of=date(2026, 8, 8),
    )

    assert rows[0]["cooperation_status"] == "stopped"
    assert rows[0]["renewal_status"] == "stopped"
    assert rows[0]["next_due_at"] is None
    assert rows[0]["commission_impact"] == "停止后不再新增续费分润"


def test_historical_attribution_does_not_expose_current_status_or_receipts():
    attribution = row(id=3, customer_id=30, engagement_id=None, effective_from=date(2026, 1, 1), effective_to=date(2026, 6, 30), is_active=False)
    engagement = row(id=103, customer_id=30, business_line_id=1, product_id=2, package_name="基础套餐", status="active_paid", billing_cycle="monthly")
    payment = service_payment(payment_id=303, customer_id=30, engagement_id=103, payment_date=date(2026, 8, 1), coverage_end=date(2026, 9, 1))

    rows = build_partner_customer_status_rows(
        attributions=[attribution], customer_map={}, engagements=[engagement], subscriptions=[], payments=[payment], as_of=date(2026, 8, 8),
    )

    assert rows[0]["cooperation_status"] == "historical"
    assert rows[0]["renewal_status"] == "historical"
    assert rows[0]["last_receipt_at"] is None
    assert rows[0]["next_due_at"] is None
    assert rows[0]["commission_impact"] == "历史归属，仅保留历史分润"


def test_partner_summary_counts_unique_customers_and_renewal_attention():
    summary = partner_status_summary([
        {"customer_id": 1, "is_active": True, "cooperation_status": "active_paid", "renewal_status": "expiring_soon"},
        {"customer_id": 1, "is_active": True, "cooperation_status": "active_paid", "renewal_status": "active"},
        {"customer_id": 2, "is_active": True, "cooperation_status": "stopped", "renewal_status": "stopped"},
        {"customer_id": 4, "is_active": True, "cooperation_status": "active_paid", "renewal_status": "active"},
        {"customer_id": 4, "is_active": True, "cooperation_status": "stopped", "renewal_status": "stopped"},
        {"customer_id": 3, "is_active": False, "cooperation_status": "historical", "renewal_status": "historical"},
    ])

    assert summary == {"cooperation_customer_count": 2, "renewal_attention_count": 1, "stopped_customer_count": 1}
