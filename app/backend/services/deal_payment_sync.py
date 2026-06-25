import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.customers import Customers
from models.deals import Deals
from models.payments import Payments
from models.subscriptions import Subscriptions

logger = logging.getLogger(__name__)


def normalize_payment_method(method: Optional[str]) -> Optional[str]:
    if method == "subscription_debit":
        return "stripe"
    return method


def infer_payment_mode(payment_method: Optional[str]) -> str:
    return "subscription_auto" if normalize_payment_method(payment_method) == "stripe" else "manual_collection"


def infer_payment_income_type(product_type: Optional[str], package_name: Optional[str]) -> str:
    normalized = (package_name or "").lower()
    if product_type == "ordering_system" or "点餐" in normalized:
        return "ordering_fee"
    if product_type == "website" or "网站" in normalized or "官网" in normalized:
        return "website_fee"
    if product_type == "ads" or "广告" in normalized or "ads" in normalized:
        return "ads_fee"
    if product_type == "social_media":
        return "management_fee"
    return "other_income"


async def _load_customer(db: AsyncSession, customer_id: Optional[int]) -> Optional[Customers]:
    if not customer_id:
        return None
    result = await db.execute(select(Customers).where(Customers.id == customer_id))
    return result.scalar_one_or_none()


async def _load_subscription_for_deal(db: AsyncSession, deal: Deals) -> Optional[Subscriptions]:
    result = await db.execute(
        select(Subscriptions)
        .where(Subscriptions.deal_id == deal.id)
        .order_by(Subscriptions.id.desc())
        .limit(2)
    )
    subscriptions = result.scalars().all()
    if len(subscriptions) > 1:
        logger.warning(
            "Multiple subscriptions found for deal %s, using latest subscription %s",
            deal.id,
            subscriptions[0].id,
        )
    if subscriptions:
        return subscriptions[0]

    result = await db.execute(
        select(Subscriptions)
        .where(Subscriptions.customer_id == deal.customer_id)
        .where(Subscriptions.package_name == deal.package_name)
        .order_by(Subscriptions.id.desc())
        .limit(2)
    )
    subscriptions = result.scalars().all()
    if len(subscriptions) > 1:
        logger.warning(
            "Multiple matching subscriptions found for customer %s package %s, using latest subscription %s",
            deal.customer_id,
            deal.package_name,
            subscriptions[0].id,
        )
    return subscriptions[0] if subscriptions else None


async def _load_synced_payment(db: AsyncSession, deal_id: int) -> Optional[Payments]:
    result = await db.execute(select(Payments).where(Payments.source_deal_id == deal_id))
    return result.scalar_one_or_none()


async def _load_matching_payment(db: AsyncSession, deal: Deals) -> Optional[Payments]:
    query = (
        select(Payments)
        .where(Payments.customer_id == deal.customer_id)
        .where(Payments.source_deal_id.is_(None))
        .where(Payments.product_name == (deal.package_name or ""))
        .where(Payments.amount_due == (deal.deal_amount or 0))
    )
    if deal.billing_cycle:
        query = query.where(Payments.billing_cycle == deal.billing_cycle)
    if deal.service_start_date:
        query = query.where(Payments.coverage_start == deal.service_start_date)
    if deal.service_end_date:
        query = query.where(Payments.coverage_end == deal.service_end_date)

    result = await db.execute(query.order_by(Payments.id.desc()))
    return result.scalar_one_or_none()


def _choose_payment_date(deal: Deals, subscription: Optional[Subscriptions]) -> datetime:
    return (
        (subscription.last_payment_date if subscription else None)
        or deal.deal_date
        or deal.created_at
        or datetime.utcnow()
    )


async def sync_payment_from_deal(db: AsyncSession, deal: Deals, commit: bool = True) -> Payments:
    customer = await _load_customer(db, deal.customer_id)
    subscription = await _load_subscription_for_deal(db, deal)
    payment = await _load_synced_payment(db, deal.id)
    if payment is None:
        payment = await _load_matching_payment(db, deal)

    payment_date = (payment.payment_date if payment else None) or _choose_payment_date(deal, subscription)
    created_at = (payment.created_at if payment else None) or deal.created_at or payment_date
    amount_due = float(deal.deal_amount or 0)
    amount_paid = amount_due if deal.is_paid else 0.0
    outstanding_amount = max(amount_due - amount_paid, 0.0)
    payment_mode = (
        payment.payment_mode
        if payment and getattr(payment, "payment_mode", None)
        else infer_payment_mode(payment.payment_method if payment else None)
    )
    payment_method = normalize_payment_method(payment.payment_method if payment else None)
    if payment_mode == "subscription_auto":
        payment_method = payment_method or "stripe"
    else:
        payment_method = payment_method or "other"
    product_name = (
        deal.package_name
        or (customer.business_name if customer and customer.business_name else None)
        or deal.customer_name
        or "未命名套餐"
    )
    product_name = product_name or "未命名套餐"
    user_id = str(
        deal.sales_employee_id
        or (customer.sales_employee_id if customer and customer.sales_employee_id else "")
        or "system"
    )

    payload = {
        "source_deal_id": deal.id,
        "customer_id": deal.customer_id,
        "customer_name": customer.business_name if customer and customer.business_name else (deal.customer_name or ""),
        "income_type": infer_payment_income_type(deal.product_type, deal.package_name),
        "product_name": product_name,
        "amount_due": amount_due,
        "amount_paid": amount_paid,
        "currency": payment.currency if payment and payment.currency else "USD",
        "payment_date": payment_date,
        "payment_mode": payment_mode,
        "payment_method": payment_method,
        "billing_cycle": deal.billing_cycle,
        "coverage_start": deal.service_start_date,
        "coverage_end": deal.service_end_date,
        "has_invoice": payment.has_invoice if payment and payment.has_invoice is not None else False,
        "outstanding_amount": outstanding_amount,
        "expense_month": payment_date.strftime("%Y-%m") if payment_date else None,
        "recorded_by": payment.recorded_by if payment and payment.recorded_by else deal.sales_name,
        "notes": deal.notes if deal.notes else (payment.notes if payment else None),
        "created_at": created_at,
        "user_id": user_id,
    }

    if payment is None:
        payment = Payments(**payload)
        db.add(payment)
    else:
        for key, value in payload.items():
            setattr(payment, key, value)

    if commit:
        await db.commit()
        await db.refresh(payment)
    else:
        await db.flush()

    return payment


async def delete_synced_payment_for_deal(db: AsyncSession, deal_id: int, commit: bool = True) -> bool:
    payment = await _load_synced_payment(db, deal_id)
    if payment is None:
        return False

    await db.delete(payment)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return True


async def backfill_missing_payments_from_deals(db: AsyncSession) -> int:
    result = await db.execute(select(Deals).order_by(Deals.id.asc()))
    deals = result.scalars().all()
    synced_count = 0

    for deal in deals:
        existing = await _load_synced_payment(db, deal.id)
        if existing is not None:
            continue
        await sync_payment_from_deal(db, deal, commit=False)
        synced_count += 1

    await db.commit()
    logger.info("Backfilled %s payments from deals", synced_count)
    return synced_count
