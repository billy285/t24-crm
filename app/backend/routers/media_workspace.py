"""Read-only merchant-first projection; every mutation stays in its native API."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from services import media_workspace as service

HEADERS = {"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def private(request):
            try:
                response = await handler(request)
                response.headers.update(HEADERS)
                return response
            except RequestValidationError:
                raise HTTPException(422, "请求字段不完整或格式不正确", headers=HEADERS) from None
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), **HEADERS}
                raise
        return private


router = APIRouter(prefix="/api/v1/media-workspace", tags=["media-workspace"], route_class=PrivateRoute)
Platform = Literal["google_business", "facebook", "instagram", "tiktok", "xiaohongshu", "other"]
Status = Literal["all", "attention", "review", "unassigned", "no_schedule"]


@router.get("/merchants")
async def merchants(q: str | None = Query(None, max_length=100), platform: Platform | None = None,
                    customer_id: int | None = Query(None, ge=1),
                    start: str | None = Query(None, max_length=80), end: str | None = Query(None, max_length=80),
                    status: Status = "all", operator_id: int | None = Query(None, ge=1),
                    cursor: str | None = Query(None, max_length=6000), limit: int = Query(50, ge=1, le=100),
                    user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.merchants(db, user, q=q, platform=platform, customer_id=customer_id, start=start, end=end,
                                   status=status, operator_id=operator_id, cursor=cursor, limit=limit)


@router.get("/workspace")
async def workspace(start: str = Query(max_length=80), end: str = Query(max_length=80),
                    customer_id: int | None = Query(None, ge=1), platform: Platform | None = None,
                    view: Literal["overview", "calendar", "review", "inbox"] = "overview",
                    status: Status = "all", operator_id: int | None = Query(None, ge=1),
                    cursor: str | None = Query(None, max_length=6000), limit: int = Query(50, ge=1, le=100),
                    user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.workspace(db, user, start=start, end=end, customer_id=customer_id, platform=platform,
                                   view=view, status=status, operator_id=operator_id, cursor=cursor, limit=limit)
