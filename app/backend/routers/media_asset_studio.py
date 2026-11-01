"""Authenticated private asset studio. No public preview or publishing route."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from schemas.media_asset_studio import ProfileInput, JobInput, RetryInput, AdoptInput
from services import media_asset_studio as service
from routers.media_publication_images import ImageRoute, HEADERS

router = APIRouter(prefix="/api/v1/media-asset-studio", tags=["media-asset-studio"], route_class=ImageRoute)


@router.get("/customers/{customer_id}/studio")
async def studio(customer_id: int, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.studio(db, user, customer_id)


@router.put("/customers/{customer_id}/profile")
async def profile(customer_id: int, value: ProfileInput, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.save_profile(db, user, customer_id, value)


@router.post("/customers/{customer_id}/jobs", status_code=202)
async def create(customer_id: int, value: JobInput, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.create_job(db, user, customer_id, value)


@router.get("/jobs/{job_id}")
async def job(job_id: str, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.get_job(db, user, job_id)


@router.get("/requests/{request_id}")
async def request_result(request_id: str, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.request_result(db, user, request_id)


@router.post("/jobs/{job_id}/retry")
async def retry(job_id: str, value: RetryInput, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.retry(db, user, job_id, value)


@router.post("/jobs/{job_id}/adopt")
async def adopt(job_id: str, value: AdoptInput, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.adopt(db, user, job_id, value)


@router.get("/jobs/{job_id}/preview")
async def preview(job_id: str, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    body, mime = await service.preview(db, user, job_id)
    return Response(body, media_type=mime, headers=HEADERS)


@router.get("/jobs/{job_id}/download")
async def download(job_id: str, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    body, mime = await service.preview(db, user, job_id)
    suffix = "png" if mime == "image/png" else "mp4"
    return Response(body, media_type=mime, headers={**HEADERS, "Content-Disposition":"attachment; filename=t24-private-"+job_id+"."+suffix})
