from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import Base
from models.company_expenses import Company_expenses
from models.expenses import Expenses
from models.finance_refunds import FinanceRefund
from models.finance_profit_closes import MonthlyProfitClose
from models.payments import Payments
from routers.company_expenses import (
    Company_expensesBatchCreateRequest,
    Company_expensesData,
    Company_expensesUpdateData,
    create_company_expenses,
    create_company_expensess_batch,
    update_company_expenses,
)
from routers.expenses import (
    ExpensesBatchCreateRequest,
    ExpensesData,
    create_expenses,
    create_expensess_batch,
)
from routers.payments import (
    PaymentsBatchCreateRequest,
    PaymentsData,
    PaymentsUpdateData,
    create_payments,
    create_paymentss_batch,
    delete_payments,
    update_payments,
)
from schemas.auth import UserResponse


def _finance_user() -> UserResponse:
    return UserResponse(id="finance-user", email="finance@example.com", name="Finance", role="finance")


@pytest.mark.asyncio
async def test_locked_profit_month_rejects_all_primary_finance_writes():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            db.add(MonthlyProfitClose(
                year_month="2026-07",
                status="locked",
                snapshot_json="{}",
                locked_by="Owner",
                locked_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            ))
            await db.commit()

            with pytest.raises(HTTPException) as payment_error:
                await create_payments(
                    PaymentsData(
                        customer_id=1,
                        amount_due=249,
                        amount_paid=249,
                        payment_date=datetime(2026, 7, 10, tzinfo=timezone.utc),
                    ),
                    _finance_user(),
                    db,
                )
            assert payment_error.value.status_code == 409

            with pytest.raises(HTTPException) as customer_expense_error:
                await create_expenses(
                    ExpensesData(
                        customer_id=1,
                        expense_type="domain",
                        amount=20,
                        expense_date=datetime(2026, 7, 11, tzinfo=timezone.utc),
                    ),
                    _finance_user(),
                    db,
                )
            assert customer_expense_error.value.status_code == 409

            with pytest.raises(HTTPException) as company_expense_error:
                await create_company_expenses(
                    Company_expensesData(
                        category="software",
                        amount=100,
                        currency="CNY",
                        expense_month="2026-07",
                    ),
                    _finance_user(),
                    db,
                )
            assert company_expense_error.value.status_code == 409
            assert "月结" in company_expense_error.value.detail
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_payment_lock_covers_recognition_period_refunds_and_batch_preflight():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            db.add_all([
                MonthlyProfitClose(
                    year_month="2026-07", status="locked", snapshot_json="{}",
                    locked_by="Owner", locked_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                ),
                Payments(
                    id=1, customer_id=1, amount_due=249, amount_paid=249, currency="USD",
                    payment_date=datetime(2026, 8, 5, tzinfo=timezone.utc),
                    coverage_start=datetime(2026, 7, 1, tzinfo=timezone.utc),
                    coverage_end=datetime(2026, 8, 1, tzinfo=timezone.utc),
                    created_at=datetime(2026, 8, 5, tzinfo=timezone.utc), user_id="finance-user",
                ),
                Payments(
                    id=2, customer_id=2, amount_due=500, amount_paid=500, currency="USD",
                    payment_date=datetime(2026, 8, 6, tzinfo=timezone.utc),
                    coverage_start=datetime(2026, 8, 1, tzinfo=timezone.utc),
                    coverage_end=datetime(2026, 9, 1, tzinfo=timezone.utc),
                    created_at=datetime(2026, 8, 6, tzinfo=timezone.utc), user_id="finance-user",
                ),
                FinanceRefund(
                    payment_id=2, customer_id=2, refund_amount=50, currency="USD",
                    refund_date=datetime(2026, 7, 20, tzinfo=timezone.utc), provider="stripe",
                    stripe_fee_refunded_amount=0, status="completed",
                    created_at=datetime(2026, 7, 20, tzinfo=timezone.utc), user_id="finance-user",
                ),
            ])
            await db.commit()

            with pytest.raises(HTTPException) as coverage_update:
                await update_payments(1, PaymentsUpdateData(amount_paid=199), _finance_user(), db)
            assert coverage_update.value.status_code == 409

            with pytest.raises(HTTPException) as coverage_delete:
                await delete_payments(1, _finance_user(), db)
            assert coverage_delete.value.status_code == 409

            with pytest.raises(HTTPException) as refund_update:
                await update_payments(2, PaymentsUpdateData(amount_paid=450), _finance_user(), db)
            assert refund_update.value.status_code == 409

            before_count = await db.scalar(select(func.count(Payments.id)))
            with pytest.raises(HTTPException) as batch_error:
                await create_paymentss_batch(
                    PaymentsBatchCreateRequest(items=[
                        PaymentsData(
                            customer_id=3, amount_due=100, amount_paid=100,
                            payment_date=datetime(2026, 8, 10, tzinfo=timezone.utc),
                        ),
                        PaymentsData(
                            customer_id=4, amount_due=100, amount_paid=100,
                            payment_date=datetime(2026, 7, 10, tzinfo=timezone.utc),
                        ),
                    ]),
                    _finance_user(),
                    db,
                )
            assert batch_error.value.status_code == 409
            assert await db.scalar(select(func.count(Payments.id))) == before_count
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_all_batch_creates_preflight_and_blank_company_month_uses_persisted_fallback():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            db.add_all([
                MonthlyProfitClose(
                    year_month="2026-07", status="locked", snapshot_json="{}",
                    locked_by="Owner", locked_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                ),
                Company_expenses(
                    id=1, category="software", amount=100, currency="CNY",
                    expense_month="2026-08", expense_date=datetime(2026, 7, 15, tzinfo=timezone.utc),
                    user_id="finance-user",
                ),
            ])
            await db.commit()

            with pytest.raises(HTTPException) as cleared_month_error:
                await update_company_expenses(
                    1,
                    Company_expensesUpdateData(expense_month=""),
                    _finance_user(),
                    db,
                )
            assert cleared_month_error.value.status_code == 409
            await db.refresh(await db.get(Company_expenses, 1))
            assert (await db.get(Company_expenses, 1)).expense_month == "2026-08"

            with pytest.raises(HTTPException):
                await create_expensess_batch(
                    ExpensesBatchCreateRequest(items=[
                        ExpensesData(expense_type="domain", amount=10, expense_date=datetime(2026, 8, 2, tzinfo=timezone.utc)),
                        ExpensesData(expense_type="domain", amount=20, expense_date=datetime(2026, 7, 2, tzinfo=timezone.utc)),
                    ]),
                    _finance_user(),
                    db,
                )
            assert await db.scalar(select(func.count(Expenses.id))) == 0

            with pytest.raises(HTTPException):
                await create_company_expensess_batch(
                    Company_expensesBatchCreateRequest(items=[
                        Company_expensesData(category="software", amount=10, expense_month="2026-08"),
                        Company_expensesData(category="software", amount=20, expense_month="2026-07"),
                    ]),
                    _finance_user(),
                    db,
                )
            assert await db.scalar(select(func.count(Company_expenses.id))) == 1
    finally:
        await engine.dispose()
