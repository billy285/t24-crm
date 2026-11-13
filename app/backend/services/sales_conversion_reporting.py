"""Report one conversion per lead and first receipts from the two sales workflows."""
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select

from models.deals import Deals
from models.management_decisions import CustomerEngagement
from models.payments import Payments
from models.sales_deal_controls import SalesHandoffChecklists, SalesQuoteRequests
from models.sales_deal_handoffs import SalesDealHandoff
from models.sales_lead_conversion_logs import SalesLeadConversionLogs


@dataclass(frozen=True)
class Conversion:
    lead_id: int
    customer_id: int | None
    seller_id: int | None
    created_at: datetime


def snapshot_id(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    token = str(value).strip()
    if not (token.isascii() and token.isdigit() and len(token) <= 19):
        return None
    identifier = int(token)
    return identifier if 0 < identifier <= 2**63 - 1 else None


async def sales_conversions(db, *, start=None, until=None, lead_ids=None):
    """Date filters apply to the original conversion, including duplicate older audit rows."""
    logs = SalesLeadConversionLogs
    first = select(logs.lead_id).group_by(logs.lead_id)
    if lead_ids is not None:
        if not lead_ids:
            return []
        first = first.where(logs.lead_id.in_(lead_ids))
    if start is not None:
        first = first.having(func.min(logs.created_at) >= start)
    if until is not None:
        first = first.having(func.min(logs.created_at) < until)
    rows = (await db.execute(select(logs.lead_id, logs.customer_id, logs.lead_snapshot_json, logs.created_at)
        .where(logs.lead_id.in_(first)).order_by(logs.created_at, logs.id))).all()
    groups = defaultdict(list)
    handoff_ids = set()
    for row in rows:
        try:
            data = json.loads(row.lead_snapshot_json)
        except (ValueError, TypeError):
            data = {}
        data = data if isinstance(data, dict) else {}
        fixed = data.get("source") == "fixed_catalog_sale"
        handoff_id = snapshot_id(data.get("handoff_id")) if fixed else None
        if handoff_id:
            handoff_ids.add(handoff_id)
        groups[row.lead_id].append((row, data, fixed, handoff_id))

    origins = {}
    if handoff_ids:
        h = SalesDealHandoff
        origins = {r.id: r for r in (await db.execute(
            select(h.id, h.lead_id, h.customer_id, Deals.sales_employee_id,
                   CustomerEngagement.sales_employee_id.label("project_seller_id"))
            .join(Deals, and_(Deals.id == h.deal_id, Deals.customer_id == h.customer_id,
                              Deals.engagement_id == h.engagement_id))
            .outerjoin(CustomerEngagement, and_(CustomerEngagement.id == h.engagement_id,
                       CustomerEngagement.customer_id == h.customer_id))
            .where(h.id.in_(handoff_ids)))).all()}
    result = []
    for lead_id, group in groups.items():
        sellers = set()
        customers = set()
        broken_link = False
        for row, data, fixed, handoff_id in group:
            seller = snapshot_id(data.get("assigned_sales_id"))
            customers.add(row.customer_id)
            if seller:
                sellers.add(seller)
            if fixed:
                origin = origins.get(handoff_id)
                if origin is None or (origin.lead_id, origin.customer_id) != (lead_id, row.customer_id):
                    broken_link = True
                else:
                    sellers.update(value for value in (origin.sales_employee_id, origin.project_seller_id) if value)
        customer = next(iter(customers)) if len(customers) == 1 else None
        seller = next(iter(sellers)) if customer and not broken_link and len(sellers) == 1 else None
        result.append(Conversion(lead_id, customer, seller, group[0][0].created_at))
    return result


async def conversion_counts(db, seller_ids, start_date: date, end_date: date):
    business_tz = ZoneInfo("Asia/Shanghai")
    start = datetime.combine(start_date, time.min, business_tz).astimezone(timezone.utc)
    until = datetime.combine(end_date + timedelta(days=1), time.min, business_tz).astimezone(timezone.utc)
    counts = dict.fromkeys(seller_ids, 0)
    for conversion in await sales_conversions(db, start=start, until=until):
        if conversion.seller_id in counts:
            counts[conversion.seller_id] += 1
    return counts


@dataclass(frozen=True)
class FirstReceipt:
    lead_id: int
    amount: Decimal
    currency: str
    paid_in_full: bool


def currency_totals(pairs):
    totals = defaultdict(Decimal)
    for currency, amount in pairs:
        totals[(currency or "UNKNOWN").strip().upper()] += Decimal(str(amount or 0))
    return {currency: float(round(amount, 2)) for currency, amount in sorted(totals.items())}


async def first_receipts(db, lead_ids):
    """Recognize verified first receipts once. When both workflows have evidence, the
    catalog receipt is authoritative, with conflicting legacy evidence flagged for review.
    """
    if not lead_ids:
        return [], set(), set()
    h, p = SalesDealHandoff, Payments
    standard = (await db.execute(select(h.lead_id, h.amount, h.currency, h.payment_status,
        h.payment_confirmed_at, p.amount_paid, p.currency.label("receipt_currency"), p.transaction_reference)
        .outerjoin(p, and_(p.id == h.payment_id, p.source_deal_id == h.deal_id,
                           p.customer_id == h.customer_id, p.engagement_id == h.engagement_id))
        .where(h.lead_id.in_(lead_ids)))).all()
    standard_ids = {r.lead_id for r in standard}
    receipts = []
    pending = set()
    for r in standard:
        if (r.payment_status == "paid" and r.payment_confirmed_at and r.amount_paid is not None
                and r.amount_paid > 0 and r.amount_paid == r.amount and r.receipt_currency == r.currency):
            receipts.append(FirstReceipt(r.lead_id, Decimal(str(r.amount_paid)), r.receipt_currency, True))
        else:
            pending.add(r.lead_id)

    paid_standard = {r.lead_id: r for r in standard if r.lead_id not in pending}
    conflicts = set()
    legacy = SalesHandoffChecklists
    quote = SalesQuoteRequests
    legacy_rows = (await db.execute(select(legacy, quote.currency).outerjoin(quote, and_(
        quote.id == legacy.quote_id, quote.lead_id == legacy.lead_id)).where(legacy.lead_id.in_(lead_ids)))).all()
    for row, currency in legacy_rows:
        full = row.payment_status == "paid" and row.finance_payment_confirmed
        confirmed = full or (row.payment_status == "deposit_paid" and row.payment_confirmed_at)
        if confirmed and row.amount_received > 0:
            standard_payment = paid_standard.get(row.lead_id)
            if standard_payment is None:
                # An older deposit still counts as cash. It cannot settle a new catalog contract.
                receipts.append(FirstReceipt(row.lead_id, Decimal(str(row.amount_received)), currency,
                                             bool(full and row.lead_id not in standard_ids)))
            if row.lead_id in standard_ids and not (
                standard_payment and row.payment_reference and row.payment_reference == standard_payment.transaction_reference
                and row.amount_received == standard_payment.amount_paid and currency == standard_payment.receipt_currency
            ):
                conflicts.add(row.lead_id)
        if row.lead_id not in standard_ids and not full and not row.generated_deal_id:
            pending.add(row.lead_id)
    return receipts, pending, conflicts
