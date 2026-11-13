"""Company statement matching is owner-only and cannot charge or post income."""
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_owner_user
from schemas.auth import UserResponse
from schemas.stripe_history_reconciliation import Strict
from services import stripe_bank_reconciliation as service


def private(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(prefix="/api/v1/stripe-history-reconciliation/bank", tags=["stripe-bank-reconciliation"], dependencies=[Depends(private)])


class StatementContent(Strict):
    csv_text: str = Field(min_length=1, max_length=service.MAX_CSV_BYTES)


class StatementPreview(StatementContent):
    account_label: str = Field(min_length=2, max_length=80)
    currency: Literal["USD"] = "USD"
    date_format: Literal["ymd", "mdy"] = "ymd"
    date_column: str = Field(min_length=1, max_length=80)
    amount_column: str = Field(min_length=1, max_length=80)
    description_column: str = Field(min_length=1, max_length=80)
    reference_column: str | None = Field(default=None, min_length=1, max_length=80)


class MatchPreview(Strict):
    statement_token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    row_index: int = Field(ge=2, le=service.MAX_ROWS + 1)
    payout_id: str = Field(pattern=r"^po_[A-Za-z0-9_]{1,220}$")


class MatchConfirm(Strict):
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    owner_verified: Literal[True]
    note: str = Field(min_length=3, max_length=1000)


class MatchVoid(Strict):
    owner_verified: Literal[True]
    note: str = Field(min_length=3, max_length=1000)


@router.get("/overview")
async def overview(user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    return await service.overview(db, user)


@router.get("/payouts")
async def payouts(starting_after: str | None = Query(None, pattern=r"^po_[A-Za-z0-9_]{1,220}$"), user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    return await service.payouts(db, user, starting_after)


@router.post("/statements/inspect")
async def inspect(value: StatementContent, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    return await service.inspect_statement(db, user, value)


@router.post("/statements/preview")
async def preview_statement(value: StatementPreview, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    return await service.preview_statement(db, user, value)


@router.post("/matches/preview")
async def preview_match(value: MatchPreview, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    return await service.preview_match(db, user, value)


@router.post("/matches/confirm")
async def confirm_match(value: MatchConfirm, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    return await service.confirm_match(db, user, value)


@router.post("/matches/{match_id}/void")
async def void_match(match_id: int, value: MatchVoid, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    return await service.void_match(db, user, match_id, value)
