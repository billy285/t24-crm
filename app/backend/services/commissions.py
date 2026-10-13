import calendar
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func, inspect, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.commissions import (
    CommissionAgreement,
    CommissionEntry,
    CommissionStatusEvent,
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


def _next_service_month(start: date) -> date:
    year, month = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def _validate_attribution_rule(commission_mode, commission_start_date, first_service_start, history_basis):
    if commission_mode not in {"legacy", "first_month_then_renewal", "renewal_only", "none"}:
        raise ValueError("无效的计佣模式")
    if commission_mode == "legacy":
        return
    if not commission_start_date:
        raise ValueError("请明确计佣起始日期")
    if commission_mode == "first_month_then_renewal" and not first_service_start:
        raise ValueError("请明确首服务月起始日期")
    if commission_mode == "renewal_only":
        if not (history_basis or "").strip():
            raise ValueError("历史客户仅续费必须填写首期已结清依据")


async def preview_customer_commission_owner(
    db: AsyncSession, *, customer_id: int, partner_id: int, effective_from: date,
    engagement_id: int | None = None, commission_mode: str = "legacy",
    commission_start_date: date | None = None, first_service_start: date | None = None,
    history_basis: str | None = None, source_note: str | None = None,
) -> dict:
    """Read-only impact preview; existing financial entries are never adjusted here."""
    _validate_attribution_rule(commission_mode, commission_start_date, first_service_start, history_basis)
    links = list((await db.scalars(select(CustomerCommissionAttribution).where(
        CustomerCommissionAttribution.customer_id == customer_id,
        CustomerCommissionAttribution.engagement_id.is_(None) if engagement_id is None else CustomerCommissionAttribution.engagement_id == engagement_id,
        CustomerCommissionAttribution.is_active.is_(True),
        CustomerCommissionAttribution.attribution_role == "primary",
    ))).all())
    unchanged = any(
        link.partner_id == partner_id and link.effective_from == effective_from
        and (link.commission_mode or "legacy") == commission_mode
        and link.commission_start_date == commission_start_date
        and link.first_service_start == first_service_start
        and (link.history_basis or "").strip() == (history_basis or "").strip()
        for link in links
    )
    entries = list((await db.scalars(select(CommissionEntry).where(
        CommissionEntry.customer_id == customer_id,
        CommissionEntry.refund_id.is_(None),
        CommissionEntry.status.in_(("pending_confirmation", "estimated", "confirmed", "payable", "paid")),
    ))).all())
    affected = [row for row in entries if _as_date(row.occurred_at) >= effective_from and (
        engagement_id is None or row.engagement_id in (None, engagement_id)
    )] if not unchanged else []
    conflicts = [dict(entry_id=row.id, payment_id=row.payment_id, status=row.status, partner_id=row.partner_id)
                 for row in affected if row.status in {"confirmed", "payable", "paid"}]
    return {
        "blocked": bool(conflicts), "conflicts": conflicts,
        "affected_pending_count": sum(row.status in {"pending_confirmation", "estimated"} for row in affected),
        "legacy_count": sum((row.commission_mode or "legacy") == "legacy" for row in links),
        "message": "影响已确认佣金，请使用调整单或选择之后的生效日期" if conflicts else "保存将版本化归属；受影响的待确认条目会保留作废记录后重新生成",
    }


async def assign_customer_commission_owner(
    db: AsyncSession, *, customer_id: int, partner_id: int, effective_from: date,
    engagement_id: int | None = None, source_note: str | None = None,
    actor_id: str | None = None, actor_name: str | None = None,
    commission_mode: str = "legacy", commission_start_date: date | None = None,
    first_service_start: date | None = None, history_basis: str | None = None,
) -> CustomerCommissionAttribution:
    """Version the owner/rule; refuse changes to already recognized commission."""
    partner = await db.get(SalesPartner, partner_id)
    if not partner or partner.status != "active":
        raise ValueError("只能归属给正常合作中的渠道")
    await db.scalar(select(Customers).where(Customers.id == customer_id).with_for_update())
    preview = await preview_customer_commission_owner(
        db, customer_id=customer_id, partner_id=partner_id, effective_from=effective_from,
        engagement_id=engagement_id, commission_mode=commission_mode,
        commission_start_date=commission_start_date, first_service_start=first_service_start,
        history_basis=history_basis, source_note=source_note,
    )
    if preview["blocked"]:
        raise ValueError(preview["message"])
    current = list((await db.scalars(select(CustomerCommissionAttribution).where(
        CustomerCommissionAttribution.customer_id == customer_id,
        CustomerCommissionAttribution.engagement_id.is_(None) if engagement_id is None else CustomerCommissionAttribution.engagement_id == engagement_id,
        CustomerCommissionAttribution.attribution_role == "primary",
        CustomerCommissionAttribution.is_active.is_(True),
    ).with_for_update().execution_options(populate_existing=True))).all())
    for link in current:
        if (link.partner_id == partner_id and link.effective_from == effective_from
                and (link.commission_mode or "legacy") == commission_mode
                and link.commission_start_date == commission_start_date
                and link.first_service_start == first_service_start
                and (link.history_basis or "").strip() == (history_basis or "").strip()):
            return link
        if link.effective_from > effective_from:
            raise ValueError("新归属生效日期不能早于现有归属；请先核对日期")
        link.effective_to = effective_from - timedelta(days=1)
        link.is_active = False
    # Cancel only unrecognized candidates. Keep immutable entries/events as proof.
    pending = list((await db.scalars(select(CommissionEntry).where(
        CommissionEntry.customer_id == customer_id,
        CommissionEntry.refund_id.is_(None),
        CommissionEntry.status.in_(("pending_confirmation", "estimated")),
    ).with_for_update().execution_options(populate_existing=True))).all())
    for entry in pending:
        if _as_date(entry.occurred_at) >= effective_from and (engagement_id is None or entry.engagement_id in (None, engagement_id)):
            previous = entry.status
            entry.status = "reversed"
            db.add(CommissionStatusEvent(commission_entry_id=entry.id, from_status=previous, to_status="reversed",
                reason="归属或计佣规则版本变更，旧待确认候选作废", actor_id=actor_id, actor_name=actor_name))
            # Any unrecognized refund candidate also belongs to the superseded rule.
            reversals = (await db.scalars(select(CommissionEntry).where(
                CommissionEntry.original_entry_id == entry.id,
                CommissionEntry.status.in_(("pending_confirmation", "estimated")),
            ))).all()
            for reversal in reversals:
                reversal.status = "reversed"
                db.add(CommissionStatusEvent(commission_entry_id=reversal.id, from_status="pending_confirmation", to_status="reversed",
                    reason="原待确认佣金已因归属变更作废", actor_id=actor_id, actor_name=actor_name))
    row = CustomerCommissionAttribution(
        customer_id=customer_id, engagement_id=engagement_id, partner_id=partner_id,
        attribution_role="primary", effective_from=effective_from, is_active=True,
        source_note=source_note, created_by_id=actor_id, created_by_name=actor_name,
        commission_mode=commission_mode, commission_start_date=commission_start_date,
        first_service_start=first_service_start, history_basis=(history_basis or "").strip() or None,
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
            CustomerCommissionAttribution.engagement_id.desc().nullslast(),
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
        CommissionAgreement.product_id.desc().nullslast(),
        CommissionAgreement.business_line_id.desc().nullslast(),
        CommissionAgreement.version.desc(),
    )
    return await db.scalar(statement.limit(1))


async def _is_first_service_payment(db: AsyncSession, payment: Payments) -> bool:
    occurred = payment.payment_date or payment.created_at or utcnow()
    statement = select(Payments).where(
            Payments.customer_id == payment.customer_id,
            Payments.id != payment.id,
            or_(func.coalesce(Payments.payment_date, Payments.created_at) < occurred, and_(func.coalesce(Payments.payment_date, Payments.created_at) == occurred, Payments.id < payment.id)),
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


def _entry_snapshot(entry: CommissionEntry) -> dict:
    try:
        return json.loads(entry.snapshot_json or "{}")
    except (ValueError, TypeError):
        return {}


def _service_segments(payment: Payments, attribution: CustomerCommissionAttribution, agreement: CommissionAgreement) -> tuple[list[dict], list[str]]:
    """Commission periods are separate from the cash-accounting service_month column."""
    mode = attribution.commission_mode or "legacy"
    if mode == "none":
        return [], []
    if mode == "legacy":
        return [], ["历史归属尚未确认计佣模式、首服务月和计佣起始日期"]
    try:
        _validate_attribution_rule(mode, attribution.commission_start_date, attribution.first_service_start, attribution.history_basis)
    except ValueError as exc:
        return [], [str(exc)]
    if agreement.calculation_version != "service_month_v2" or agreement.renewal_policy != "fixed":
        return [], ["当前适用协议仍是历史规则，请明确新固定续费协议的生效日期"]
    if not payment.payment_date:
        return [], ["收款缺少实际到账日期，不能确定计佣入账月"]
    first_start = attribution.first_service_start
    first_end = _next_service_month(first_start) if mode == "first_month_then_renewal" else None
    origin = attribution.commission_start_date
    amount = eligible_service_amount(payment)
    coverage_start = _as_date(payment.coverage_start) if payment.coverage_start else None
    coverage_end = _as_date(payment.coverage_end) if payment.coverage_end else None
    cycle = (payment.billing_cycle or "").strip().lower()
    if bool(coverage_start) != bool(coverage_end) or (coverage_start and coverage_end <= coverage_start):
        return [], ["服务覆盖日期不完整或结束日期不晚于开始日期，请核对"]
    if not coverage_start:
        # Never allocate annual/quarterly/multi-month receipts entirely to month one.
        if cycle not in {"", "monthly", "month", "月", "月付", "每月", "按月", "once", "one_time", "one-time", "一次性"}:
            return [], ["季付、年付或不明确周期的收款需要填写完整服务覆盖日期后计佣"]
        day = _as_date(payment.payment_date)
        if day < origin:
            return [], []
        if first_end and day < first_start:
            return [], ["收款日期早于确认的首服务月起点，请核对服务周期"]
        entry_type = "renewal" if mode == "renewal_only" or day >= first_end else "first_order"
        return [dict(entry_type=entry_type, service_period_start=day.isoformat(), service_period_end=None,
            allocated_service_amount=amount, allocation_basis="receipt_date_fallback", allocated_days=None,
            coverage_start=None, coverage_end=None, excluded_service_amount=0.0)], []
    if first_end and coverage_start < first_start:
        return [], ["服务覆盖开始日期早于确认的首次服务日期，请核对历史起点"]
    boundaries = sorted({coverage_start, coverage_end, *[day for day in (origin, first_end) if day and coverage_start < day < coverage_end]})
    total_days = (coverage_end - coverage_start).days
    allocated = 0.0
    parts = []
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        part_amount = money(amount - allocated) if index == len(boundaries) - 2 else money(amount * (end - start).days / total_days)
        allocated = money(allocated + part_amount)
        parts.append((start, end, part_amount))
    excluded = money(sum(value for start, end, value in parts if start < origin))
    segments = []
    for start, end, value in parts:
        if start < origin or value <= 0:
            continue
        segments.append(dict(entry_type="renewal" if mode == "renewal_only" or start >= first_end else "first_order",
            service_period_start=start.isoformat(), service_period_end=end.isoformat(), allocated_service_amount=value,
            allocated_days=(end-start).days, allocation_basis="coverage_days", coverage_start=coverage_start.isoformat(),
            coverage_end=coverage_end.isoformat(), excluded_service_amount=excluded))
    return segments, []


async def preview_payment_commission(db: AsyncSession, payment: Payments) -> dict:
    """No writes: previews use resolved IDs already on the payment, never mutate scope."""
    result = {"payment_id": payment.id, "segments": [], "issues": [], "eligible_service_amount": eligible_service_amount(payment)}
    if result["eligible_service_amount"] <= 0:
        return result
    attributions = await _attributions_for_payment(db, payment)
    if not attributions:
        result["issues"] = ["未找到付款日期对应的客户或项目归属"]
        return result
    attribution = attributions[0]
    partner = await db.get(SalesPartner, attribution.partner_id)
    if not partner or partner.partner_type == "direct" or attribution.commission_mode == "none":
        return result
    agreement = await _agreement_for(db, attribution, payment, payment.payment_date or payment.created_at or utcnow())
    if not agreement:
        result["issues"] = ["付款日期未匹配到适用的渠道协议"]
        return result
    segments, issues = _service_segments(payment, attribution, agreement)
    result.update(partner_id=attribution.partner_id, attribution_id=attribution.id, agreement_id=agreement.id,
                  commission_mode=attribution.commission_mode, first_service_start=attribution.first_service_start,
                  commission_start_date=attribution.commission_start_date, segments=segments, issues=issues)
    for segment in segments:
        segment["contract_rate"] = agreement.first_order_rate if segment["entry_type"] == "first_order" else agreement.renewal_rate
        segment["activity_multiplier"] = 1.0
        segment["commission_amount"] = money(segment["allocated_service_amount"] * segment["contract_rate"])
    return result


async def validate_commission_entry_confirmation(db: AsyncSession, entry: CommissionEntry) -> None:
    """Reject duplicates/stale candidates without rewriting locked financial history."""
    await db.scalar(select(Customers).where(Customers.id == entry.customer_id).with_for_update())
    payment = await db.scalar(select(Payments).where(Payments.id == entry.payment_id).with_for_update().execution_options(populate_existing=True))
    if not payment:
        raise ValueError("原收款不存在，不能确认佣金")
    originals = list((await db.scalars(select(CommissionEntry).where(
        CommissionEntry.payment_id == entry.payment_id, CommissionEntry.refund_id.is_(None),
        CommissionEntry.status.in_(("confirmed", "payable", "paid")),
    ).with_for_update().execution_options(populate_existing=True))).all())
    if entry.entry_type == "refund_reversal":
        original = await db.get(CommissionEntry, entry.original_entry_id)
        if not original or original.status not in {"confirmed", "payable", "paid"}:
            raise ValueError("原佣金尚未确认或已作废，退款冲回不能单独确认")
        refund = await db.get(FinanceRefund, entry.refund_id)
        if not refund or refund.status != "completed":
            raise ValueError("原退款不是已完成状态")
        reversals = (await db.scalars(select(CommissionEntry).where(
            CommissionEntry.original_entry_id == original.id,
            CommissionEntry.status.in_(("confirmed", "payable", "paid")),
            CommissionEntry.id != entry.id,
        ))).all()
        if abs(money(sum(row.commission_amount for row in reversals) + entry.commission_amount)) > abs(original.commission_amount) + .001:
            raise ValueError("累计退款冲回超过原已确认佣金，请核对")
        return
    attributions = await _attributions_for_payment(db, payment)
    if not attributions or attributions[0].id != entry.attribution_id or attributions[0].partner_id != entry.partner_id:
        raise ValueError("客户归属已变化，不能确认旧渠道佣金；请重新扫描核对")
    for other in originals:
        if other.id == entry.id:
            continue
        if other.partner_id != entry.partner_id or other.attribution_id != entry.attribution_id:
            raise ValueError("同一收款已有其他渠道的已确认佣金，请先使用调整流程处理")
        left, right = _entry_snapshot(entry), _entry_snapshot(other)
        if left.get("calculation_version") != "service_month_v2" or right.get("calculation_version") != "service_month_v2":
            raise ValueError("同一收款已有已确认佣金，不能重复确认")
        a, b = left.get("service_period_start"), left.get("service_period_end")
        c, d = right.get("service_period_start"), right.get("service_period_end")
        if not (a and b and c and d and (b <= c or d <= a)):
            raise ValueError("同一收款服务区间已有已确认佣金，不能重复确认")
    snapshot = _entry_snapshot(entry)
    if snapshot.get("calculation_version") != "service_month_v2":
        raise ValueError("历史待确认佣金需先核对计佣规则并重新扫描，不能直接按旧首单规则确认")
    if snapshot.get("calculation_version") == "service_month_v2":
        preview = await preview_payment_commission(db, payment)
        matched = next((segment for segment in preview["segments"] if segment["service_period_start"] == snapshot.get("service_period_start")
                       and segment["service_period_end"] == snapshot.get("service_period_end") and segment["entry_type"] == entry.entry_type), None)
        if (preview["issues"] or preview.get("agreement_id") != entry.agreement_id or not matched
                or money(matched["commission_amount"]) != money(entry.commission_amount)
                or money(matched["allocated_service_amount"]) != money(entry.eligible_service_amount)):
            raise ValueError("计佣依据已变化，请重新扫描并核对金额后确认")


async def validate_commission_entry_reversal(db: AsyncSession, entry: CommissionEntry) -> None:
    await db.scalar(select(Customers).where(Customers.id == entry.customer_id).with_for_update())
    await db.scalar(select(Payments).where(Payments.id == entry.payment_id).with_for_update().execution_options(populate_existing=True))
    if entry.refund_id is not None:
        return
    recognized_refund = await db.scalar(select(CommissionEntry.id).where(
        CommissionEntry.original_entry_id == entry.id,
        CommissionEntry.status.in_(("confirmed", "payable", "paid")),
    ).limit(1))
    if recognized_refund:
        raise ValueError("原佣金已有已确认退款冲回，不能单独作废；请使用调整流程核对")


async def sync_payment_commission(db: AsyncSession, payment: Payments) -> Optional[CommissionEntry]:
    await db.scalar(select(Customers).where(Customers.id == payment.customer_id).with_for_update())
    payment = await db.scalar(select(Payments).where(Payments.id == payment.id).with_for_update().execution_options(populate_existing=True))
    service_amount = eligible_service_amount(payment)
    if service_amount <= 0:
        return None
    await _resolve_payment_scope(db, payment)
    existing = list((await db.scalars(select(CommissionEntry).where(
        CommissionEntry.payment_id == payment.id, CommissionEntry.refund_id.is_(None),
    ).with_for_update().execution_options(populate_existing=True))).all())
    # Preserve every previously recognized or explicitly voided historical snapshot.
    locked = [row for row in existing if row.status in {"confirmed", "payable", "paid"}]
    if locked:
        return locked[0]
    preview = await preview_payment_commission(db, payment)
    if preview["issues"] or not preview["segments"]:
        return None
    attribution = await db.get(CustomerCommissionAttribution, preview["attribution_id"])
    partner = await db.get(SalesPartner, preview["partner_id"])
    agreement = await db.get(CommissionAgreement, preview["agreement_id"])
    if partner.stopped_at and _as_date(payment.payment_date) > partner.stopped_at:
        return None
    occurred_at = payment.payment_date
    output = []
    current_keys = set()
    for segment in preview["segments"]:
        key = f"payment:{payment.id}:attribution:{attribution.id}:agreement:{agreement.id}:period:{segment['service_period_start']}:{segment['entry_type']}"
        current_keys.add(key)
        row = next((entry for entry in existing if entry.idempotency_key == key), None)
        if row and row.status in LOCKED_STATUSES:
            continue
        snapshot = dict(segment, calculation_version="service_month_v2", renewal_policy="fixed",
            commission_mode=attribution.commission_mode, first_service_start=attribution.first_service_start.isoformat() if attribution.first_service_start else None,
            first_service_end=_next_service_month(attribution.first_service_start).isoformat() if attribution.first_service_start else None,
            commission_start_date=attribution.commission_start_date.isoformat(), history_basis=attribution.history_basis,
            agreement_version=agreement.version, partner_status=partner.status, ad_recharge_excluded=True,
            original_eligible_service_amount=service_amount, refund_guard_days=agreement.refund_guard_days,
            calculation="allocated_service_amount * contract_rate; fixed renewal multiplier 1",
            accounting_month_basis="payment_date")
        values = dict(partner_id=partner.id, agreement_id=agreement.id, attribution_id=attribution.id,
            customer_id=payment.customer_id, engagement_id=payment.engagement_id or attribution.engagement_id,
            payment_id=payment.id, refund_id=None, original_entry_id=None, entry_type=segment["entry_type"],
            status="pending_confirmation", service_month=occurred_at.strftime("%Y-%m"), occurred_at=occurred_at,
            currency=(payment.currency or "USD").upper(), gross_receipt_amount=money(payment.amount_paid),
            eligible_service_amount=segment["allocated_service_amount"], contract_rate=segment["contract_rate"],
            inactivity_months=0, activity_multiplier=1.0, commission_amount=segment["commission_amount"],
            snapshot_json=json.dumps(snapshot, ensure_ascii=False, sort_keys=True), idempotency_key=key)
        if row:
            for name, value in values.items():
                setattr(row, name, value)
        else:
            row = CommissionEntry(**values)
            db.add(row)
        output.append(row)
    for old in existing:
        if old.status in {"pending_confirmation", "estimated"} and old.idempotency_key not in current_keys:
            previous = old.status
            old.status = "reversed"
            db.add(CommissionStatusEvent(commission_entry_id=old.id, from_status=previous, to_status="reversed",
                reason="新归属或协议候选替代未确认条目，原记录保留"))
    await db.flush()
    return output[0] if output else None


async def sync_refund_commission(db: AsyncSession, refund: FinanceRefund) -> list[CommissionEntry]:
    if refund.status != "completed":
        return []
    await db.scalar(select(Customers).where(Customers.id == refund.customer_id).with_for_update())
    payment = await db.scalar(select(Payments).where(Payments.id == refund.payment_id).with_for_update().execution_options(populate_existing=True))
    if not payment or money(payment.amount_paid) <= 0:
        return []
    originals = (await db.scalars(
        select(CommissionEntry).where(
            CommissionEntry.payment_id == payment.id,
            CommissionEntry.refund_id.is_(None),
            CommissionEntry.entry_type.in_(("first_order", "renewal")),
            CommissionEntry.status != "reversed",
        )
    )).all()
    results: list[CommissionEntry] = []
    # Voided originals cannot create a standalone negative expense.
    stale = (await db.scalars(select(CommissionEntry).where(
        CommissionEntry.payment_id == payment.id, CommissionEntry.refund_id == refund.id,
        CommissionEntry.status.in_(("pending_confirmation", "estimated")),
    ))).all()
    original_ids = {row.id for row in originals}
    for row in stale:
        if row.original_entry_id not in original_ids:
            row.status = "reversed"
            db.add(CommissionStatusEvent(commission_entry_id=row.id, from_status="pending_confirmation", to_status="reversed",
                reason="原佣金已作废，取消未确认退款冲回"))
    for original in originals:
        receipt = money(original.gross_receipt_amount)
        if receipt <= 0:
            continue
        ratio = min(max(money(refund.refund_amount) / receipt, 0), 1)
        key = f"refund:{refund.id}:commission:{original.id}"
        existing = await db.scalar(select(CommissionEntry).where(CommissionEntry.idempotency_key == key))
        if existing and existing.status in LOCKED_STATUSES:
            results.append(existing)
            continue
        # Allocate the rounding remainder cumulatively, so two partial refunds
        # can never reverse one cent more/less than a complete original refund.
        completed_refunds = list((await db.scalars(select(FinanceRefund).where(
            FinanceRefund.payment_id == payment.id, FinanceRefund.status == "completed",
        ).order_by(FinanceRefund.refund_date, FinanceRefund.id))).all())
        previous_refunded = 0.0
        for earlier in completed_refunds:
            if earlier.id == refund.id:
                break
            previous_refunded += money(earlier.refund_amount)
        cumulative = min(max((previous_refunded + money(refund.refund_amount)) / receipt, 0), 1)
        previous_ratio = min(max(previous_refunded / receipt, 0), 1)
        reversal_magnitude = money(original.commission_amount * cumulative) - money(original.commission_amount * previous_ratio)
        other_locked = (await db.scalars(select(CommissionEntry).where(
            CommissionEntry.original_entry_id == original.id,
            CommissionEntry.refund_id != refund.id,
            CommissionEntry.status.in_(("confirmed", "payable", "paid")),
        ))).all()
        remaining = max(money(original.commission_amount + sum(row.commission_amount for row in other_locked)), 0)
        amount = -money(min(max(reversal_magnitude, 0), remaining))
        origin_snapshot = _entry_snapshot(original)
        snapshot = {
            **{field: origin_snapshot[field] for field in (
                "calculation_version", "renewal_policy", "commission_mode", "first_service_start", "first_service_end",
                "service_period_start", "service_period_end", "coverage_start", "coverage_end", "allocation_basis",
            ) if field in origin_snapshot},
            "original_entry_id": original.id,
            "original_commission_amount": original.commission_amount,
            "refund_amount": money(refund.refund_amount),
            "original_receipt_amount": receipt,
            "reversal_ratio": ratio,
            "calculation": "cumulative proportional refund difference with cent remainder and locked reversal cap",
            "cumulative_refund_ratio": cumulative,
            "previous_refund_ratio": previous_ratio,
        }
        reversal_values = dict(
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
        if existing:
            reversal = existing
            for field, value in reversal_values.items():
                setattr(reversal, field, value)
        else:
            reversal = CommissionEntry(**reversal_values)
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
        scoped_links = await _attributions_for_payment(db, payment)
        scoped_partner = partner_map.get(scoped_links[0].partner_id) if scoped_links else None
        if scoped_links and scoped_links[0].commission_mode == "none":
            covered_keys.add(key)
            continue
        if scoped_links and scoped_partner and scoped_partner.partner_type != "direct":
            preview = await preview_payment_commission(db, payment)
            if preview["issues"] and preview.get("agreement_id"):
                issues.append({"key": f"payment:{payment.id}:commission_rule", "type": "commission_rule_review",
                    "severity": "high", "customer_id": payment.customer_id,
                    "customer_name": customer_names.get(payment.customer_id) or payment.customer_name,
                    "payment_id": payment.id, "partner_id": scoped_partner.id, "partner_name": scoped_partner.name,
                    "title": "计佣规则或服务周期待核对", "description": "；".join(preview["issues"])})
                continue
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
            CustomerCommissionAttribution.engagement_id.desc().nullslast(),
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
