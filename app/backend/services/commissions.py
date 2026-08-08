import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, inspect, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.commissions import (
    CommissionAgreement,
    CommissionEntry,
    CustomerCommissionAttribution,
    SalesPartner,
)
from models.customers import Customers
from models.deals import Deals
from models.finance_refunds import FinanceRefund
from models.management_decisions import CustomerEngagement
from models.opportunities import Opportunities
from models.payments import Payments
from models.subscriptions import Subscriptions


DEFAULT_DECAY = {0: 1.0, 1: 0.8, 2: 0.6, 3: 0.4, 4: 0.25, 5: 0.1, 6: 0.0}
LOCKED_STATUSES = {"confirmed", "payable", "paid", "reversed"}
DIRECT_PARTNER_CODE = "DIRECT-T24"
DIRECT_PARTNER_NAME = "T24 公司直营"


async def commission_ledger_available(db: AsyncSession) -> bool:
    connection = await db.connection()
    return bool(await connection.run_sync(lambda sync_connection: inspect(sync_connection).has_table("commission_entries")))


async def ensure_company_direct_partner(
    db: AsyncSession,
    *,
    actor_id: str | None = None,
    actor_name: str | None = None,
) -> SalesPartner:
    """Return the system-owned direct channel, creating it when first needed."""
    partner = await db.scalar(
        select(SalesPartner).where(SalesPartner.partner_code == DIRECT_PARTNER_CODE).limit(1)
    )
    if partner:
        if partner.partner_type != "direct":
            raise ValueError(f"渠道编号 {DIRECT_PARTNER_CODE} 已被非直营渠道占用")
        if partner.status != "active":
            partner.status = "active"
            partner.stopped_at = None
        return partner

    partner = SalesPartner(
        partner_code=DIRECT_PARTNER_CODE,
        name=DIRECT_PARTNER_NAME,
        partner_type="direct",
        status="active",
        joined_at=date(2026, 1, 1),
        notes="系统直营归属；仅用于客户来源和归属闭环，不产生渠道佣金。",
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
    db.add(partner)
    await db.flush()
    return partner


async def assign_customer_commission_owner(
    db: AsyncSession,
    *,
    customer_id: int,
    partner_id: int,
    effective_from: date,
    engagement_id: int | None = None,
    source_note: str | None = None,
    actor_id: str | None = None,
    actor_name: str | None = None,
) -> CustomerCommissionAttribution:
    """Create a single effective-dated primary owner while preserving history."""
    partner = await db.get(SalesPartner, partner_id)
    if not partner or partner.status != "active":
        raise ValueError("只能归属给正常合作中的渠道")

    current = (await db.scalars(select(CustomerCommissionAttribution).where(
        CustomerCommissionAttribution.customer_id == customer_id,
        CustomerCommissionAttribution.engagement_id.is_(engagement_id)
        if engagement_id is None else CustomerCommissionAttribution.engagement_id == engagement_id,
        CustomerCommissionAttribution.attribution_role == "primary",
        CustomerCommissionAttribution.is_active.is_(True),
    ))).all()
    for link in current:
        if link.partner_id == partner_id:
            if source_note and not link.source_note:
                link.source_note = source_note
            return link
        if link.effective_from >= effective_from:
            raise ValueError("当前归属的生效日期不早于新归属，请先核对日期")
        link.effective_to = effective_from - timedelta(days=1)
        link.is_active = False

    row = CustomerCommissionAttribution(
        customer_id=customer_id,
        engagement_id=engagement_id,
        partner_id=partner_id,
        attribution_role="primary",
        effective_from=effective_from,
        is_active=True,
        source_note=source_note,
        created_by_id=actor_id,
        created_by_name=actor_name,
    )
    db.add(row)
    await db.flush()
    return row


async def auto_assign_new_customer(
    db: AsyncSession,
    *,
    customer_id: int,
    sales_employee_id: int | None,
    effective_from: date,
    explicit_partner_id: int | None = None,
    actor_id: str | None = None,
    actor_name: str | None = None,
) -> CustomerCommissionAttribution | None:
    """Assign a new customer to an explicit/employee channel, otherwise direct."""
    if not await commission_ledger_available(db):
        return None
    partner = await db.get(SalesPartner, explicit_partner_id) if explicit_partner_id else None
    if explicit_partner_id and (not partner or partner.status != "active"):
        raise ValueError("所选分润渠道不存在或已停止合作")
    if not partner and sales_employee_id:
        partner = await db.scalar(select(SalesPartner).where(
            SalesPartner.partner_type == "employee",
            SalesPartner.employee_id == sales_employee_id,
            SalesPartner.status == "active",
        ).order_by(SalesPartner.id.desc()).limit(1))
    if not partner:
        partner = await ensure_company_direct_partner(db, actor_id=actor_id, actor_name=actor_name)
    return await assign_customer_commission_owner(
        db,
        customer_id=customer_id,
        partner_id=partner.id,
        effective_from=effective_from,
        source_note="客户首次录入自动建立分润归属",
        actor_id=actor_id,
        actor_name=actor_name,
    )


async def transfer_partner_attributions_to_direct(
    db: AsyncSession,
    *,
    partner_id: int,
    stopped_at: date,
    actor_id: str | None = None,
    actor_name: str | None = None,
) -> int:
    """Close a stopped partner's active links and continue them as company direct."""
    direct = await ensure_company_direct_partner(db, actor_id=actor_id, actor_name=actor_name)
    links = (await db.scalars(select(CustomerCommissionAttribution).where(
        CustomerCommissionAttribution.partner_id == partner_id,
        CustomerCommissionAttribution.is_active.is_(True),
    ))).all()
    transferred = 0
    for link in links:
        link.effective_to = stopped_at
        link.is_active = False
        await assign_customer_commission_owner(
            db,
            customer_id=link.customer_id,
            engagement_id=link.engagement_id,
            partner_id=direct.id,
            effective_from=stopped_at + timedelta(days=1),
            source_note=f"原渠道停止合作后自动转公司直营；原归属 #{link.id}",
            actor_id=actor_id,
            actor_name=actor_name,
        )
        transferred += 1
    return transferred


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
        CommissionAgreement.status.in_(("active", "expired")),
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
    if partner.partner_type == "direct":
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


async def commission_data_quality(db: AsyncSession) -> dict:
    """Return actionable attribution/agreement gaps without changing accounting data."""
    if not await commission_ledger_available(db):
        return {"issues": [], "issue_count": 0, "covered_count": 0, "coverage_rate": 100.0}

    customers = (await db.scalars(select(Customers))).all()
    customer_names = {row.id: row.business_name for row in customers}
    partners = (await db.scalars(select(SalesPartner))).all()
    partner_map = {row.id: row for row in partners}
    issues: list[dict] = []
    covered_keys: set[tuple[str, int]] = set()
    examined_keys: set[tuple[str, int]] = set()

    today = utcnow().date()
    for partner in partners:
        if partner.status != "active" or partner.partner_type == "direct":
            continue
        agreement = await db.scalar(select(CommissionAgreement.id).where(
            CommissionAgreement.partner_id == partner.id,
            CommissionAgreement.status == "active",
            CommissionAgreement.effective_from <= today,
            or_(CommissionAgreement.effective_to.is_(None), CommissionAgreement.effective_to >= today),
        ).limit(1))
        if not agreement:
            issues.append({
                "key": f"partner:{partner.id}:agreement",
                "type": "partner_without_agreement",
                "severity": "high",
                "partner_id": partner.id,
                "partner_name": partner.name,
                "title": "合作渠道缺少当前协议",
                "description": f"{partner.name} 当前没有生效的分润协议，相关实收无法计佣。",
            })

    payments = (await db.scalars(select(Payments).order_by(Payments.payment_date, Payments.id))).all()
    accounted_payment_ids = set((await db.scalars(select(CommissionEntry.payment_id).where(
        CommissionEntry.refund_id.is_(None)
    ))).all())
    for payment in payments:
        if eligible_service_amount(payment) <= 0 or not (payment.payment_date or payment.created_at):
            continue
        key = ("payment", payment.id)
        examined_keys.add(key)
        if payment.id in accounted_payment_ids:
            covered_keys.add(key)
            continue
        attributions = await _attributions_for_payment(db, payment)
        if not attributions:
            issues.append({
                "key": f"payment:{payment.id}:attribution",
                "type": "unattributed_payment",
                "severity": "high",
                "customer_id": payment.customer_id,
                "customer_name": customer_names.get(payment.customer_id) or payment.customer_name,
                "engagement_id": payment.engagement_id,
                "payment_id": payment.id,
                "title": "服务实收尚未归属渠道",
                "description": f"收款 #{payment.id} 已到账，但没有找到对应客户/项目的分润归属。",
            })
            continue
        attribution = attributions[0]
        partner = partner_map.get(attribution.partner_id)
        if partner and partner.partner_type == "direct":
            covered_keys.add(key)
            continue
        agreement = await _agreement_for(db, attribution, payment, payment.payment_date or payment.created_at)
        if not agreement:
            issues.append({
                "key": f"payment:{payment.id}:agreement",
                "type": "payment_without_agreement",
                "severity": "high",
                "customer_id": payment.customer_id,
                "customer_name": customer_names.get(payment.customer_id) or payment.customer_name,
                "engagement_id": payment.engagement_id,
                "payment_id": payment.id,
                "partner_id": attribution.partner_id,
                "partner_name": partner.name if partner else None,
                "title": "归属渠道缺少适用协议",
                "description": f"收款 #{payment.id} 已有归属，但付款日期或产品范围没有匹配的协议版本。",
            })
            continue
        covered_keys.add(key)

    active_engagements = (await db.scalars(select(CustomerEngagement).where(
        CustomerEngagement.status.in_(("active_paid", "reactivated"))
    ))).all()
    for engagement in active_engagements:
        key = ("engagement", engagement.id)
        examined_keys.add(key)
        attribution = await db.scalar(select(CustomerCommissionAttribution).where(
            CustomerCommissionAttribution.customer_id == engagement.customer_id,
            or_(
                CustomerCommissionAttribution.engagement_id == engagement.id,
                CustomerCommissionAttribution.engagement_id.is_(None),
            ),
            CustomerCommissionAttribution.is_active.is_(True),
            CustomerCommissionAttribution.effective_from <= today,
        ).order_by(
            CustomerCommissionAttribution.engagement_id.desc(),
            CustomerCommissionAttribution.effective_from.desc(),
        ).limit(1))
        if attribution:
            covered_keys.add(key)
            continue
        issues.append({
            "key": f"engagement:{engagement.id}:attribution",
            "type": "unattributed_engagement",
            "severity": "medium",
            "customer_id": engagement.customer_id,
            "customer_name": customer_names.get(engagement.customer_id),
            "engagement_id": engagement.id,
            "title": "付费项目尚未归属渠道",
            "description": f"项目 #{engagement.id} 处于付费合作中，但没有当前分润归属。",
        })

    examined_count = len(examined_keys)
    coverage_rate = round((len(covered_keys) / examined_count * 100) if examined_count else 100.0, 1)
    return {
        "issues": issues,
        "issue_count": len(issues),
        "high_count": sum(row["severity"] == "high" for row in issues),
        "covered_count": len(covered_keys),
        "examined_count": examined_count,
        "coverage_rate": coverage_rate,
    }


async def preview_bulk_customer_attributions(db: AsyncSession) -> dict:
    """Build a deterministic, non-mutating plan for historical attribution gaps."""
    quality = await commission_data_quality(db)
    attribution_issues = [
        row for row in quality["issues"]
        if row["type"] in {"unattributed_payment", "unattributed_engagement"}
        and row.get("customer_id")
    ]

    customers = (await db.scalars(select(Customers))).all()
    customer_map = {row.id: row for row in customers}
    engagements = (await db.scalars(select(CustomerEngagement))).all()
    engagement_map = {row.id: row for row in engagements}
    engagements_by_customer: dict[int, list[CustomerEngagement]] = {}
    for row in engagements:
        engagements_by_customer.setdefault(row.customer_id, []).append(row)
    payments = (await db.scalars(select(Payments))).all()
    payment_map = {row.id: row for row in payments}
    partners = (await db.scalars(select(SalesPartner))).all()
    direct_partner = next((row for row in partners if row.partner_code == DIRECT_PARTNER_CODE), None)
    employee_partners: dict[int, list[SalesPartner]] = {}
    for row in partners:
        if row.partner_type == "employee" and row.employee_id and row.status == "active":
            employee_partners.setdefault(row.employee_id, []).append(row)
    active_links = (await db.scalars(select(CustomerCommissionAttribution).where(
        CustomerCommissionAttribution.attribution_role == "primary",
        CustomerCommissionAttribution.is_active.is_(True),
    ))).all()

    targets: dict[tuple[int, int | None], dict] = {}
    for issue in attribution_issues:
        customer_id = int(issue["customer_id"])
        engagement_id = issue.get("engagement_id")
        key = (customer_id, int(engagement_id) if engagement_id else None)
        effective_from: date | None = None
        if issue.get("payment_id"):
            payment = payment_map.get(int(issue["payment_id"]))
            occurred_at = payment.payment_date or payment.created_at if payment else None
            effective_from = _as_date(occurred_at) if occurred_at else None
        if effective_from is None and engagement_id:
            engagement = engagement_map.get(int(engagement_id))
            if engagement and engagement.paid_started_at:
                effective_from = _as_date(engagement.paid_started_at)
        customer = customer_map.get(customer_id)
        if effective_from is None and customer and customer.created_at:
            effective_from = _as_date(customer.created_at)
        effective_from = effective_from or utcnow().date()

        target = targets.setdefault(key, {
            "customer_id": customer_id,
            "engagement_id": key[1],
            "effective_from": effective_from,
            "issue_keys": [],
        })
        target["effective_from"] = min(target["effective_from"], effective_from)
        target["issue_keys"].append(issue["key"])

    items: list[dict] = []
    for (customer_id, engagement_id), target in targets.items():
        customer = customer_map.get(customer_id)
        engagement = engagement_map.get(engagement_id) if engagement_id else None
        item = {
            **target,
            "customer_code": customer.customer_code if customer else None,
            "customer_name": customer.business_name if customer else f"客户 #{customer_id}",
            "engagement_name": engagement.package_name if engagement else None,
            "partner_id": None,
            "partner_name": None,
            "partner_type": None,
            "status": "ready",
            "basis": "",
        }

        covering_links = [
            row for row in active_links
            if row.customer_id == customer_id and (
                row.engagement_id == engagement_id
                or (engagement_id is not None and row.engagement_id is None)
            )
        ]
        if covering_links:
            item["status"] = "manual_review"
            item["basis"] = "已有较晚生效的归属，不能自动回溯旧收款日期"
            items.append(item)
            continue

        if engagement_id is None:
            project_links = [row for row in active_links if row.customer_id == customer_id and row.engagement_id is not None]
            if project_links:
                item["status"] = "manual_review"
                item["basis"] = "客户已有项目级归属，但旧收款未指定项目"
                items.append(item)
                continue

        employee_id = engagement.sales_employee_id if engagement and engagement.sales_employee_id else (
            customer.sales_employee_id if customer else None
        )
        if engagement_id is None:
            project_employee_ids = {
                row.sales_employee_id for row in engagements_by_customer.get(customer_id, [])
                if row.sales_employee_id
            }
            if employee_id and any(row_id != employee_id for row_id in project_employee_ids):
                item["status"] = "manual_review"
                item["basis"] = "客户下存在不同项目销售负责人，旧收款未指定项目"
                items.append(item)
                continue
            if not employee_id and len(project_employee_ids) == 1:
                employee_id = next(iter(project_employee_ids))
            elif not employee_id and len(project_employee_ids) > 1:
                item["status"] = "manual_review"
                item["basis"] = "客户下存在多个项目销售负责人，旧收款未指定项目"
                items.append(item)
                continue

        matches = employee_partners.get(employee_id, []) if employee_id else []
        if len(matches) > 1:
            item["status"] = "manual_review"
            item["basis"] = "同一员工匹配到多个合作中的内部销售渠道"
        elif matches:
            partner = matches[0]
            item.update({
                "partner_id": partner.id,
                "partner_name": partner.name,
                "partner_type": partner.partner_type,
                "basis": f"批量自动补齐：匹配客户/项目销售员工 #{employee_id}",
            })
        else:
            item.update({
                "partner_id": direct_partner.id if direct_partner else None,
                "partner_name": DIRECT_PARTNER_NAME,
                "partner_type": "direct",
                "basis": "批量自动补齐：没有可确认的合作渠道，归公司直营",
            })
        items.append(item)

    items.sort(key=lambda row: (row["status"] != "ready", row["customer_name"], row["engagement_id"] or 0))
    fingerprint_rows = [{
        "customer_id": row["customer_id"],
        "engagement_id": row["engagement_id"],
        "effective_from": row["effective_from"].isoformat(),
        "partner_id": row["partner_id"],
        "partner_type": row["partner_type"],
        "status": row["status"],
        "basis": row["basis"],
    } for row in items]
    preview_token = hashlib.sha256(
        json.dumps(fingerprint_rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    ready = [row for row in items if row["status"] == "ready"]
    return {
        "preview_token": preview_token,
        "source_issue_count": len(attribution_issues),
        "target_count": len(items),
        "ready_count": len(ready),
        "employee_count": sum(row["partner_type"] == "employee" for row in ready),
        "direct_count": sum(row["partner_type"] == "direct" for row in ready),
        "manual_review_count": sum(row["status"] == "manual_review" for row in items),
        "items": items,
    }


async def apply_bulk_customer_attributions(
    db: AsyncSession,
    *,
    preview_token: str,
    actor_id: str | None = None,
    actor_name: str | None = None,
) -> dict:
    """Apply exactly the last previewed ready rows; never overwrite active links."""
    preview = await preview_bulk_customer_attributions(db)
    if preview["preview_token"] != preview_token:
        raise ValueError("归属数据在预览后发生变化，请重新预览再确认")

    ready = [row for row in preview["items"] if row["status"] == "ready"]
    direct = None
    assigned = 0
    for item in ready:
        partner_id = item["partner_id"]
        if item["partner_type"] == "direct":
            if direct is None:
                direct = await ensure_company_direct_partner(
                    db, actor_id=actor_id, actor_name=actor_name
                )
            partner_id = direct.id
        await assign_customer_commission_owner(
            db,
            customer_id=item["customer_id"],
            engagement_id=item["engagement_id"],
            partner_id=partner_id,
            effective_from=item["effective_from"],
            source_note=item["basis"],
            actor_id=actor_id,
            actor_name=actor_name,
        )
        assigned += 1

    scan = await scan_commissions(db, commit=False)
    return {
        "assigned_count": assigned,
        "employee_count": preview["employee_count"],
        "direct_count": preview["direct_count"],
        "manual_review_count": preview["manual_review_count"],
        "entries_created": scan["entries_created"],
    }
