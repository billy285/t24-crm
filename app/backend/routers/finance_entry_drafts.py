"""Clerk registration workspace, independent from owner-only ledger APIs."""
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from services import finance_entry_drafts as service


async def no_store(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(prefix="/api/v1/finance-entry-drafts", tags=["finance-entry-drafts"], dependencies=[Depends(no_store)])


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateDraft(StrictInput):
    client_request_id: str = Field(min_length=8, max_length=64)
    kind: Literal["manual_receipt", "customer_expense", "company_expense"]
    customer_id: int | None = Field(None, ge=1, strict=True)
    payload: dict


class EditDraft(StrictInput):
    expected_revision: int = Field(ge=1, strict=True)
    payload: dict


class DraftAction(StrictInput):
    expected_revision: int = Field(ge=1, strict=True)
    request_id: str = Field(min_length=8, max_length=64)


class ReasonAction(DraftAction):
    reason: str = Field(min_length=3, max_length=1000)


@router.get("/customer-options")
async def customer_options(user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.customer_options(db, user)


@router.get("")
async def list_drafts(status: str | None = None, skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.list_drafts(db, user, status=status, skip=skip, limit=limit)


@router.post("", status_code=201)
async def create_draft(value: CreateDraft, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.create_draft(db, user, **value.model_dump())


@router.get("/{draft_id}")
async def get_draft(draft_id: int, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return service.draft_data(await service.authorize_draft(db, user, draft_id), user)


@router.put("/{draft_id}")
async def edit_draft(draft_id: int, value: EditDraft, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.edit_draft(db, user, draft_id, **value.model_dump())


@router.post("/{draft_id}/submit")
async def submit_draft(draft_id: int, value: DraftAction, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.transition_draft(db, user, draft_id, action="submit", **value.model_dump())


@router.post("/{draft_id}/return")
async def return_draft(draft_id: int, value: ReasonAction, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.transition_draft(db, user, draft_id, action="return", **value.model_dump())


@router.post("/{draft_id}/void")
async def void_draft(draft_id: int, value: ReasonAction, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.transition_draft(db, user, draft_id, action="void", **value.model_dump())


@router.post("/{draft_id}/post")
async def post_draft(draft_id: int, value: DraftAction, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.transition_draft(db, user, draft_id, action="post", **value.model_dump())
