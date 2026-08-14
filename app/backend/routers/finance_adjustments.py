import re
import logging
from datetime import datetime, timezone
from calendar import monthrange
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_finance_user
from models.ad_fund_settlements import AdFundSettlement
from models.finance_refunds import FinanceRefund
from models.payments import Payments
from services.commissions import commission_ledger_available, sync_refund_commission
from services.finance_period_lock import ensure_profit_months_open
from schemas.auth import UserResponse


router = APIRouter(prefix="/api/v1/finance", tags=["finance-adjustments"])
logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _money(value: float) -> float:
    return round(float(value or 0), 2)


def _payment_ads_amount(payment: Payments) -> float:
    if payment.ads_recharge_amount is not None:
        return max(_money(payment.ads_recharge_amount), 0)
    return max(_money(payment.amount_paid), 0) if payment.income_type == "ads_fee" else 0


def _refund_ads_share(payment: Payments, refund: FinanceRefund) -> float:
    paid = max(_money(payment.amount_paid), 0)
    ads = _payment_ads_amount(payment)
    if paid <= 0 or ads <= 0:
        return 0
    return _money(refund.refund_amount * min(ads / paid, 1))


class RefundCreate(BaseModel):
    payment_id: int = Field(gt=0)
    refund_amount: float = Field(gt=0)
    refund_date: datetime
    provider: str = "stripe"
    provider_refund_id: Optional[str] = None
    stripe_fee_refunded_amount: float = Field(default=0, ge=0)
    status: Literal["pending", "completed", "failed"] = "completed"
    reason: Optional[str] = None
    notes: Optional[str] = None
    recorded_by: Optional[str] = None


class RefundResponse(BaseModel):
    id: int
    payment_id: int
    customer_id: int
    customer_name: Optional[str] = None
    refund_amount: float
    currency: str
    refund_date: datetime
    provider: str
    provider_refund_id: Optional[str] = None
    stripe_fee_refunded_amount: float
    status: str
    reason: Optional[str] = None
    notes: Optional[str] = None
    recorded_by: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class RefundListResponse(BaseModel):
    items: list[RefundResponse]
    total: int


@router.get("/refunds", response_model=RefundListResponse)
async def list_refunds(
    skip: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=2000),
    _current_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    total = await db.scalar(select(func.count(FinanceRefund.id))) or 0
    rows = await db.scalars(
        select(FinanceRefund).order_by(FinanceRefund.refund_date.desc(), FinanceRefund.id.desc()).offset(skip).limit(limit)
    )
    return {"items": rows.all(), "total": total}


@router.post("/refunds", response_model=RefundResponse, status_code=status.HTTP_201_CREATED)
async def create_refund(
    data: RefundCreate,
    current_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    await ensure_profit_months_open(db, [data.refund_date], action="新增退款")
    payment = await db.get(Payments, data.payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="原收款记录不存在")

    completed_total = await db.scalar(
        select(func.coalesce(func.sum(FinanceRefund.refund_amount), 0)).where(
            FinanceRefund.payment_id == payment.id,
            FinanceRefund.status == "completed",
        )
    ) or 0
    pending_total = await db.scalar(
        select(func.coalesce(func.sum(FinanceRefund.refund_amount), 0)).where(
            FinanceRefund.payment_id == payment.id,
            FinanceRefund.status == "pending",
        )
    ) or 0
    reserved_total = _money(completed_total) + _money(pending_total)
    if data.status in {"completed", "pending"} and reserved_total + _money(data.refund_amount) > _money(payment.amount_paid) + 0.01:
        raise HTTPException(status_code=400, detail="累计退款金额不能超过原收款实收金额")
    if _money(data.stripe_fee_refunded_amount) > _money(data.refund_amount):
        raise HTTPException(status_code=400, detail="退回的 Stripe 手续费不能高于退款金额")

    refund = FinanceRefund(
        payment_id=payment.id,
        customer_id=payment.customer_id,
        customer_name=payment.customer_name,
        refund_amount=_money(data.refund_amount),
        currency=(payment.currency or "USD").upper(),
        refund_date=data.refund_date,
        provider=(data.provider or "stripe").strip().lower(),
        provider_refund_id=(data.provider_refund_id or "").strip() or None,
        stripe_fee_refunded_amount=_money(data.stripe_fee_refunded_amount),
        status=data.status,
        reason=(data.reason or "").strip() or None,
        notes=(data.notes or "").strip() or None,
        recorded_by=(data.recorded_by or "").strip() or None,
        created_at=_utcnow(),
        user_id=str(current_user.id),
    )
    db.add(refund)
    await db.commit()
    await db.refresh(refund)
    if await commission_ledger_available(db):
        refund_id = refund.id
        try:
            await sync_refund_commission(db, refund)
            await db.commit()
        except Exception as commission_err:
            await db.rollback()
            await db.refresh(refund)
            logger.error("Refund %s saved but commission reversal sync failed: %s", refund_id, commission_err, exc_info=True)
    return refund


class AdFundSettlementWrite(BaseModel):
    customer_id: int = Field(gt=0)
    customer_name: Optional[str] = None
    year_month: str
    currency: Literal["USD", "CNY"] = "USD"
    opening_balance: float = Field(default=0, ge=0)
    actual_ad_spend: float = Field(default=0, ge=0)
    customer_refund_amount: float = Field(default=0, ge=0)
    recognized_spread_amount: float = Field(default=0, ge=0)
    adjustment_amount: float = 0
    status: Literal["draft", "closed"] = "draft"
    notes: Optional[str] = None
    recorded_by: Optional[str] = None

    @model_validator(mode="after")
    def validate_month(self):
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", self.year_month):
            raise ValueError("结算月份必须为 YYYY-MM")
        return self


class AdFundSettlementResponse(BaseModel):
    id: int
    customer_id: int
    customer_name: Optional[str] = None
    year_month: str
    currency: str
    opening_balance: float
    funds_received: float
    actual_ad_spend: float
    customer_refund_amount: float
    recognized_spread_amount: float
    adjustment_amount: float
    closing_balance: float
    status: str
    notes: Optional[str] = None
    recorded_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AdFundSettlementListResponse(BaseModel):
    items: list[AdFundSettlementResponse]
    total: int


async def _net_ads_received(db: AsyncSession, customer_id: int, year_month: str, currency: str) -> float:
    year, month = (int(part) for part in year_month.split("-"))
    month_start = datetime(year, month, 1, tzinfo=timezone.utc)
    month_end = datetime(year, month, monthrange(year, month)[1], 23, 59, 59, 999999, tzinfo=timezone.utc)
    payments = (
        await db.scalars(
            select(Payments).where(
                Payments.customer_id == customer_id,
                Payments.currency == currency,
                Payments.payment_date >= month_start,
                Payments.payment_date <= month_end,
            )
        )
    ).all()
    received = sum(_payment_ads_amount(payment) for payment in payments)

    refund_rows = (
        await db.execute(
            select(FinanceRefund, Payments)
            .join(Payments, Payments.id == FinanceRefund.payment_id)
            .where(
                FinanceRefund.customer_id == customer_id,
                FinanceRefund.currency == currency,
                FinanceRefund.status == "completed",
                FinanceRefund.refund_date >= month_start,
                FinanceRefund.refund_date <= month_end,
            )
        )
    ).all()
    refunded_ads = sum(_refund_ads_share(payment, refund) for refund, payment in refund_rows)
    return _money(received - refunded_ads)


def _settlement_values(data: AdFundSettlementWrite, funds_received: float) -> tuple[float, float]:
    available = _money(data.opening_balance + funds_received + data.adjustment_amount)
    allocated = _money(data.actual_ad_spend + data.customer_refund_amount + data.recognized_spread_amount)
    closing = _money(available - allocated)
    if closing < -0.01:
        raise HTTPException(status_code=400, detail="广告实支、退款和确认差价合计不能超过可用客户资金")
    if data.status == "closed" and closing < 0:
        closing = 0
    return available, closing


async def _previous_ad_fund_settlement(
    db: AsyncSession,
    customer_id: int,
    year_month: str,
    currency: str,
) -> Optional[AdFundSettlement]:
    return await db.scalar(
        select(AdFundSettlement)
        .where(
            AdFundSettlement.customer_id == customer_id,
            AdFundSettlement.currency == currency,
            AdFundSettlement.year_month < year_month,
        )
        .order_by(AdFundSettlement.year_month.desc(), AdFundSettlement.id.desc())
        .limit(1)
    )


async def _automatic_opening_balance(
    db: AsyncSession,
    customer_id: int,
    year_month: str,
    currency: str,
) -> float:
    previous = await _previous_ad_fund_settlement(db, customer_id, year_month, currency)
    return _money(previous.closing_balance) if previous else 0


async def _ensure_future_ad_fund_months_open(
    db: AsyncSession,
    customer_id: int,
    currency: str,
    after_month: str,
) -> None:
    future_months = (
        await db.scalars(
            select(AdFundSettlement.year_month).where(
                AdFundSettlement.customer_id == customer_id,
                AdFundSettlement.currency == currency,
                AdFundSettlement.year_month > after_month,
            )
        )
    ).all()
    await ensure_profit_months_open(
        db,
        future_months,
        action="联动重算后续投流月结",
    )


async def _recalculate_future_ad_fund_settlements(
    db: AsyncSession,
    customer_id: int,
    currency: str,
    after_month: str,
    carried_balance: float,
) -> None:
    future_rows = (
        await db.scalars(
            select(AdFundSettlement)
            .where(
                AdFundSettlement.customer_id == customer_id,
                AdFundSettlement.currency == currency,
                AdFundSettlement.year_month > after_month,
            )
            .order_by(AdFundSettlement.year_month, AdFundSettlement.id)
        )
    ).all()
    await ensure_profit_months_open(
        db,
        [row.year_month for row in future_rows],
        action="联动重算后续投流月结",
    )
    opening_balance = _money(carried_balance)
    for row in future_rows:
        funds_received = await _net_ads_received(db, customer_id, row.year_month, currency)
        recalculated = AdFundSettlementWrite(
            customer_id=row.customer_id,
            customer_name=row.customer_name,
            year_month=row.year_month,
            currency=row.currency,
            opening_balance=opening_balance,
            actual_ad_spend=row.actual_ad_spend,
            customer_refund_amount=row.customer_refund_amount,
            recognized_spread_amount=row.recognized_spread_amount,
            adjustment_amount=row.adjustment_amount,
            status=row.status,
            notes=row.notes,
            recorded_by=row.recorded_by,
        )
        _available, closing_balance = _settlement_values(recalculated, funds_received)
        row.opening_balance = opening_balance
        row.funds_received = funds_received
        row.closing_balance = closing_balance
        row.updated_at = _utcnow()
        opening_balance = closing_balance


@router.get("/ad-fund-settlements", response_model=AdFundSettlementListResponse)
async def list_ad_fund_settlements(
    skip: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=2000),
    _current_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    total = await db.scalar(select(func.count(AdFundSettlement.id))) or 0
    rows = await db.scalars(
        select(AdFundSettlement)
        .order_by(AdFundSettlement.year_month.desc(), AdFundSettlement.customer_name, AdFundSettlement.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return {"items": rows.all(), "total": total}


@router.post("/ad-fund-settlements", response_model=AdFundSettlementResponse, status_code=status.HTTP_201_CREATED)
async def create_ad_fund_settlement(
    data: AdFundSettlementWrite,
    current_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    await ensure_profit_months_open(db, [data.year_month], action="新增投流月结")
    existing = await db.scalar(
        select(AdFundSettlement).where(
            AdFundSettlement.customer_id == data.customer_id,
            AdFundSettlement.year_month == data.year_month,
            AdFundSettlement.currency == data.currency,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="该客户该月份已有投流结算，请编辑原记录")
    await _ensure_future_ad_fund_months_open(db, data.customer_id, data.currency, data.year_month)
    opening_balance = await _automatic_opening_balance(db, data.customer_id, data.year_month, data.currency)
    data = data.model_copy(update={"opening_balance": opening_balance})
    funds_received = await _net_ads_received(db, data.customer_id, data.year_month, data.currency)
    _available, closing = _settlement_values(data, funds_received)
    now = _utcnow()
    payload = data.model_dump()
    payload["customer_name"] = (data.customer_name or "").strip() or None
    payload["notes"] = (data.notes or "").strip() or None
    payload["recorded_by"] = (data.recorded_by or "").strip() or None
    settlement = AdFundSettlement(
        **payload,
        funds_received=funds_received,
        closing_balance=closing,
        created_at=now,
        updated_at=now,
        user_id=str(current_user.id),
    )
    try:
        db.add(settlement)
        await db.flush()
        await _recalculate_future_ad_fund_settlements(
            db,
            settlement.customer_id,
            settlement.currency,
            settlement.year_month,
            settlement.closing_balance,
        )
        await db.commit()
        await db.refresh(settlement)
    except Exception:
        await db.rollback()
        raise
    return settlement


@router.put("/ad-fund-settlements/{settlement_id}", response_model=AdFundSettlementResponse)
async def update_ad_fund_settlement(
    settlement_id: int,
    data: AdFundSettlementWrite,
    _current_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    settlement = await db.get(AdFundSettlement, settlement_id)
    if not settlement:
        raise HTTPException(status_code=404, detail="投流结算记录不存在")
    await ensure_profit_months_open(
        db,
        [settlement.year_month, data.year_month],
        action="修改投流月结",
    )
    if (
        settlement.customer_id != data.customer_id
        or settlement.year_month != data.year_month
        or settlement.currency != data.currency
    ):
        raise HTTPException(status_code=400, detail="客户、结算月份和币种不可修改；如需调整请新建正确月份的月结")
    await _ensure_future_ad_fund_months_open(db, data.customer_id, data.currency, data.year_month)
    opening_balance = await _automatic_opening_balance(db, data.customer_id, data.year_month, data.currency)
    data = data.model_copy(update={"opening_balance": opening_balance})
    funds_received = await _net_ads_received(db, data.customer_id, data.year_month, data.currency)
    _available, closing = _settlement_values(data, funds_received)
    try:
        for key, value in data.model_dump().items():
            setattr(settlement, key, value)
        settlement.funds_received = funds_received
        settlement.closing_balance = closing
        settlement.updated_at = _utcnow()
        await db.flush()
        await _recalculate_future_ad_fund_settlements(
            db,
            settlement.customer_id,
            settlement.currency,
            settlement.year_month,
            settlement.closing_balance,
        )
        await db.commit()
        await db.refresh(settlement)
    except Exception:
        await db.rollback()
        raise
    return settlement
