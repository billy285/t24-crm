"""Explicit owner Google connection and customer-scoped review/post operations."""
from typing import Literal
import logging
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from services import google_business as service
from services import google_business_provider as provider


class GoogleOAuthAccessLogFilter(logging.Filter):
    """Do not put one-use Google codes or state into Uvicorn access logs."""
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            path = record.args[2]
            if isinstance(path, str) and path.partition("?")[0] == "/api/v1/google-business/oauth/callback":
                record.args = (*record.args[:2], path.partition("?")[0], *record.args[3:])
        return True


if not any(isinstance(item, GoogleOAuthAccessLogFilter) for item in logging.getLogger("uvicorn.access").filters):
    logging.getLogger("uvicorn.access").addFilter(GoogleOAuthAccessLogFilter())


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def private(request):
            try:
                response = await handler(request)
                response.headers["Cache-Control"] = "private, no-store"
                response.headers["Referrer-Policy"] = "no-referrer"
                return response
            except RequestValidationError:
                raise HTTPException(422, "请求字段不完整或格式不正确", headers={"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"})
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"}
                raise
        return private


router = APIRouter(prefix="/api/v1/google-business", tags=["google-business"], route_class=PrivateRoute)


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Confirmed(StrictInput):
    confirmed: StrictBool


def confirm(value):
    if value.confirmed is not True: raise HTTPException(422, "请确认本次操作内容和门店")


class CreateBinding(Confirmed):
    request_id: str = Field(min_length=36, max_length=36)
    customer_id: int = Field(ge=1, strict=True)
    connection_id: int = Field(ge=1, strict=True)
    location_name: str = Field(min_length=10, max_length=200)


class UpdateGrant(StrictInput):
    expected_revision: int = Field(ge=1, strict=True)
    employee_id: int = Field(ge=1, strict=True)
    can_reply: StrictBool
    can_publish: StrictBool


class DisconnectBinding(Confirmed):
    expected_revision: int = Field(ge=1, strict=True)


class ReviewReply(Confirmed):
    request_id: str = Field(min_length=36, max_length=36)
    review_name: str = Field(min_length=10, max_length=255)
    expected_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    reply: str = Field(min_length=1, max_length=4096)


class PublishPost(Confirmed):
    request_id: str = Field(min_length=36, max_length=36)
    task_id: int = Field(ge=1, strict=True)
    expected_revision: int = Field(ge=1, strict=True)


@router.get("/status")
async def status(user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.status(db, user)


@router.get("/options")
async def options(user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.options(db, user)


@router.post("/oauth/start")
async def oauth_start(value: Confirmed, response: Response, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value)
    result, cookie = await service.oauth_start(db, user)
    response.set_cookie(service.COOKIE, cookie, max_age=600, path="/api/v1/google-business/oauth", secure=True, httponly=True, samesite="lax")
    return result


@router.get("/oauth/callback")
async def oauth_callback(request: Request, state: str | None = Query(None, max_length=200), code: str | None = Query(None, max_length=4096), db: AsyncSession = Depends(get_db)):
    outcome = "failed"
    try:
        await service.oauth_callback(db, state, request.cookies.get(service.COOKIE), code)
        outcome = "connected"
    except (HTTPException, provider.ProviderError):
        await db.rollback()
    response = RedirectResponse("/media-ops?google=" + outcome, status_code=303)
    response.delete_cookie(service.COOKIE, path="/api/v1/google-business/oauth", secure=True, httponly=True, samesite="lax")
    return response


@router.get("/connections/{connection_id}/locations")
async def locations(connection_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.locations(db, user, connection_id)


@router.post("/connections/{connection_id}/disconnect")
async def disconnect_connection(value: Confirmed, connection_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value)
    return await service.disconnect_connection(db, user, connection_id)


@router.post("/bindings", status_code=201)
async def bind(value: CreateBinding, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value)
    return await service.bind(db, user, **value.model_dump(exclude={"confirmed"}))


@router.get("/bindings/{binding_id}/grants")
async def grants(binding_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.grants(db, user, binding_id)


@router.put("/bindings/{binding_id}/grants")
async def update_grant(value: UpdateGrant, binding_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.set_grant(db, user, binding_id, **value.model_dump())


@router.post("/bindings/{binding_id}/disconnect")
async def disconnect_binding(value: DisconnectBinding, binding_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value)
    return await service.disconnect_binding(db, user, binding_id, value.expected_revision)


@router.get("/bindings/{binding_id}/reviews")
async def reviews(binding_id: int = Path(ge=1), page_token: str | None = Query(None, max_length=4096), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.reviews(db, user, binding_id, page_token)


@router.post("/bindings/{binding_id}/review-replies")
async def reply(value: ReviewReply, binding_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value)
    return await service.reply(db, user, binding_id, **value.model_dump(exclude={"confirmed"}))


@router.get("/bindings/{binding_id}/ready-tasks")
async def ready_tasks(binding_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.ready_tasks(db, user, binding_id)


@router.post("/bindings/{binding_id}/posts")
async def publish(value: PublishPost, binding_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value)
    return await service.publish(db, user, binding_id, **value.model_dump(exclude={"confirmed"}))


@router.get("/bindings/{binding_id}/actions")
async def actions(binding_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.actions(db, user, binding_id)


@router.get("/actions/{action_id}")
async def action(action_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.action(db, user, action_id)


@router.get("/requests/{request_id}")
async def request_action(request_id: str = Path(min_length=36, max_length=36), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.request_action(db, user, request_id)


@router.post("/actions/{action_id}/reconcile")
async def reconcile(value: Confirmed, action_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value)
    return await service.reconcile(db, user, action_id)
