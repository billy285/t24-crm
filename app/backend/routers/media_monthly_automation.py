"""Owner-only automatic draft preparation; no publish or retry endpoint."""
from typing import Literal
from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from schemas.media_monthly_automation import AutomationPolicyInput
from routers.media_workspace import PrivateRoute
from services import media_monthly_automation as service

router = APIRouter(prefix="/api/v1/media-monthly", tags=["media-monthly-automation"], route_class=PrivateRoute)
Platform = Literal["google_business", "facebook", "instagram"]


@router.get("/customers/{customer_id}/automation")
async def get_policy(customer_id: int = Path(ge=1), platform: Platform = Query("google_business"), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.get_policy(db, user, customer_id, platform=platform)


@router.put("/customers/{customer_id}/automation")
async def put_policy(body: AutomationPolicyInput, customer_id: int = Path(ge=1), platform: Platform = Query("google_business"), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.save_policy(db, user, customer_id, platform=platform, **body.model_dump())


@router.get("/automation/requests/{request_id}")
async def request_result(request_id: str, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.request_result(db, user, request_id)


@router.get("/automation/overview")
async def overview(user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.overview(db, user)
