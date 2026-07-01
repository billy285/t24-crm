import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.customers import Customers
from models.deals import Deals
from models.payments import Payments

logger = logging.getLogger(__name__)


def infer_deal_product_type(product_name: Optional[str], income_type: Optional[str]) -> str:
    names = [item.strip() for item in (product_name or "").split("、") if item.strip()]
    normalized = " ".join(names).lower()

    if len(names) > 1:
        return "combo"

    if any(keyword in normalized for keyword in ["点餐", "ordering"]):
        return "ordering_system"
    if any(keyword in normalized for keyword in ["官网", "网站", "web"]):
        return "website"
    if any(keyword in normalized for keyword in ["ads", "广告", "投流"]):
        return "ads"
    if any(
        keyword in normalized
        for keyword in ["google商家", "facebook商家", "instagram商家", "yelp商家", "tiktok商家", "小红书商家", "商家管理"]
    ):
        return "social_media"

    income_type_map = {
        "ordering_fee": "ordering_system",
        "ads_fee": "ads",
        "website_fee": "website",
        "management_fee": "social_media",
        "renewal_fee": "combo" if len(names) > 1 else "social_media",
    }
    return income_type_map.get(income_type or "", "social_media")


async def _load_customer(db: AsyncSession, customer_id: Optional[int]) -> Optional[Customers]:
    if not customer_id:
        return None
    result = await db.execute(select(Customers).where(Customers.id == customer_id))
    return result.scalar_one_or_none()


async def _load_synced_deal(db: AsyncSession, payment_id: int) -> Optional[Deals]:
    result = await db.execute(select(Deals).where(Deals.source_payment_id == payment_id))
    return result.scalar_one_or_none()


async def _load_deal_by_id(db: AsyncSession, deal_id: Optional[int]) -> Optional[Deals]:
    if not deal_id:
        return None
    result = await db.execute(select(Deals).where(Deals.id == deal_id))
    return result.scalar_one_or_none()


async def sync_deal_from_payment(db: AsyncSession, payment: Payments, commit: bool = True) -> Deals:
    customer = await _load_customer(db, payment.customer_id)
    deal_date = payment.payment_date or payment.created_at or datetime.utcnow()
    created_at = payment.created_at or deal_date
    package_name = payment.product_name or payment.customer_name or "未命名套餐"
    deal_amount = payment.amount_due if payment.amount_due is not None else payment.amount_paid
    outstanding_amount = payment.outstanding_amount or 0

    payload = {
        "customer_id": payment.customer_id,
        "customer_name": customer.business_name if customer and customer.business_name else (payment.customer_name or ""),
        "sales_employee_id": customer.sales_employee_id if customer else None,
        "sales_name": customer.sales_person if customer else None,
        "product_type": infer_deal_product_type(payment.product_name, payment.income_type),
        "package_name": package_name,
        "billing_cycle": payment.billing_cycle,
        "deal_amount": deal_amount or 0,
        "is_paid": outstanding_amount <= 0,
        "service_start_date": payment.coverage_start,
        "service_end_date": payment.coverage_end,
        "needs_group": False,
        "is_handed_over": False,
        "is_transferred_ops": False,
        "notes": payment.notes,
        "deal_date": deal_date,
        "created_at": created_at,
    }

    if getattr(payment, "source_deal_id", None):
        deal = await _load_deal_by_id(db, payment.source_deal_id)
    else:
        payload["source_payment_id"] = payment.id
        deal = await _load_synced_deal(db, payment.id)
    if deal is None:
        deal = Deals(**payload)
        db.add(deal)
    else:
        for key, value in payload.items():
            setattr(deal, key, value)

    if commit:
        await db.commit()
        await db.refresh(deal)
    else:
        await db.flush()

    return deal


async def delete_synced_deal_for_payment(db: AsyncSession, payment_id: int, commit: bool = True) -> bool:
    deal = await _load_synced_deal(db, payment_id)
    if deal is None:
        return False

    await db.delete(deal)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return True


async def unlink_synced_deal_for_payment(db: AsyncSession, payment_id: int, commit: bool = True) -> bool:
    deal = await _load_synced_deal(db, payment_id)
    if deal is None:
        return False

    deal.source_payment_id = None
    if commit:
        await db.commit()
        await db.refresh(deal)
    else:
        await db.flush()
    return True


async def sync_all_deals_from_payments(db: AsyncSession) -> int:
    result = await db.execute(select(Payments).order_by(Payments.id.asc()))
    payments = result.scalars().all()
    synced_count = 0

    for payment in payments:
        await sync_deal_from_payment(db, payment, commit=False)
        synced_count += 1

    await db.commit()
    logger.info("Backfilled %s deals from payments", synced_count)
    return synced_count
