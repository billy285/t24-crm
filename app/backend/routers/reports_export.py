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
from dependencies.auth import get_finance_user
from schemas.auth import UserResponse
from utils.monthly_deduction_sql import create_default_sql, create_rates_sql, is_sqlite

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/reports", tags=["reports"])
MANAGEMENT_FEE_KEY = "management_fee"
ADS_FEE_KEY = "ads_fee"
ADS_RECHARGE_DEDUCTION_RATE = 0.01
STRIPE_PLATFORM_FEE_RATE = 0.029
STRIPE_PLATFORM_FEE_FIXED = 0.3
LEGACY_PAYMENT_METHOD_MAP = {
    "subscription_debit": "stripe",
}


# Utilities
def ym_key(dt: date) -> str:
    return f"{dt.year:04d}-{dt.month:02d}"


def _coerce_date(value: object) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return None
        try:
            return datetime.fromisoformat(text_value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return datetime.strptime(text_value[:10], "%Y-%m-%d").date()
            except ValueError:
                return None
    return None


async def _get_default_deduction_rate(db: AsyncSession) -> float:
    # Default 0.15 if no override
    await db.execute(text(create_default_sql(db)))
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
    await db.execute(text(create_rates_sql(db)))

    rows = await db.execute(text(f"SELECT year_month, rate FROM monthly_deduction_rates WHERE 1=1 {where}"), params)
    mapped: Dict[str, float] = {}
    for r in rows.mappings().all():
        ym = r["year_month"]
        if isinstance(ym, datetime):
            ym = ym.date()
        if isinstance(ym, date):
            k = f"{ym.year:04d}-{ym.month:02d}"
        else:
            k = str(ym)[:7]
        mapped[k] = float(r["rate"])
    return mapped


def _calculate_deductions(
    revenue: float,
    management_revenue: float,
    ads_recharge_revenue: float,
    management_rate: float,
) -> Tuple[float, float, float, float]:
    management_deduction = management_revenue * management_rate
    ads_deduction = ads_recharge_revenue * ADS_RECHARGE_DEDUCTION_RATE
    deduction_amount = management_deduction + ads_deduction
    effective_rate = (deduction_amount / revenue) if revenue > 0 else 0.0
    return management_deduction, ads_deduction, deduction_amount, effective_rate


def _normalize_payment_method(method: Optional[str]) -> str:
    if not method:
        return "other"
    return LEGACY_PAYMENT_METHOD_MAP.get(method, method)


def _is_stripe_subscription_payment(payment_method: Optional[str], payment_mode: Optional[str]) -> bool:
    method = _normalize_payment_method(payment_method)
    return method == "stripe" or (payment_mode == "subscription_auto" and not payment_method)


def _calculate_stripe_platform_fee(amount_paid: float, payment_method: Optional[str], payment_mode: Optional[str]) -> float:
    if amount_paid <= 0 or not _is_stripe_subscription_payment(payment_method, payment_mode):
        return 0.0
    return round(amount_paid * STRIPE_PLATFORM_FEE_RATE + STRIPE_PLATFORM_FEE_FIXED, 2)


def _optional_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _derive_management_revenue(income_type: Optional[str], amount_paid: float, stored_amount: object) -> float:
    stored = _optional_float(stored_amount)
    if stored is not None:
        return stored
    return amount_paid if income_type == MANAGEMENT_FEE_KEY else 0.0


def _derive_ads_recharge_revenue(income_type: Optional[str], amount_paid: float, stored_amount: object) -> float:
    stored = _optional_float(stored_amount)
    if stored is not None:
        return stored
    return amount_paid if income_type == ADS_FEE_KEY else 0.0


async def _get_table_columns(db: AsyncSession, table_name: str) -> set[str]:
    if is_sqlite(db):
        res = await db.execute(text(f"PRAGMA table_info({table_name})"))
        return {str(row[1]) for row in res.fetchall()}

    res = await db.execute(
        text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = :table_name
              AND table_schema = current_schema()
        """),
        {"table_name": table_name},
    )
    return {str(row[0]) for row in res.fetchall()}


def _select_existing_column(columns: set[str], column_name: str) -> str:
    if column_name in columns:
        return column_name
    return f"NULL AS {column_name}"


def _build_deduction_note(
    management_revenue: float,
    ads_recharge_revenue: float,
    management_rate: float,
    stripe_platform_fee: float = 0.0,
    fallback_note: Optional[str] = None,
    base_currency: Optional[str] = None,
) -> str:
    parts: List[str] = []
    if management_revenue > 0:
        parts.append(f"management_fee {round(management_rate * 100)}%")
    if ads_recharge_revenue > 0:
        parts.append("ads recharge 1%")
    if stripe_platform_fee > 0:
        parts.append("Stripe fee 2.9% + 0.30/payment")
    if fallback_note:
        parts.append(fallback_note)
    if base_currency is not None:
        parts.append("FX N/A (awaiting design)")
    return "; ".join(parts)


async def _aggregate_monthly(db: AsyncSession, start: Optional[str], end: Optional[str]) -> Tuple[Dict[str, Dict[str, Dict[str, float]]], List[str]]:
    """
    Returns:
      data[currency][YYYY-MM] = dict(revenue_gross, cost)
      months = sorted YYYY-MM keys union
    Assumptions:
      - payments.amount_paid (USD), payments.payment_date
      - expenses.amount (USD), expenses.expense_month (YYYY-MM string) fallback created_at
      - company_expenses.amount (native currency; legacy blank currency treated as CNY), company_expenses.expense_month (YYYY-MM string) fallback created_at
    """
    # Revenue (USD)
    revenue_map: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    management_revenue_map: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    ads_recharge_map: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    cost_map: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    stripe_platform_fee_map: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    months_set = set()

    # Date filtering
    start_dt = datetime.strptime(start, "%Y-%m-%d").date() if start else None
    end_dt = datetime.strptime(end, "%Y-%m-%d").date() if end else None

    # Payments -> USD revenue by month
    payment_columns = await _get_table_columns(db, "payments")
    payment_optional_columns = [
        _select_existing_column(payment_columns, "payment_method"),
        _select_existing_column(payment_columns, "payment_mode"),
        _select_existing_column(payment_columns, "management_amount"),
        _select_existing_column(payment_columns, "ads_recharge_amount"),
        _select_existing_column(payment_columns, "stripe_fee_amount"),
    ]
    q = f"""
        SELECT customer_id, customer_name, income_type, amount_paid, payment_date,
               {", ".join(payment_optional_columns)}
        FROM payments
    """
    # naive filter on backend side after fetch to keep SQL simple/portable
    res = await db.execute(text(q))
    for row in res.mappings().all():
        income_type = row.get("income_type") or None
        amt = float(row.get("amount_paid") or 0)
        d = _coerce_date(row.get("payment_date") or None)
        if not d:
            continue
        if start_dt and d < start_dt:
            continue
        if end_dt and d > end_dt:
            continue
        ym = ym_key(d)
        months_set.add(ym)
        revenue_map["USD"][ym] += amt
        stored_stripe_fee = _optional_float(row.get("stripe_fee_amount"))
        stripe_platform_fee = stored_stripe_fee if stored_stripe_fee is not None else _calculate_stripe_platform_fee(
            amt,
            row.get("payment_method") or None,
            row.get("payment_mode") or None,
        )
        if stripe_platform_fee > 0:
            stripe_platform_fee_map["USD"][ym] += stripe_platform_fee
            cost_map["USD"][ym] += stripe_platform_fee
        management_revenue_map["USD"][ym] += _derive_management_revenue(income_type, amt, row.get("management_amount"))
        ads_recharge_map["USD"][ym] += _derive_ads_recharge_revenue(income_type, amt, row.get("ads_recharge_amount"))

    # Customer expenses (USD)
    expense_columns = await _get_table_columns(db, "expenses")
    expense_currency_column = _select_existing_column(expense_columns, "currency")
    res = await db.execute(text(f"SELECT customer_id, customer_name, expense_type, amount, {expense_currency_column}, expense_month, created_at FROM expenses"))
    for row in res.mappings().all():
        amt = float(row["amount"] or 0)
        ym = None
        if row["expense_month"] and isinstance(row["expense_month"], str) and len(row["expense_month"]) >= 7:
            ym = row["expense_month"][:7]
        else:
            d = _coerce_date(row.get("created_at"))
            if d:
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
        currency = row.get("currency") if row.get("currency") in ("USD", "CNY") else "USD"
        cost_map[currency][ym] += amt

    # Company operating expenses. Legacy rows created before currency support are treated as CNY.
    res = await db.execute(text("SELECT amount, currency, expense_month, created_at FROM company_expenses"))
    for row in res.mappings().all():
        amt = float(row["amount"] or 0)
        currency = row.get("currency") if row.get("currency") in ("USD", "CNY") else "CNY"
        ym = None
        if row["expense_month"] and isinstance(row["expense_month"], str) and len(row["expense_month"]) >= 7:
            ym = row["expense_month"][:7]
        else:
            d = _coerce_date(row.get("created_at"))
            if d:
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
        cost_map[currency][ym] += amt

    # Combine
    all_data: Dict[str, Dict[str, Dict[str, float]]] = {}
    for cur in set(list(revenue_map.keys()) + list(cost_map.keys())):
        all_data[cur] = {}
        for ym in months_set:
            all_data[cur][ym] = {
                "revenue_gross": revenue_map[cur].get(ym, 0.0),
                "management_revenue": management_revenue_map[cur].get(ym, 0.0),
                "ads_recharge_revenue": ads_recharge_map[cur].get(ym, 0.0),
                "stripe_platform_fee": stripe_platform_fee_map[cur].get(ym, 0.0),
                "cost": cost_map[cur].get(ym, 0.0),
            }

    months_sorted = sorted(months_set)
    return all_data, months_sorted


def _build_csv(rows: List[Dict[str, str]]) -> io.BytesIO:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["month", "currency_or_base", "revenue_gross", "deduction_rate", "deduction_amount", "stripe_platform_fee", "cost", "profit", "notes"])
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
    headers = ["month", "currency_or_base", "revenue_gross", "deduction_rate", "deduction_amount", "stripe_platform_fee", "cost", "profit", "notes"]
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
            management_revenue = float(per_month.get(ym, {}).get("management_revenue", 0.0))
            ads_recharge_revenue = float(per_month.get(ym, {}).get("ads_recharge_revenue", 0.0))
            stripe_platform_fee = float(per_month.get(ym, {}).get("stripe_platform_fee", 0.0))
            cost = float(per_month.get(ym, {}).get("cost", 0.0))
            rate = float(rate_map.get(ym, default_rate))
            _, _, deduction_amt, effective_rate = _calculate_deductions(
                revenue,
                management_revenue,
                ads_recharge_revenue,
                rate,
            )
            profit = revenue - deduction_amt - cost
            result.append({
                "month": ym,
                "currency_or_base": base_currency or cur,
                "revenue_gross": f"{revenue:.2f}",
                "deduction_rate": f"{effective_rate:.4f}",
                "deduction_amount": f"{deduction_amt:.2f}",
                "stripe_platform_fee": f"{stripe_platform_fee:.2f}",
                "cost": f"{cost:.2f}",
                "profit": f"{profit:.2f}",
                "notes": _build_deduction_note(management_revenue, ads_recharge_revenue, rate, stripe_platform_fee=stripe_platform_fee, base_currency=base_currency),
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
    _current_user: UserResponse = Depends(get_finance_user),
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
    _current_user: UserResponse = Depends(get_finance_user),
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
    stripe_platform_fee: float
    cost: float
    profit: float
    notes: Optional[str] = None


@router.get("/profit-monthly.json", response_model=List[ProfitMonthlyJSONRow])
async def profit_monthly_json(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    currency: Optional[str] = Query(None, description="USD or CNY; default returns USD only unless base_currency specified"),
    base_currency: Optional[str] = Query(None, description="If provided, aggregate to base currency (FX conversion reserved)"),
    _current_user: UserResponse = Depends(get_finance_user),
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
                management_revenue = float(per_month.get(ym, {}).get("management_revenue", 0.0))
                ads_recharge_revenue = float(per_month.get(ym, {}).get("ads_recharge_revenue", 0.0))
                stripe_platform_fee = float(per_month.get(ym, {}).get("stripe_platform_fee", 0.0))
                cost = float(per_month.get(ym, {}).get("cost", 0.0))
                if revenue == 0.0 and cost == 0.0:
                    continue
                rate = float(rate_map.get(ym, default_rate))
                _, _, deduction_amt_raw, effective_rate = _calculate_deductions(
                    revenue,
                    management_revenue,
                    ads_recharge_revenue,
                    rate,
                )
                deduction_amt = round(deduction_amt_raw, 2)
                profit = round(revenue - deduction_amt - cost, 2)
                fallback_note = None if ym in rate_map else "rate from monthly config or default 0.15"
                rows.append(ProfitMonthlyJSONRow(
                    month=ym,
                    currency=None if base_currency else cur,
                    base_currency=base_currency if base_currency else None,
                    revenue_gross=round(revenue, 2),
                    deduction_rate=round(effective_rate, 4),
                    deduction_amount=deduction_amt,
                    stripe_platform_fee=round(stripe_platform_fee, 2),
                    cost=round(cost, 2),
                    profit=profit,
                    notes=_build_deduction_note(management_revenue, ads_recharge_revenue, rate, stripe_platform_fee=stripe_platform_fee, fallback_note=fallback_note, base_currency=base_currency)
                ))
        return rows
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"profit_monthly_json failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate monthly report JSON")
