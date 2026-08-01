from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models.ad_fund_settlements import AdFundSettlement
from models.finance_refunds import FinanceRefund
from models.payments import Payments
from routers.finance_adjustments import (
    AdFundSettlementWrite,
    RefundCreate,
    _net_ads_received,
    create_ad_fund_settlement,
    create_refund,
    update_ad_fund_settlement,
)
from schemas.auth import UserResponse


def _finance_user() -> UserResponse:
    return UserResponse(id="finance-user", email="finance@example.com", name="Finance", role="finance")


async def _create_tables(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Payments.__table__.create)
        await connection.run_sync(FinanceRefund.__table__.create)
        await connection.run_sync(AdFundSettlement.__table__.create)


@pytest.mark.asyncio
async def test_refund_cannot_exceed_original_payment_and_keeps_unreturned_stripe_fee():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        await _create_tables(engine)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            payment = Payments(
                customer_id=1,
                customer_name="A Cafe",
                income_type="management_fee",
                amount_due=249,
                amount_paid=249,
                stripe_fee_amount=7.52,
                currency="USD",
                payment_date=datetime(2026, 7, 7, tzinfo=timezone.utc),
                user_id="finance-user",
            )
            db.add(payment)
            await db.commit()
            await db.refresh(payment)

            refund = await create_refund(
                RefundCreate(
                    payment_id=payment.id,
                    refund_amount=249,
                    refund_date=datetime(2026, 7, 8, tzinfo=timezone.utc),
                    provider_refund_id="re_test",
                    stripe_fee_refunded_amount=0,
                ),
                _finance_user(),
                db,
            )
            assert refund.refund_amount == 249
            assert refund.stripe_fee_refunded_amount == 0

            with pytest.raises(HTTPException) as error:
                await create_refund(
                    RefundCreate(
                        payment_id=payment.id,
                        refund_amount=1,
                        refund_date=datetime(2026, 7, 9, tzinfo=timezone.utc),
                    ),
                    _finance_user(),
                    db,
                )
            assert error.value.status_code == 400
            assert "不能超过" in error.value.detail
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ad_fund_settlement_derives_net_topup_and_carries_remaining_balance():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        await _create_tables(engine)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            june_payment = Payments(
                customer_id=2,
                customer_name="B Bistro",
                income_type="ads_fee",
                amount_due=100,
                amount_paid=100,
                ads_recharge_amount=100,
                currency="USD",
                payment_date=datetime(2026, 6, 5, tzinfo=timezone.utc),
                user_id="finance-user",
            )
            july_payment = Payments(
                customer_id=2,
                customer_name="B Bistro",
                income_type="management_ads_mixed",
                amount_due=1000,
                amount_paid=1000,
                management_amount=200,
                ads_recharge_amount=800,
                currency="USD",
                payment_date=datetime(2026, 7, 5, tzinfo=timezone.utc),
                user_id="finance-user",
            )
            db.add_all([june_payment, july_payment])
            await db.commit()
            await db.refresh(july_payment)
            db.add(FinanceRefund(
                payment_id=july_payment.id,
                customer_id=2,
                customer_name="B Bistro",
                refund_amount=250,
                currency="USD",
                refund_date=datetime(2026, 7, 8, tzinfo=timezone.utc),
                provider="stripe",
                stripe_fee_refunded_amount=0,
                status="completed",
                created_at=datetime.now(timezone.utc),
                user_id="finance-user",
            ))
            await db.commit()

            assert await _net_ads_received(db, 2, "2026-07", "USD") == 600

            june = await create_ad_fund_settlement(
                AdFundSettlementWrite(
                    customer_id=2,
                    customer_name="B Bistro",
                    year_month="2026-06",
                    opening_balance=999,
                    actual_ad_spend=0,
                    status="closed",
                ),
                _finance_user(),
                db,
            )
            assert june.opening_balance == 0
            assert june.funds_received == 100
            assert june.closing_balance == 100

            july = await create_ad_fund_settlement(
                AdFundSettlementWrite(
                    customer_id=2,
                    customer_name="B Bistro",
                    year_month="2026-07",
                    opening_balance=999,
                    actual_ad_spend=500,
                    customer_refund_amount=50,
                    recognized_spread_amount=25,
                    status="closed",
                ),
                _finance_user(),
                db,
            )
            assert july.opening_balance == 100
            assert july.funds_received == 600
            assert july.closing_balance == 125
            assert july.recognized_spread_amount == 25

            august = await create_ad_fund_settlement(
                AdFundSettlementWrite(
                    customer_id=2,
                    customer_name="B Bistro",
                    year_month="2026-08",
                    opening_balance=0,
                    status="draft",
                ),
                _finance_user(),
                db,
            )
            assert august.opening_balance == 125
            assert august.funds_received == 0
            assert august.closing_balance == 125

            updated_july = await update_ad_fund_settlement(
                july.id,
                AdFundSettlementWrite(
                    customer_id=2,
                    customer_name="B Bistro",
                    year_month="2026-07",
                    opening_balance=0,
                    actual_ad_spend=500,
                    customer_refund_amount=50,
                    recognized_spread_amount=75,
                    status="closed",
                ),
                _finance_user(),
                db,
            )
            assert updated_july.opening_balance == 100
            assert updated_july.closing_balance == 75
            await db.refresh(august)
            assert august.opening_balance == 75
            assert august.closing_balance == 75

            with pytest.raises(HTTPException) as error:
                await update_ad_fund_settlement(
                    august.id,
                    AdFundSettlementWrite(
                        customer_id=3,
                        customer_name="Wrong Customer",
                        year_month="2026-08",
                        status="draft",
                    ),
                    _finance_user(),
                    db,
                )
            assert error.value.status_code == 400
            assert "不可修改" in error.value.detail
    finally:
        await engine.dispose()
