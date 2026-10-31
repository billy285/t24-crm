"""One brief, separately scoped/reviewed drafts for each target platform."""
from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from services import media_planning as service
from routers.media_operations import Platform


async def no_store(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(prefix="/api/v1/media-planning", tags=["media-planning"], dependencies=[Depends(no_store)])


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Variant(Strict):
    platform: Platform
    content: str = Field("", max_length=20000)
    due_at: str = Field(min_length=10, max_length=80)
    timezone: str = Field(min_length=1, max_length=80)


class PlanInput(Strict):
    request_id: str = Field(min_length=36, max_length=36)
    customer_id: int = Field(ge=1, strict=True)
    title: str = Field(min_length=1, max_length=200)
    brief: str = Field("", max_length=2000)
    assignee_id: int | None = Field(None, ge=1, strict=True)
    variants: list[Variant] = Field(min_length=1, max_length=6)


@router.get("/calendar")
async def calendar(start: str = Query(max_length=80), end: str = Query(max_length=80), customer_id: int | None = Query(None, ge=1),
                   platform: Platform | None = None, skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200),
                   user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.calendar(db, user, start=start, end=end, customer_id=customer_id, platform=platform, skip=skip, limit=limit)


@router.get("/summary")
async def summary(start: str = Query(max_length=80), end: str = Query(max_length=80), customer_id: int | None = Query(None, ge=1),
                  user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.summary(db, user, start=start, end=end, customer_id=customer_id)


@router.get("/plans")
async def plans(customer_id: int | None = Query(None, ge=1), skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50),
                user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.list_plans(db, user, customer_id=customer_id, skip=skip, limit=limit)


@router.post("/plans", status_code=201)
async def create(value: PlanInput, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.create_plan(db, user, **value.model_dump())


@router.get("/requests/{request_id}")
async def request_result(request_id: str, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.request_result(db, user, request_id)
