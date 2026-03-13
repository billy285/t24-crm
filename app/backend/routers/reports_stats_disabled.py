# @File: backend/routers/reports_stats master
# @Desc: JSON stats for monthly profit, default by currency (no implicit cross-currency mix).
import logging
from typing import List, Optional, Dict
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

class ProfitMonthlyRow(BaseModel):
    month: str = Field(..., description="YYYY-MM")
    currency: Optional[str] = Field(default="USD", description="Currency when not using base currency")
    base_currency: Optional[str] = Field(default=None, description="When base currency conversion is applied")
    revenue_gross: float
    deduction_rate: float
    deduction_amount: float
    cost: float
    profit: float
    notes: Optional[str] = None

def ym_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m")

def clamp_ym(s: str) -> str:
    try:
        d = datetime.strptime(s[:10], "%Y-%m-%d")
        return d.strftime("%Y-%m")
    except Exception:
        return s[:7] if len(s) >= 7 else s

@router.get("/profit-monthly.json", response_model=List[ProfitMonthlyRow])
async def profit_monthly_json(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    currency: Optional[str] = Query(None, description="e.g., USD or CNY. Default: split by currency, this endpoint returns USD part only unless base_currency specified."),
    base_currency: Optional[str] = Query(None, description="If provided, aggregate into base currency (reserved for future use)"),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    JSON monthly detail:
    - Default: split by currency, shows USD-only (customer revenue and customer expenses are in USD)
    - Company expenses are CNY and are NOT mixed here by default
    - If `base_currency` is provided (future), conversion/merge could be applied (not implemented yet)
    """
    try:
        # Normalize boundaries
        try:
            start_dt = datetime.strptime(start, "%Y-%m-%d")
            end_dt = datetime.strptime(end, "%Y-%m-%d")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid date format, expect YYYY-MM-DD")

        if end_dt < start_dt:
            raise HTTPException(status_code=400, detail="end must be greater than or equal to start")

        # Collect USD revenue from payments within range
        payments_rows = []
        try:
            pay_sql = text("""
                SELECT payment_date, amount_paid
                FROM payments
                WHERE payment_date IS NOT NULL
                  AND payment_date >= :start
                  AND payment_date <= :end
            """)
            res = await db.execute(pay_sql, {"start": start_dt, "end": end_dt})
            payments_rows = res.fetchall()
        except Exception as e:
            logging.warning(f"Query payments failed: {e}")

        # Collect USD customer costs from expenses (stored as monthly YYYY-MM)
        expenses_rows = []
        try:
            # We fetch all expense_month strings and amounts and filter in Python by range
            exp_sql = text("""
                SELECT expense_month, amount
                FROM expenses
                WHERE expense_month IS NOT NULL
            """)
            res = await db.execute(exp_sql)
            expenses_rows = res.fetchall()
        except Exception as e:
            logging.warning(f"Query expenses failed: {e}")

        # Build month keys within range
        ym_start = ym_str(start_dt)
        ym_end = ym_str(end_dt)

        def in_range_ym(ym: str) -> bool:
            return (ym >= ym_start) and (ym <= ym_end)

        # Aggregate revenue and cost by YYYY-MM
        by_month: Dict[str, Dict[str, float]] = {}
        for row in payments_rows:
            pd: datetime = row[0]
            amt = float(row[1] or 0)
            ym = ym_str(pd)
            if not in_range_ym(ym):
                continue
            bucket = by_month.setdefault(ym, {"revenue": 0.0, "cost": 0.0})
            bucket["revenue"] += amt

        for row in expenses_rows:
            ym = str(row[0] or "")
            if len(ym) >= 7:
                ym = ym[:7]
            else:
                continue
            if not in_range_ym(ym):
                continue
            amt = float(row[1] or 0)
            bucket = by_month.setdefault(ym, {"revenue": 0.0, "cost": 0.0})
            bucket["cost"] += amt

        # Fetch deduction rates within months
        ded_sql = text("""
            SELECT year_month, rate
            FROM monthly_deduction_rates
        """)
        rates: Dict[str, float] = {}
        try:
            res = await db.execute(ded_sql)
            for ym, rate in res.fetchall():
                rates[str(ym)[:7]] = float(rate)
        except Exception as e:
            logging.warning(f"Query monthly_deduction_rates failed: {e}")

        # Build rows
        rows: List[ProfitMonthlyRow] = []
        for ym in sorted(by_month.keys()):
            revenue = round(by_month[ym]["revenue"], 2)
            cost = round(by_month[ym]["cost"], 2)
            rate = rates.get(ym, 0.15)  # default 15%
            deduction_amount = round(revenue * rate, 2)
            profit = round(revenue - deduction_amount - cost, 2)
            note = None if ym in rates else "rate from default 0.15"
            rows.append(ProfitMonthlyRow(
                month=ym,
                currency="USD" if not base_currency else None,
                base_currency=base_currency if base_currency else None,
                revenue_gross=revenue,
                deduction_rate=rate,
                deduction_amount=deduction_amount,
                cost=cost,
                profit=profit,
                notes=note
            ))

        # If no data and range valid, return empty array
        return rows

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"profit_monthly_json error: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate monthly report JSON")