"""Read-only renewal observations and explicitly assigned delivery checklists."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user, get_owner_user
from schemas.auth import UserResponse
from routers.sales_deal_handoffs import mutate
from services import service_follow_through as service

router = APIRouter(prefix="/api/v1/service-follow-through", tags=["service-follow-through"])


class InitializeKickoff(BaseModel):
    model_config = ConfigDict(extra="forbid")
    first_delivery_due_date: date


class UpdateKickoffItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    revision: int = Field(ge=1)
    status: Literal["pending", "blocked", "completed"]
    due_date: date
    note: str = Field(default="", max_length=2000)
    evidence: str = Field(default="", max_length=2000)
    completed_on: date | None = None


def private(response):
    response.headers["Cache-Control"] = "private, no-store"


@router.get("/owner-overview")
async def owner_overview(response: Response, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await service.owner_overview(db, user)


@router.get("/renewals")
async def renewals(response: Response, status: Literal["all", "attention", "unconnected", "upcoming"] = "all",
                   user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await service.renewals(db, user, status)


@router.get("/kickoffs")
async def kickoffs(response: Response, status: Literal["all", "missing", "in_progress", "overdue", "completed", "blocked"] = "all",
                   user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await service.kickoffs(db, user, status)


@router.get("/kickoffs/{handoff_id}")
async def kickoff(handoff_id: int, response: Response, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await service.kickoff_detail(db, handoff_id, user)


@router.post("/kickoffs/{handoff_id}/initialize")
async def initialize(handoff_id: int, payload: InitializeKickoff, response: Response,
                     user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await mutate(db, lambda: service.initialize_kickoff(db, handoff_id, payload, user))


@router.patch("/kickoffs/{handoff_id}/items/{item_key}")
async def update(handoff_id: int, item_key: str, payload: UpdateKickoffItem, response: Response,
                 user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await mutate(db, lambda: service.update_kickoff_item(db, handoff_id, item_key, payload, user))
