import json
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import and_, inspect, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.commissions import (
    CommissionAgreement,
    CommissionEntry,
    CustomerCommissionAttribution,
    SalesPartner,
)
from models.deals import Deals
from models.finance_refunds import FinanceRefund
from models.management_decisions import CustomerEngagement
from models.opportunities import Opportunities
from models.payments import Payments
from models.subscriptions import Subscriptions


DEFAULT_DECAY = {0: 1.0, 1: 0.8, 2: 0.6, 3: 0.4, 4: 0.25, 5: 0.1, 6: 0.0}
LOCKED_STATUSES = {"confirmed", "payable", "paid", "reversed"}


async def commission_ledger_available(db: AsyncSession) -> bool:
    connection = await db.connection()
    return bool(await connection.run_sync(lambda sync_connection: inspect(sync_connection).has_table("commission_entries")))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def money(value: float) -> float:
    return round(float(value or 0), 2)


def eligible_service_amount(payment: Payments) -> float:
    """Only service revenue is commissionable; ad recharge remains client funds."""
    if (payment.income_type or "").strip().lower() == "ads_fee":
        return 0.0
    paid = max(money(payment.amount_paid), 0)
    ads = max(money(payment.ads_recharge_amount or 0), 0)
    if payment.management_amount is not None:
        return min(max(money(payment.management_amount), 0), paid)
    return max(money(paid - ads), 0)


def _as_date(value: datetime | date) -> date:
    return value.date() if isinstance(value, datetime) else value


def _month_gap(earlier: datetime, later: datetime) -> int:
    return max((later.year - earlier.year) * 12 + later.month - earlier.month, 0)


def _decay_map(raw: str) -> dict[int, float]:
    try:
        value = json.loads(raw)
        parsed = {int(key): float(rate) for key, rate in value.items()}
        return parsed or DEFAULT_DECAY
    except (TypeError, ValueError, json.JSONDecodeError):
        return DEFAULT_DECAY


def _decay_multiplier(agreement: CommissionAgreement, inactivity_months: int) -> float:
    mapping = _decay_map(agreement.activity_decay_json)
    key = min(max(inactivity_months, 0), max(mapping))
    while key not in mapping and key > 0:
        key -= 1
    return max(min(float(mapping.get(key, 0)), 1), 0)


async def _attributions_for_payment(db: AsyncSession, payment: Payments) -> list[CustomerCommissionAttribution]:
    payment_day = _as_date(payment.payment_date or payment.created_at or utcnow())
    statement = select(CustomerCommissionAttribution).where(
            CustomerCommissionAttribution.customer_id == payment.customer_id,
            CustomerCommissionAttribution.effective_from <= payment_day,
            or_(
                CustomerCommissionAttribution.effective_to.is_(None),
                CustomerCommissionAttribution.effective_to >= payment_day,
            ),
        )
    if payment.engagement_id:
        statement = statement.where(or_(
            CustomerCommissionAttribution.engagement_id == payment.engagement_id,
            CustomerCommissionAttribution.engagement_id.is_(None),
        )).order_by(
            CustomerCommissionAttribution.engagement_id.desc(),
            CustomerCommissionAttribution.effective_from.desc(),
            CustomerCommissionAttribution.id.desc(),
        )
    else:
        # Never guess between project-specific owners when an old payment has no project scope.
        statement = statement.where(CustomerCommissionAttribution.engagement_id.is_(None)).order_by(
            CustomerCommissionAttribution.effective_from.desc(), CustomerCommissionAttribution.id.desc()
        )
    rows = (await db.scalars(statement)).all()
    # A customer/project may only have one primary commission owner for a date.
    primary = [row for row in rows if row.attribution_role == "primary"]
    return primary[:1] if primary else rows[:1]


async def _agreement_for(
    db: AsyncSession,
    attribution: CustomerCommissionAttribution,
    payment: Payments,
    occurred_at: datetime,
) -> Optional[CommissionAgreement]:
    day = _as_date(occurred_at)
    engagement = await db.get(CustomerEngagement, attribution.engagement_id) if attribution.engagement_id else None
    statement = select(CommissionAgreement).where(
        CommissionAgreement.partner_id == attribution.partner_id,
        CommissionAgreement.status == "active",
        CommissionAgreement.effective_from <= day,
        or_(CommissionAgreement.effective_to.is_(None), CommissionAgreement.effective_to >= day),
        or_(CommissionAgreement.business_line_id.is_(None), CommissionAgreement.business_line_id == (payment.business_line_id or getattr(engagement, "business_line_id", None))),
        or_(CommissionAgreement.product_id.is_(None), CommissionAgreement.product_id == (payment.product_id or getattr(engagement, "product_id", None))),
    ).order_by(
        CommissionAgreement.product_id.desc(),
        CommissionAgreement.business_line_id.desc(),
        CommissionAgreement.version.desc(),
    )
    return await db.scalar(statement.limit(1))


async def _is_first_service_payment(db: AsyncSession, payment: Payments) -> bool:
    occurred = payment.payment_date or payment.created_at or utcnow()
    statement = select(Payments).where(
            Payments.customer_id == payment.customer_id,
            Payments.id != payment.id,
            or_(Payments.payment_date < occurred, and_(Payments.payment_date == occurred, Payments.id < payment.id)),
        )
    # A customer's first paid project in another business line counts as a new
    # acquisition; plan changes within the same line remain renewals/upgrades.
    if payment.business_line_id:
        statement = statement.where(Payments.business_line_id == payment.business_line_id)
    elif payment.engagement_id:
        statement = statement.where(Payments.engagement_id == payment.engagement_id)
    rows = (await db.scalars(statement.order_by(Payments.payment_date, Payments.id))).all()
    return not any(eligible_service_amount(row) > 0 for row in rows)


async def _resolve_payment_scope(db: AsyncSession, payment: Payments) -> None:
    if payment.engagement_id:
        engagement = await db.get(CustomerEngagement, payment.engagement_id)
        if engagement:
            payment.business_line_id = payment.business_line_id or engagement.business_line_id
            payment.product_id = payment.product_id or engagement.product_id
            return
    if payment.source_deal_id:
        deal = await db.get(Deals, payment.source_deal_id)
        if deal:
            subscription = await db.scalar(
                select(Subscriptions).where(Subscriptions.deal_id == deal.id).order_by(Subscriptions.id.desc()).limit(1)
            )
            if subscription:
                payment.engagement_id = subscription.engagement_id
                payment.business_line_id = subscription.business_line_id
                payment.product_id = subscription.product_id
                return
            if deal.opportunity_id:
                opportunity = await db.get(Opportunities, deal.opportunity_id)
                if opportunity:
                    payment.business_line_id = opportunity.business_line_id
                    payment.product_id = opportunity.product_id
                    return
    product_label = (payment.product_name or "").strip().lower()
    if not product_label:
        return
    subscriptions = (await db.scalars(
        select(Subscriptions).where(Subscriptions.customer_id == payment.customer_id).order_by(Subscriptions.id.desc())
    )).all()
    for subscription in subscriptions:
        package_label = (subscription.package_name or "").strip().lower()
        if package_label and (package_label == product_label or package_label in product_label or product_label in package_label):
            payment.engagement_id = subscription.engagement_id
            payment.business_line_id = subscription.business_line_id
            payment.product_id = subscription.product_id
            return


async def _inactivity_months(db: AsyncSession, partner_id: int, occurred_at: datetime) -> int:
    latest = await db.scalar(
        select(CommissionEntry.occurred_at).where(
            CommissionEntry.partner_id == partner_id,
            CommissionEntry.entry_type == "first_order",
            CommissionEntry.refund_id.is_(None),
            CommissionEntry.occurred_at <= occurred_at,
        ).order_by(CommissionEntry.occurred_at.desc()).limit(1)
    )
    return _month_gap(latest, occurred_at) if latest else 0


async def sync_payment_commission(db: AsyncSession, payment: Payments) -> Optional[CommissionEntry]:
    service_amount = eligible_service_amount(payment)
    if service_amount <= 0 or not (payment.payment_date or payment.created_at):
        return None

    occurred_at = payment.payment_date or payment.created_at
    await _resolve_payment_scope(db, payment)
    attributions = await _attributions_for_payment(db, payment)
    if not attributions:
        return None
    attribution = attributions[0]
    partner = await db.get(SalesPartner, attribution.partner_id)
    if not partner:
        return None
    if partner.stopped_at and _as_date(occurred_at) > partner.stopped_at:
        return None

    agreement = await _agreement_for(db, attribution, payment, occurred_at)
    if not agreement:
        return None

    key = f"payment:{payment.id}:partner:{partner.id}"
    existing = await db.scalar(select(CommissionEntry).where(CommissionEntry.idempotency_key == key))
    if existing and existing.status in LOCKED_STATUSES:
        return existing

    first_order = await _is_first_service_payment(db, payment)
    entry_type = "first_order" if first_order else "renewal"
    inactivity_months = 0 if first_order else await _inactivity_months(db, partner.id, occurred_at)
    multiplier = 1.0 if first_order else _decay_multiplier(agreement, inactivity_months)
    rate = agreement.first_order_rate if first_order else agreement.renewal_rate
    amount = money(service_amount * rate * multiplier)
    snapshot = {
        "agreement_version": agreement.version,
        "partner_status": partner.status,
        "calculation": "eligible_service_amount * contract_rate * activity_multiplier",
        "ad_recharge_excluded": True,
        "first_order": first_order,
        "decay_schedule": _decay_map(agreement.activity_decay_json),
        "refund_guard_days": agreement.refund_guard_days,
    }
    values = dict(
        partner_id=partner.id,
        agreement_id=agreement.id,
        attribution_id=attribution.id,
        customer_id=payment.customer_id,
        engagement_id=payment.engagement_id or attribution.engagement_id,
        payment_id=payment.id,
        refund_id=None,
        original_entry_id=None,
        entry_type=entry_type,
        status="pending_confirmation",
        service_month=occurred_at.strftime("%Y-%m"),
        occurred_at=occurred_at,
        currency=(payment.currency or "USD").upper(),
        gross_receipt_amount=money(payment.amount_paid),
        eligible_service_amount=service_amount,
        contract_rate=rate,
        inactivity_months=inactivity_months,
        activity_multiplier=multiplier,
        commission_amount=amount,
        snapshot_json=json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
        idempotency_key=key,
    )
    if existing:
        for name, value in values.items():
            setattr(existing, name, value)
        return existing
    entry = CommissionEntry(**values)
    db.add(entry)
    await db.flush()
    return entry


async def sync_refund_commission(db: AsyncSession, refund: FinanceRefund) -> list[CommissionEntry]:
    if refund.status != "completed":
        return []
    payment = await db.get(Payments, refund.payment_id)
    if not payment or money(payment.amount_paid) <= 0:
        return []
    originals = (await db.scalars(
        select(CommissionEntry).where(
            CommissionEntry.payment_id == payment.id,
            CommissionEntry.refund_id.is_(None),
            CommissionEntry.entry_type.in_(("first_order", "renewal")),
        )
    )).all()
    results: list[CommissionEntry] = []
    ratio = min(max(money(refund.refund_amount) / money(payment.amount_paid), 0), 1)
    for original in originals:
        key = f"refund:{refund.id}:commission:{original.id}"
        existing = await db.scalar(select(CommissionEntry).where(CommissionEntry.idempotency_key == key))
        if existing:
            results.append(existing)
            continue
        amount = -money(original.commission_amount * ratio)
        snapshot = {
            "original_entry_id": original.id,
            "original_commission_amount": original.commission_amount,
            "refund_amount": money(refund.refund_amount),
            "original_receipt_amount": money(payment.amount_paid),
            "reversal_ratio": ratio,
            "calculation": "original_commission_amount * refund_ratio * -1",
        }
        reversal = CommissionEntry(
            partner_id=original.partner_id,
            agreement_id=original.agreement_id,
            attribution_id=original.attribution_id,
            customer_id=original.customer_id,
            engagement_id=original.engagement_id,
            payment_id=payment.id,
            refund_id=refund.id,
            original_entry_id=original.id,
            entry_type="refund_reversal",
            status="pending_confirmation",
            service_month=refund.refund_date.strftime("%Y-%m"),
            occurred_at=refund.refund_date,
            currency=original.currency,
            gross_receipt_amount=-money(refund.refund_amount),
            eligible_service_amount=-money(original.eligible_service_amount * ratio),
            contract_rate=original.contract_rate,
            inactivity_months=original.inactivity_months,
            activity_multiplier=original.activity_multiplier,
            commission_amount=amount,
            snapshot_json=json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            idempotency_key=key,
        )
        db.add(reversal)
        await db.flush()
        results.append(reversal)
    return results


async def scan_commissions(db: AsyncSession, *, commit: bool = True) -> dict[str, int]:
    created_before = len((await db.scalars(select(CommissionEntry.id))).all())
    payments = (await db.scalars(select(Payments).order_by(Payments.payment_date, Payments.id))).all()
    for payment in payments:
        await sync_payment_commission(db, payment)
    refunds = (await db.scalars(select(FinanceRefund).where(FinanceRefund.status == "completed").order_by(FinanceRefund.refund_date, FinanceRefund.id))).all()
    for refund in refunds:
        await sync_refund_commission(db, refund)
    if commit:
        await db.commit()
    else:
        await db.flush()
    created_after = len((await db.scalars(select(CommissionEntry.id))).all())
    return {"payments_scanned": len(payments), "refunds_scanned": len(refunds), "entries_created": max(created_after - created_before, 0)}
