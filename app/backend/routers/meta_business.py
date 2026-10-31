"""Meta connection and client binding only; no publish or comment endpoints."""
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
from services import meta_business as service
from services import meta_business_provider as provider


class MetaOAuthAccessLogFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            path = record.args[2]
            if isinstance(path, str) and path.partition("?")[0] == "/api/v1/meta-business/oauth/callback":
                record.args = (*record.args[:2], path.partition("?")[0], *record.args[3:])
        return True


if not any(isinstance(item, MetaOAuthAccessLogFilter) for item in logging.getLogger("uvicorn.access").filters):
    logging.getLogger("uvicorn.access").addFilter(MetaOAuthAccessLogFilter())


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def private(request):
            headers = {"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"}
            try:
                response = await handler(request)
                response.headers.update(headers)
                return response
            except RequestValidationError:
                raise HTTPException(422, "请求字段不完整或格式不正确", headers=headers) from None
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), **headers}
                raise
        return private


router = APIRouter(prefix="/api/v1/meta-business", tags=["meta-business"], route_class=PrivateRoute)


class Confirmed(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    confirmed: StrictBool


def confirm(value):
    if value.confirmed is not True: raise HTTPException(422, "请确认本次 Meta 授权或绑定范围")


class OAuthStart(Confirmed):
    request_id: str = Field(min_length=36, max_length=36)
    reconnect_connection_id: int | None = Field(None, ge=1, strict=True)


class CreateBinding(Confirmed):
    request_id: str = Field(min_length=36, max_length=36)
    customer_id: int = Field(ge=1, strict=True)
    connection_id: int = Field(ge=1, strict=True)
    asset_ref: str = Field(pattern=r"^[a-f0-9]{32}$")


class DisconnectBinding(Confirmed):
    expected_revision: int = Field(ge=1, strict=True)


def _cookie(response, value):
    response.set_cookie(service.COOKIE, value, max_age=600, path="/api/v1/meta-business/oauth", secure=True, httponly=True, samesite="lax")


@router.get("/status")
async def status(user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.status(db, user)


@router.get("/options")
async def options(user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.options(db, user)


@router.post("/oauth/start")
async def oauth_start(value: OAuthStart, response: Response, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value)
    result, cookie = await service.oauth_start(db, user, request_id=value.request_id, reconnect_connection_id=value.reconnect_connection_id)
    _cookie(response, cookie)
    return result


@router.get("/oauth/requests/{request_id}")
async def oauth_request(response: Response, request_id: str = Path(min_length=36, max_length=36), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result, cookie = await service.oauth_request(db, user, request_id)
    _cookie(response, cookie)
    return result


@router.get("/oauth/callback")
async def oauth_callback(request: Request, state: str | None = Query(None, max_length=200), code: str | None = Query(None, max_length=4096), db: AsyncSession = Depends(get_db)):
    outcome = "failed"
    try:
        await service.oauth_callback(db, state, request.cookies.get(service.COOKIE), code)
        outcome = "connected"
    except (HTTPException, provider.ProviderError):
        await db.rollback()
    response = RedirectResponse("/media-ops?meta=" + outcome, status_code=303)
    response.delete_cookie(service.COOKIE, path="/api/v1/meta-business/oauth", secure=True, httponly=True, samesite="lax")
    return response


@router.get("/connections/{connection_id}/assets")
async def assets(connection_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.assets(db, user, connection_id)


@router.post("/connections/{connection_id}/disconnect")
async def disconnect_connection(value: DisconnectBinding, connection_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value)
    return await service.disconnect_connection(db, user, connection_id, value.expected_revision)


@router.post("/bindings", status_code=201)
async def bind(value: CreateBinding, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value)
    return await service.bind(db, user, **value.model_dump(exclude={"confirmed"}))


@router.post("/bindings/{binding_id}/disconnect")
async def disconnect_binding(value: DisconnectBinding, binding_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value)
    return await service.disconnect_binding(db, user, binding_id, value.expected_revision)


@router.get("/requests/{request_id}")
async def request_result(request_id: str = Path(min_length=36, max_length=36), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.request_result(db, user, request_id)
