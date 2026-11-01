from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from schemas.media_monthly_workflow import Prepare, Review, Schedule, Cancel
from routers.media_workspace import PrivateRoute
from services import media_monthly_workflow as service

router = APIRouter(prefix="/api/v1/media-monthly", tags=["media-monthly-workflow"], route_class=PrivateRoute)


@router.get("/runs/{run_id}/workflow")
async def workflow(run_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.get_workflow(db, user, run_id)


@router.post("/runs/{run_id}/prepare")
async def prepare(body: Prepare, run_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.prepare(db, user, run_id, **body.model_dump())


@router.post("/runs/{run_id}/review")
async def review(body: Review, run_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.review(db, user, run_id, **body.model_dump())


@router.post("/runs/{run_id}/schedule")
async def schedule(body: Schedule, run_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.schedule(db, user, run_id, **body.model_dump())


@router.post("/runs/{run_id}/cancel")
async def cancel(body: Cancel, run_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.cancel(db, user, run_id, **body.model_dump())


@router.get("/workflow-requests/{request_id}")
async def request_result(request_id: str, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.request_result(db, user, request_id)


@router.get("/customers/{customer_id}/workflow-alerts")
async def alerts(customer_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.alerts(db, user, customer_id)
