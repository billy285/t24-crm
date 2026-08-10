from datetime import date, datetime, time, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_admin_user, get_finance_user
from schemas.auth import UserResponse
from services.customer_lifecycle import (
    STOP_REASONS,
    apply_lifecycle_action,
    customer_lifecycle_detail,
    lifecycle_overview,
    reconcile_stopped_customer,
    sync_lifecycle_from_payments,
)


router = APIRouter(prefix="/api/v1/customer-lifecycle", tags=["customer-lifecycle"])


def date_at_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def date_at_end(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=timezone.utc)


class LifecycleActionRequest(BaseModel):
    action: Literal["pause", "pending_stop", "resume", "stop", "reactivate", "adjust_start"]
    effective_date: date
    reason_code: Optional[str] = None
    note: Optional[str] = None
    first_payment_id: Optional[int] = None

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


@router.get("/overview")
async def get_lifecycle_overview(
    start_date: date = Query(date(2026, 1, 1)),
    as_of: Optional[date] = Query(None),
    current_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    as_of_date = as_of or date.today()
    if as_of_date < start_date:
        raise HTTPException(status_code=400, detail="统计截止日期不能早于开始日期")
    return await lifecycle_overview(db, date_at_start(start_date), date_at_end(as_of_date))


@router.get("/stop-reasons")
async def get_stop_reasons(current_user: UserResponse = Depends(get_finance_user)):
    return [{"value": value, "label": label} for value, label in STOP_REASONS.items()]


@router.get("/customers/{customer_id}")
async def get_customer_lifecycle(
    customer_id: int,
    current_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await customer_lifecycle_detail(db, customer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/customers/{customer_id}/actions")
async def update_customer_lifecycle(
    customer_id: int,
    request: LifecycleActionRequest,
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await apply_lifecycle_action(
            db,
            customer_id=customer_id,
            action=request.action,
            effective_at=date_at_start(request.effective_date),
            actor_id=str(current_user.id),
            actor_name=current_user.name or current_user.email or "管理员",
            reason_code=request.reason_code,
            note=request.note,
            first_payment_id=request.first_payment_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/customers/{customer_id}/reconcile-closure")
async def reconcile_customer_closure(
    customer_id: int,
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await reconcile_stopped_customer(
            db,
            customer_id=customer_id,
            actor_id=str(current_user.id),
            actor_name=current_user.name or current_user.email or "管理员",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/backfill")
async def backfill_customer_lifecycle(
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await sync_lifecycle_from_payments(db)
