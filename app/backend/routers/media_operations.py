"""Customer-scoped native operations API; no platform publishing or billing."""
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from services import media_operations as service


async def no_store(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(prefix="/api/v1/media-operations", tags=["media-operations"], dependencies=[Depends(no_store)])
Platform = Literal["google_business", "facebook", "instagram", "tiktok", "xiaohongshu", "other"]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateTask(StrictInput):
    client_request_id: str = Field(min_length=36, max_length=36)
    customer_id: int = Field(ge=1, strict=True)
    service_progress_id: int | None = Field(None, ge=1, strict=True)
    title: str = Field(min_length=1, max_length=200)
    platform: Platform
    due_at: str = Field(min_length=10, max_length=80)
    timezone: str = Field("America/New_York", min_length=1, max_length=80)
    assignee_id: int | None = Field(None, ge=1, strict=True)
    content: str = Field("", max_length=20000)
    material_id: int | None = Field(None, ge=1, strict=True)


class EditTask(StrictInput):
    expected_revision: int = Field(ge=1, strict=True)
    title: str | None = Field(None, min_length=1, max_length=200)
    platform: Platform | None = None
    due_at: str | None = Field(None, min_length=10, max_length=80)
    timezone: str | None = Field(None, min_length=1, max_length=80)
    content: str | None = Field(None, max_length=20000)
    material_id: int | None = Field(None, ge=1, strict=True)
    assignee_id: int | None = Field(None, ge=1, strict=True)


class TransitionTask(StrictInput):
    expected_revision: int = Field(ge=1, strict=True)
    request_id: str = Field(min_length=36, max_length=36)
    action: Literal["submit", "approve", "return", "complete", "block", "resume"]
    note: str | None = Field(None, max_length=2000)
    proof_url: str | None = Field(None, max_length=2048)
    proof_material_id: int | None = Field(None, ge=1, strict=True)


@router.get("/options")
async def options(user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.options(db, user)


@router.get("")
async def list_tasks(status: str | None = None, customer_id: int | None = Query(None, ge=1), q: str | None = Query(None, max_length=100),
                     skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=50),
                     user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.list_tasks(db, user, status=status, customer_id=customer_id, q=q, skip=skip, limit=limit)


@router.post("", status_code=201)
async def create_task(value: CreateTask, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.create_task(db, user, **value.model_dump())


@router.get("/{task_id}")
async def get_task(task_id: int, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.get_task(db, user, task_id)


@router.put("/{task_id}")
async def edit_task(task_id: int, value: EditTask, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.edit_task(db, user, task_id, **value.model_dump(exclude_unset=True))


@router.post("/{task_id}/transition")
async def transition_task(task_id: int, value: TransitionTask, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.transition_task(db, user, task_id, **value.model_dump())
