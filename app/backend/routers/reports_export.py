import csv
import io
import logging
from collections import defaultdict
from datetime import datetime, date
from typing import Dict, List, Tuple, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel  # added for JSON schema
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from core.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


# Utilities
def ym_key(dt: date) -> str:
    return f"{dt.year:04d}-{dt.month:02d}"


async def _get_default_deduction_rate(db: AsyncSession) -> float:
    # Default 0.15 if no override
    await db.execute(text("""
CREATE TABLE IF NOT EXISTS monthly_deduction_defaults (
  id SERIAL PRIMARY KEY,
  rate NUMERIC(5,4) NOT NULL DEFAULT 0.15,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""))
    res = await db.execute(text("SELECT rate FROM monthly_deduction_defaults ORDER BY id DESC LIMIT 1"))
    row = res.fetchone()
    if row and row[0] is not None:
        return float(row[0])
    return 0.15




async def _get_monthly_deduction_map(db: AsyncSession, start_ym: Optional[str], end_ym: Optional[str]) -> Dict[str, float]:
    where = ""
    params = {}
    if start_ym:
        where += " AND year_month >= :s"
        y_s, m_s = map(int, start_ym.split("-"))
        params["s"] = date(y_s, m_s, 1)
    if end_ym:
        where += " AND year_month <= :e"
        y_e, m_e = map(int, end_ym.split("-"))
        params["e"] = date(y_e, m_e, 1)

    # Ensure table exists in a separate statement (asyncpg disallows multi-statement prepared exec)
    await db.execute(text("""
CREATE TABLE IF NOT EXISTS monthly_deduction_rates (
  id SERIAL PRIMARY KEY,
  year_month DATE UNIQUE NOT NULL,
  rate NUMERIC(5,4) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""))

    rows = await db.execute(text(f"SELECT year_month, rate FROM monthly_deduction_rates WHERE 1=1 {where}"), params)
    mapped: Dict[str, float] = {}
    for r in rows.mappings().all():
        ym = r["year_month"]
        k = f"{ym.year:04d}-{ym.month:02d}"
        mapped[k] = float(r["rate"])
    return mapped


async def _aggregate_monthly(db: AsyncSession, start: Optional[str], end: Optional[str]) -> Tuple[Dict[str, Dict[str, float]], List[str]]:
    """
    Returns:
      data[currency][YYYY-MM] = dict(revenue_gross, cost)
      months = sorted YYYY-MM keys union
    Assumptions:
      - payments.amount_paid (USD), payments.payment_date
      - expenses.amount (USD), expenses.expense_month (YYYY-MM string) fallback created_at
      - company_expenses.amount (CNY), company_expenses.expense_month (YYYY-MM string) fallback created_at
    """
    # Revenue (USD)
    revenue_map: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    cost_map: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    months_set = set()

    # Date filtering
    start_dt = datetime.strptime(start, "%Y-%m-%d").date() if start else None
    end_dt = datetime.strptime(end, "%Y-%m-%d").date() if end else None

    # Payments -> USD revenue by month
    q = "SELECT amount_paid, payment_date FROM payments"
    # naive filter on backend side after fetch to keep SQL simple/portable
    res = await db.execute(text(q))
    for row in res.fetchall():
        amt = float(row[0] or 0)
        pdt = row[1] or None
        if not pdt:
            continue
        if isinstance(pdt, datetime):
            d = pdt.date()
        elif isinstance(pdt, date):
            d = pdt
        else:
            continue
        if start_dt and d < start_dt:
            continue
        if end_dt and d > end_dt:
            continue
        ym = ym_key(d)
        months_set.add(ym)
        revenue_map["USD"][ym] += amt

    # Customer expenses (USD)
    res = await db.execute(text("SELECT amount, expense_month, created_at FROM expenses"))
    for row in res.mappings().all():
        amt = float(row["amount"] or 0)
        ym = None
        if row["expense_month"] and isinstance(row["expense_month"], str) and len(row["expense_month"]) >= 7:
            ym = row["expense_month"][:7]
        else:
            ca = row.get("created_at")
            if ca:
                d = ca if isinstance(ca, date) else ca.date()
                ym = ym_key(d)
        if not ym:
            continue
        # filter by constructed date range if provided
        if start_dt or end_dt:
            y, m = ym.split("-")
            d = date(int(y), int(m), 1)
            if start_dt and d < date(start_dt.year, start_dt.month, 1):
                continue
            if end_dt and d > date(end_dt.year, end_dt.month, 1):
                continue
        months_set.add(ym)
        cost_map["USD"][ym] += amt

    # Company expenses (CNY)
    res = await db.execute(text("SELECT amount, expense_month, created_at FROM company_expenses"))
    for row in res.mappings().all():
        amt = float(row["amount"] or 0)
        ym = None
        if row["expense_month"] and isinstance(row["expense_month"], str) and len(row["expense_month"]) >= 7:
            ym = row["expense_month"][:7]
        else:
            ca = row.get("created_at")
            if ca:
                d = ca if isinstance(ca, date) else ca.date()
                ym = ym_key(d)
        if not ym:
            continue
        if start_dt or end_dt:
            y, m = ym.split("-")
            d = date(int(y), int(m), 1)
            if start_dt and d < date(start_dt.year, start_dt.month, 1):
                continue
            if end_dt and d > date(end_dt.year, end_dt.month, 1):
                continue
        months_set.add(ym)
        cost_map["CNY"][ym] += amt

    # Combine
    all_data: Dict[str, Dict[str, Dict[str, float]]] = {}
    for cur in set(list(revenue_map.keys()) + list(cost_map.keys())):
        all_data[cur] = {}
        for ym in months_set:
            all_data[cur][ym] = {
                "revenue_gross": revenue_map[cur].get(ym, 0.0),
                "cost": cost_map[cur].get(ym, 0.0),
            }

    months_sorted = sorted(months_set)
    return all_data, months_sorted


def _build_csv(rows: List[Dict[str, str]]) -> io.BytesIO:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["month", "currency_or_base", "revenue_gross", "deduction_rate", "deduction_amount", "cost", "profit", "notes"])
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    out = io.BytesIO()
    content = buf.getvalue()
    # Optional BOM for Excel compatibility
    out.write("\ufeff".encode("utf-8"))
    out.write(content.encode("utf-8"))
    out.seek(0)
    return out


def _build_xlsx(rows: List[Dict[str, str]]) -> io.BytesIO:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "profit_monthly"
    headers = ["month", "currency_or_base", "revenue_gross", "deduction_rate", "deduction_amount", "cost", "profit", "notes"]
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h, "") for h in headers])
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out


def _apply_deductions(rows_in: Dict[str, Dict[str, Dict[str, float]]], months: List[str], rate_map: Dict[str, float], default_rate: float, base_currency: Optional[str]) -> List[Dict[str, str]]:
    """
    For MVP:
      - No FX conversion (base_currency accepted, but rows remain per original currency).
      - Deduction applied only on revenue (per month).
    """
    result: List[Dict[str, str]] = []
    for cur, per_month in rows_in.items():
        for ym in months:
            revenue = float(per_month.get(ym, {}).get("revenue_gross", 0.0))
            cost = float(per_month.get(ym, {}).get("cost", 0.0))
            rate = float(rate_map.get(ym, default_rate))
            deduction_amt = revenue * rate
            profit = revenue - deduction_amt - cost
            result.append({
                "month": ym,
                "currency_or_base": base_currency or cur,
                "revenue_gross": f"{revenue:.2f}",
                "deduction_rate": f"{rate:.4f}",
                "deduction_amount": f"{deduction_amt:.2f}",
                "cost": f"{cost:.2f}",
                "profit": f"{profit:.2f}",
                "notes": "" if base_currency is None else "FX N/A (awaiting design)",
            })
    # stable sort by month then label
    result.sort(key=lambda r: (r["month"], r["currency_or_base"]))
    return result


@router.get("/profit-monthly.csv")
async def export_profit_monthly_csv(
    request: Request,
    start: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="YYYY-MM-DD"),
    currency: Optional[str] = Query(None, description="Filter currency: USD or CNY"),
    base_currency: Optional[str] = Query(None, description="If provided, target base currency for display (FX conversion pending)"),
    db: AsyncSession = Depends(get_db),
):
    try:
        data, months = await _aggregate_monthly(db, start, end)
        if currency:
            data = {currency: data.get(currency, {})}
        default_rate = await _get_default_deduction_rate(db)
        rate_map = await _get_monthly_deduction_map(db, months[0] if months else None, months[-1] if months else None)
        rows = _apply_deductions(data, months, rate_map, default_rate, base_currency)
        out = _build_csv(rows)
        filename = f"profit_monthly_{(start or 'start')}_{(end or 'end')}.csv"
        return StreamingResponse(out, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    except Exception as e:
        logger.error(f"CSV export failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to export CSV")


@router.get("/profit-monthly.xlsx")
async def export_profit_monthly_xlsx(
    request: Request,
    start: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="YYYY-MM-DD"),
    currency: Optional[str] = Query(None, description="Filter currency: USD or CNY"),
    base_currency: Optional[str] = Query(None, description="If provided, target base currency for display (FX conversion pending)"),
    db: AsyncSession = Depends(get_db),
):
    try:
        data, months = await _aggregate_monthly(db, start, end)
        if currency:
            data = {currency: data.get(currency, {})}
        default_rate = await _get_default_deduction_rate(db)
        rate_map = await _get_monthly_deduction_map(db, months[0] if months else None, months[-1] if months else None)
        rows = _apply_deductions(data, months, rate_map, default_rate, base_currency)
        out = _build_xlsx(rows)
        filename = f"profit_monthly_{(start or 'start')}_{(end or 'end')}.xlsx"
        return StreamingResponse(out, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    except Exception as e:
        logger.error(f"XLSX export failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to export XLSX")


# ---- JSON monthly detail ----
class ProfitMonthlyJSONRow(BaseModel):
    month: str
    currency: Optional[str] = None
    base_currency: Optional[str] = None
    revenue_gross: float
    deduction_rate: float
    deduction_amount: float
    cost: float
    profit: float
    notes: Optional[str] = None


@router.get("/profit-monthly.json", response_model=List[ProfitMonthlyJSONRow])
async def profit_monthly_json(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    currency: Optional[str] = Query(None, description="USD or CNY; default returns USD only unless base_currency specified"),
    base_currency: Optional[str] = Query(None, description="If provided, aggregate to base currency (FX conversion reserved)"),
    db: AsyncSession = Depends(get_db),
):
    try:
        # Validate date format
        try:
            datetime.strptime(start, "%Y-%m-%d")
            datetime.strptime(end, "%Y-%m-%d")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid date format, expect YYYY-MM-DD")

        data, months = await _aggregate_monthly(db, start, end)

        # Default behavior: if no currency and no base_currency, return USD only
        selected: Dict[str, Dict[str, Dict[str, float]]] = {}
        if base_currency:
            # Placeholder: still rely on native currency buckets. No FX conversion in MVP.
            # Return USD bucket but mark base_currency.
            if currency:
                if currency in data:
                    selected[currency] = data.get(currency, {})
            else:
                if "USD" in data:
                    selected["USD"] = data.get("USD", {})
        else:
            if currency:
                selected[currency] = data.get(currency, {})
            else:
                if "USD" in data:
                    selected["USD"] = data.get("USD", {})

        default_rate = await _get_default_deduction_rate(db)
        rate_map = await _get_monthly_deduction_map(db, months[0] if months else None, months[-1] if months else None)

        rows: List[ProfitMonthlyJSONRow] = []
        for cur, per_month in selected.items():
            for ym in sorted(months):
                revenue = float(per_month.get(ym, {}).get("revenue_gross", 0.0))
                cost = float(per_month.get(ym, {}).get("cost", 0.0))
                if revenue == 0.0 and cost == 0.0:
                    continue
                rate = float(rate_map.get(ym, default_rate))
                deduction_amt = round(revenue * rate, 2)
                profit = round(revenue - deduction_amt - cost, 2)
                note = None if ym in rate_map else "rate from monthly config or default 0.15"
                rows.append(ProfitMonthlyJSONRow(
                    month=ym,
                    currency=None if base_currency else cur,
                    base_currency=base_currency if base_currency else None,
                    revenue_gross=round(revenue, 2),
                    deduction_rate=rate,
                    deduction_amount=deduction_amt,
                    cost=round(cost, 2),
                    profit=profit,
                    notes=note
                ))
        return rows
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"profit_monthly_json failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate monthly report JSON")