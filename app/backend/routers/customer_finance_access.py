"""Read-only, customer-scoped financial disclosure. No ledger mutations."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from models.payments import Payments
from models.expenses import Expenses
from models.finance_refunds import FinanceRefund
from routers.payments import PaymentsResponse
from routers.expenses import ExpensesResponse
from schemas.auth import UserResponse
from services.customer_permissions import get_customer_permissions
from services.schema_readiness import MONTHLY_DEDUCTION_TABLES, require_tables

router = APIRouter(prefix="/api/v1/entities/customers", tags=["customer-finance-access"])

RECEIPT_FIELDS = (
    "id", "customer_id", "amount_due", "amount_paid", "currency", "payment_date",
    "income_type", "product_name", "payment_mode", "payment_method",
    "outstanding_amount", "billing_cycle", "coverage_start", "coverage_end",
)
REFUND_FIELDS = ("id", "payment_id", "customer_id", "refund_amount", "currency", "refund_date", "status")


@router.get("/{id}/finance-access-data")
async def customer_finance_access_data(
    id: int,
    response: Response,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    permissions = await get_customer_permissions(db, current_user, id)
    if permissions.get("access_level", "none") == "none":
        raise HTTPException(status_code=404, detail="Customer not found")
    level = permissions.get("finance_access", "none")
    if level not in {"status", "receipts", "profit"}:
        raise HTTPException(status_code=403, detail="未获得该客户的财务查看权限")
    response.headers["Cache-Control"] = "private, no-store"
    payments = list((await db.execute(
        select(Payments).where(Payments.customer_id == id)
        .order_by(Payments.payment_date.desc(), Payments.id.desc())
    )).scalars().all())
    latest = next((row.payment_date for row in payments if row.payment_date), None)
    result = {
        "customer_id": id, "finance_access": level,
        "status": {
            "payment_count": len(payments), "last_payment_date": latest,
            "has_outstanding": any((row.outstanding_amount or 0) > 0 for row in payments),
        },
        "payments": [], "refunds": [], "expenses": [], "deduction_rates": {},
    }
    if level == "status":
        return result
    result["payments"] = [
        {key: getattr(row, key) for key in RECEIPT_FIELDS} for row in payments
    ]
    refunds = (await db.execute(
        select(FinanceRefund).where(FinanceRefund.customer_id == id)
        .order_by(FinanceRefund.refund_date.desc(), FinanceRefund.id.desc())
    )).scalars().all()
    result["refunds"] = [{key: getattr(row, key) for key in REFUND_FIELDS} for row in refunds]
    if level == "profit":
        result["payments"] = [PaymentsResponse.model_validate(row).model_dump() for row in payments]
        expenses = (await db.execute(
            select(Expenses).where(Expenses.customer_id == id)
            .order_by(Expenses.expense_date.desc(), Expenses.id.desc())
        )).scalars().all()
        result["expenses"] = [ExpensesResponse.model_validate(row).model_dump() for row in expenses]
        months = {(row.payment_date or row.created_at).strftime("%Y-%m") for row in payments if row.payment_date or row.created_at}
        if months:
            # Read existing snapshots only. Viewing a shared customer must not
            # create deduction snapshots or modify period/closing state.
            await require_tables(db, MONTHLY_DEDUCTION_TABLES)
            rates = (await db.execute(text("SELECT year_month, rate FROM monthly_deduction_rates"))).all()
            result["deduction_rates"] = {
                str(month)[:7]: float(rate) for month, rate in rates if str(month)[:7] in months
            }
    return result
