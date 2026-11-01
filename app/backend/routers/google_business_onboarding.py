from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from schemas.google_business_onboarding import Discover, Preview, Confirm, Cancel
from routers.google_business import PrivateRoute
from services import google_business_onboarding as service

router = APIRouter(prefix="/api/v1/google-business/onboarding", tags=["google-business-onboarding"], route_class=PrivateRoute)


@router.get("/context")
async def context(customer_id: int | None = Query(None, ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.get_context(db, user, customer_id)


@router.post("/catalogs", status_code=202)
async def discover(body: Discover, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.discover(db, user, **body.model_dump())


@router.get("/catalogs/{catalog_id}")
async def catalog(catalog_id: str = Path(pattern=r"^[a-f0-9]{32}$"), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.get_catalog(db, user, catalog_id)


@router.post("/previews", status_code=201)
async def preview(body: Preview, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.preview(db, user, **body.model_dump())


@router.get("/batches/{batch_id}")
async def batch(batch_id: str = Path(pattern=r"^[a-f0-9]{32}$"), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.get_batch(db, user, batch_id)


@router.post("/batches/{batch_id}/confirm", status_code=202)
async def confirm(body: Confirm, batch_id: str = Path(pattern=r"^[a-f0-9]{32}$"), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.confirm(db, user, batch_id, **body.model_dump())


@router.post("/batches/{batch_id}/cancel")
async def cancel(body: Cancel, batch_id: str = Path(pattern=r"^[a-f0-9]{32}$"), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.cancel(db, user, batch_id, **body.model_dump())


@router.get("/requests/{request_id}")
async def request_result(request_id: str = Path(min_length=36, max_length=36), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.request_result(db, user, request_id)
