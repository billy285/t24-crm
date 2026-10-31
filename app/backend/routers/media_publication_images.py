"""Authenticated private versions; the one public route serves leased copies only."""
import asyncio
from collections import deque
import logging
import time
from typing import Literal
import weakref

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from services import media_publication_images as service

HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}
_public_times = deque(maxlen=120)
_public_slots = weakref.WeakKeyDictionary()


class ImageAccessLogFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) >= 3 and isinstance(record.args[2], str):
            if record.args[2].startswith("/api/v1/media-publication-images/delivery/"):
                record.args = (*record.args[:2], "/api/v1/media-publication-images/delivery/[image].png", *record.args[3:])
        return True


if not any(isinstance(item, ImageAccessLogFilter) for item in logging.getLogger("uvicorn.access").filters):
    logging.getLogger("uvicorn.access").addFilter(ImageAccessLogFilter())


class ImageRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def private(request: Request):
            try:
                response = await handler(request)
                response.headers.update(HEADERS)
                return response
            except RequestValidationError:
                raise HTTPException(422, "请求字段不完整或格式不正确", headers=HEADERS)
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), **HEADERS}; raise
        return private


class LeasedResponse(Response):
    """Bound retained bodies to four through complete ASGI send/cancellation."""
    def __init__(self, body, slot):
        super().__init__(body, media_type="image/png", headers=HEADERS)
        self.slot = slot

    async def __call__(self, scope, receive, send):
        try: await super().__call__(scope, receive, send)
        finally: self.slot.release()


router = APIRouter(prefix="/api/v1/media-publication-images", tags=["media-publication-images"], route_class=ImageRoute)


class DeliveryPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool
    public_delivery_confirmed: bool


@router.get("/delivery-policy")
async def delivery_policy(response: Response, customer_id: int | None = Query(None, ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    response.headers.update(HEADERS)
    return await service.delivery_policy(db, user, customer_id)


@router.post("/delivery-policy")
async def set_delivery_policy(value: DeliveryPolicyInput, response: Response, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    response.headers.update(HEADERS)
    return await service.set_delivery_policy(db, user, **value.model_dump())


@router.get("")
async def list_images(response: Response, customer_id: int = Query(..., ge=1), material_id: int = Query(..., ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    response.headers.update(HEADERS)
    return await service.list_images(db, user, customer_id=customer_id, material_id=material_id)


@router.post("/prepare", status_code=201)
async def prepare(response: Response, customer_id: int = Form(..., ge=1), material_id: int = Form(..., ge=1),
                  source_sha256: str = Form(..., min_length=64, max_length=64),
                  rights_basis: Literal["owned", "client_provided", "licensed"] = Form(...),
                  rights_confirmed: bool = Form(...), request_id: str = Form(..., min_length=36, max_length=36),
                  file: UploadFile = File(...), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    response.headers.update(HEADERS)
    try:
        body = await file.read(service.MAX_PNG_BYTES + 1)
        if len(body) > service.MAX_PNG_BYTES: raise HTTPException(413, "PNG 发布副本不能超过8MB，请缩小后重新准备")
        return await service.prepare(db, user, customer_id=customer_id, material_id=material_id,
            source_sha256=source_sha256, rights_basis=rights_basis, rights_confirmed=rights_confirmed, request_id=request_id, body=body)
    finally:
        await file.close()


@router.get("/requests/{request_id}")
async def request_image(request_id: str, response: Response, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    response.headers.update(HEADERS)
    return await service.request_image(db, user, request_id)


@router.api_route("/delivery/{token}.png", methods=["GET", "HEAD"], include_in_schema=False)
async def delivery(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    at = time.monotonic()
    while _public_times and _public_times[0] < at - 60: _public_times.popleft()
    if len(_public_times) >= 120 or sum(value > at - 2 for value in _public_times) >= 8:
        return Response(status_code=429, headers={**HEADERS, "Retry-After": "2"})
    _public_times.append(at)
    loop = asyncio.get_running_loop()
    slot = _public_slots.get(loop)
    if slot is None:
        slot = asyncio.Semaphore(4); _public_slots[loop] = slot
    await slot.acquire()
    try:
        body = await service.public_delivery(db, token)
    except HTTPException:
        slot.release()
        return Response(status_code=404, headers=HEADERS)
    except Exception:
        # Database exceptions can contain bound capability-token parameters.
        # This public read must never pass those into the global error logger.
        slot.release()
        return Response(status_code=503, headers=HEADERS)
    except BaseException:
        slot.release(); raise
    if request.method == "HEAD":
        slot.release()
        return Response(media_type="image/png", headers={**HEADERS, "Content-Length": str(len(body))})
    return LeasedResponse(body, slot)


@router.get("/{image_id}/preview")
async def preview(image_id: str, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return Response(await service.preview(db, user, image_id), media_type="image/png", headers=HEADERS)


@router.post("/{image_id}/revoke")
async def revoke(image_id: str, response: Response, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    response.headers.update(HEADERS)
    return await service.revoke(db, user, image_id)
