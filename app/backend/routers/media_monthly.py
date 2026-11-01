"""Owner-only monthly draft preparation. No public operation endpoints."""
from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from schemas.media_monthly import ProfileInput, Generate, EditItem, Adopt, Archive
from routers.media_workspace import PrivateRoute
from services import media_monthly as service

router = APIRouter(prefix="/api/v1/media-monthly", tags=["media-monthly"], route_class=PrivateRoute)


@router.get("/customers/{customer_id}/setup")
async def setup(customer_id: int = Path(ge=1), month: str = Query(service.MONTH, pattern=r"^[0-9]{4}-(?:0[1-9]|1[0-2])$"), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.setup(db, user, customer_id, month=month)


@router.put("/customers/{customer_id}/profile")
async def profile(body: ProfileInput, customer_id: int = Path(ge=1), month: str = Query(service.MONTH, pattern=r"^[0-9]{4}-(?:0[1-9]|1[0-2])$"), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.save_profile(db, user, customer_id, month=month, **body.model_dump())


@router.post("/customers/{customer_id}/runs", status_code=201)
async def generate(body: Generate, customer_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.generate(db, user, customer_id, **body.model_dump())


@router.get("/customers/{customer_id}/runs")
async def runs(customer_id: int = Path(ge=1), month: str | None = Query(None, pattern=r"^[0-9]{4}-(?:0[1-9]|1[0-2])$"), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.list_runs(db, user, customer_id, month=month)


@router.get("/runs/{run_id}")
async def run(run_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.get_run(db, user, run_id)


@router.get("/requests/{request_id}")
async def request(request_id: str, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.request_result(db, user, request_id)


@router.patch("/runs/{run_id}/items/{item_id}")
async def edit(body: EditItem, run_id: int = Path(ge=1), item_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.edit_item(db, user, run_id, item_id, **body.model_dump())


@router.post("/runs/{run_id}/adopt")
async def adopt(body: Adopt, run_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.adopt(db, user, run_id, **body.model_dump())


@router.post("/runs/{run_id}/archive")
async def archive(body: Archive, run_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.archive(db, user, run_id, **body.model_dump())
