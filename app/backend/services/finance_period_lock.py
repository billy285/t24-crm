from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Iterable, Mapping, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.finance_profit_closes import MonthlyProfitClose
from models.finance_refunds import FinanceRefund


MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def financial_month(value: object) -> Optional[str]:
    """Return YYYY-MM for values that can authoritatively identify a finance month."""
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m")
    text = str(value).strip()
    candidate = text[:7]
    return candidate if MONTH_PATTERN.fullmatch(candidate) else None


def _field(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _financial_date(value: object) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def financial_month_span(start: object, end: object) -> set[str]:
    """Return months touched by the half-open finance period [start, end)."""
    start_day = _financial_date(start)
    end_day = _financial_date(end)
    if not start_day or not end_day or end_day <= start_day:
        return set()
    last_day = end_day - timedelta(days=1)
    cursor = date(start_day.year, start_day.month, 1)
    last_month = date(last_day.year, last_day.month, 1)
    months: set[str] = set()
    while cursor <= last_month:
        months.add(cursor.strftime("%Y-%m"))
        cursor = date(
            cursor.year + (cursor.month == 12),
            1 if cursor.month == 12 else cursor.month + 1,
            1,
        )
    return months


def payment_profit_months(payment: object) -> set[str]:
    """Return every month whose formal result can depend on a payment."""
    months: set[str] = set()
    receipt_month = financial_month(_field(payment, "payment_date") or _field(payment, "created_at"))
    if receipt_month:
        months.add(receipt_month)
    months.update(
        financial_month_span(
            _field(payment, "coverage_start"),
            _field(payment, "coverage_end"),
        )
    )
    return months


async def ensure_profit_months_open(
    db: AsyncSession,
    months: Iterable[object],
    *,
    action: str = "修改财务记录",
) -> None:
    """Reject writes touching a month whose formal profit snapshot is locked.

    Callers must pass both the existing and proposed month for move/update operations,
    so a record cannot be moved out of or into a locked period.
    """
    normalized = sorted({month for value in months if (month := financial_month(value))})
    if not normalized:
        return
    locked = (
        await db.execute(
            select(MonthlyProfitClose.year_month).where(
                MonthlyProfitClose.year_month.in_(normalized),
                MonthlyProfitClose.status == "locked",
            )
        )
    ).scalars().all()
    if locked:
        labels = "、".join(sorted(set(locked)))
        raise HTTPException(
            status_code=409,
            detail=f"{labels} 已完成经营利润月结，不能{action}；请由管理员填写原因重新打开月结后再操作",
        )


async def ensure_payment_writes_open(
    db: AsyncSession,
    payments: Iterable[object],
    *,
    payment_ids: Iterable[int] = (),
    action: str = "修改收款",
) -> None:
    """Protect receipt, revenue-recognition and associated refund months."""
    months: set[str] = set()
    for payment in payments:
        if payment is not None:
            months.update(payment_profit_months(payment))

    ids = sorted({int(value) for value in payment_ids if value})
    if ids:
        refund_dates = (
            await db.execute(
                select(FinanceRefund.refund_date).where(
                    FinanceRefund.payment_id.in_(ids),
                    FinanceRefund.status == "completed",
                )
            )
        ).scalars().all()
        months.update(
            month for value in refund_dates if (month := financial_month(value))
        )

    await ensure_profit_months_open(db, months, action=action)
