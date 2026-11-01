"""Isolated owner pilot: private preparation and explicitly confirmed dispatch."""
import asyncio
from collections import deque
import logging
import time
from typing import Literal
import weakref

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from services import meta_operations as service
from services import meta_operations_provider as provider

HEADERS = {"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}
_public_times = deque(maxlen=120)
_public_slots = weakref.WeakKeyDictionary()


class MetaOperationsAccessLogFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) >= 3 and isinstance(record.args[2], str):
            value = record.args[2]
            if value.partition("?")[0] == "/api/v1/meta-operations/oauth/callback":
                record.args = (*record.args[:2], value.partition("?")[0], *record.args[3:])
            elif value.startswith("/api/v1/meta-operations/delivery/"):
                record.args = (*record.args[:2], "/api/v1/meta-operations/delivery/[image].jpg", *record.args[3:])
        return True


if not any(isinstance(item, MetaOperationsAccessLogFilter) for item in logging.getLogger("uvicorn.access").filters):
    logging.getLogger("uvicorn.access").addFilter(MetaOperationsAccessLogFilter())


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def private(request):
            try:
                response = await handler(request); response.headers.update(HEADERS); return response
            except RequestValidationError:
                raise HTTPException(422, "请求字段不完整或格式不正确", headers=HEADERS) from None
            except provider.OpsProviderError as exc:
                raise HTTPException(409, service.MESSAGES.get(exc.code, service.MESSAGES["provider_unavailable"]), headers=HEADERS) from None
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), **HEADERS}; raise
        return private


router = APIRouter(prefix="/api/v1/meta-operations", tags=["meta-operations"], route_class=PrivateRoute)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Confirmed(Input):
    confirmed: StrictBool


def confirm(value):
    if value.confirmed is not True: raise HTTPException(422, "请核对本次具体内容、账号和操作后确认")


class Revision(Input):
    expected_revision: int = Field(ge=1)


class ConfirmedRevision(Confirmed):
    expected_revision: int = Field(ge=1)


class CreateDraft(Input):
    request_id: str = Field(min_length=36, max_length=36)
    kind: Literal["post", "reply"]
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=5000)
    media_id: str | None = Field(None, pattern=r"^[a-f0-9]{32}$")
    target_ref: str | None = Field(None, pattern=r"^[a-f0-9]{32}$")
    expected_target_version: str | None = Field(None, pattern=r"^[a-f0-9]{64}$")


class UpdateDraft(Revision):
    title: str | None = Field(None, min_length=1, max_length=200)
    content: str | None = Field(None, max_length=5000)
    media_id: str | None = Field(None, pattern=r"^[a-f0-9]{32}$")


class Approve(ConfirmedRevision):
    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class Publish(Approve):
    request_id: str = Field(min_length=36, max_length=36)


class CreateSchedule(Publish):
    planned_at: str = Field(min_length=20, max_length=80)
    timezone: str = Field(min_length=1, max_length=80)
    execute_confirmed: StrictBool = False


class OAuthStart(Confirmed):
    request_id: str = Field(min_length=36, max_length=36)
    connection_id: int = Field(ge=1)


@router.get("/status")
async def status(user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.status(db, user)


@router.get("/bindings/{binding_id}/workspace")
async def workspace(binding_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.workspace(db, user, binding_id)


@router.post("/bindings/{binding_id}/disconnect")
async def disconnect_binding(value: ConfirmedRevision, binding_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value)
    return await service.disconnect_binding(db, user, binding_id, value.expected_revision)


@router.post("/bindings/{binding_id}/drafts", status_code=201)
async def create_draft(value: CreateDraft, binding_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.create_draft(db, user, binding_id, **value.model_dump())


@router.patch("/drafts/{draft_id}")
async def update_draft(value: UpdateDraft, draft_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    fields = value.model_dump(exclude_unset=True, exclude={"expected_revision"})
    return await service.update_draft(db, user, draft_id, expected_revision=value.expected_revision, fields=fields)


@router.post("/drafts/{draft_id}/preview")
async def preview(value: Revision, draft_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.preview(db, user, draft_id, value.expected_revision)


@router.post("/drafts/{draft_id}/approve")
async def approve(value: Approve, draft_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value)
    return await service.approve(db, user, draft_id, **value.model_dump(exclude={"confirmed"}))


@router.post("/drafts/{draft_id}/publish")
async def publish(value: Publish, draft_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value)
    return await service.publish(db, user, draft_id, **value.model_dump(exclude={"confirmed"}))


@router.post("/bindings/{binding_id}/media", status_code=201)
async def upload_media(request: Request, binding_id: int = Path(ge=1), request_id: str = Form(..., min_length=36, max_length=36),
                       rights_confirmed: bool = Form(...), file: UploadFile = File(...),
                       user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        form = await request.form()
        if set(form) != {"request_id", "rights_confirmed", "file"} or any(len(form.getlist(key)) != 1 for key in form):
            raise HTTPException(422, "图片请求字段不正确")
        if file.content_type != "image/jpeg": raise HTTPException(422, "请先导出为 JPEG 图片")
        body = await file.read(service.images.MAX_BYTES + 1)
        if len(body) > service.images.MAX_BYTES: raise HTTPException(413, "图片不能超过8MB")
        return await service.upload_media(db, user, binding_id, request_id=request_id, rights_confirmed=rights_confirmed, body=body)
    finally: await file.close()


@router.get("/media/{media_id}/preview")
async def media_preview(media_id: str = Path(pattern=r"^[a-f0-9]{32}$"), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return Response(await service.preview_media(db, user, media_id), media_type="image/jpeg", headers=HEADERS)


@router.get("/bindings/{binding_id}/posts")
async def posts(binding_id: int = Path(ge=1), cursor: str | None = Query(None, max_length=6000), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.read_posts(db, user, binding_id, cursor)


@router.get("/bindings/{binding_id}/comments")
async def comments(binding_id: int = Path(ge=1), post_ref: str = Query(..., pattern=r"^[a-f0-9]{32}$"), cursor: str | None = Query(None, max_length=6000),
                   user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.read_comments(db, user, binding_id, post_ref=post_ref, cursor=cursor)


@router.get("/actions/{action_id}")
async def action(action_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.action(db, user, action_id)


@router.post("/actions/{action_id}/continue")
async def continue_action(value: ConfirmedRevision, action_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value)
    return await service.continue_action(db, user, action_id, expected_revision=value.expected_revision)


@router.post("/drafts/{draft_id}/schedules", status_code=201)
async def prepare_schedule(value: CreateSchedule, draft_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value)
    return await service.prepare_schedule(db, user, draft_id, **value.model_dump(exclude={"confirmed"}))


@router.post("/schedules/{schedule_id}/cancel")
async def cancel_schedule(value: ConfirmedRevision, schedule_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value)
    return await service.cancel_schedule(db, user, schedule_id, value.expected_revision)


@router.post("/schedules/{schedule_id}/activate")
async def activate_schedule(value: ConfirmedRevision, schedule_id: int = Path(ge=1), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value)
    return await service.activate_schedule(db, user, schedule_id, value.expected_revision)


@router.get("/requests/{request_id}")
async def request_result(request_id: str = Path(min_length=36, max_length=36), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.request_result(db, user, request_id)


def _cookie(response, value):
    response.set_cookie(service.COOKIE, value, max_age=600, path="/api/v1/meta-operations/oauth", secure=True, httponly=True, samesite="lax")


@router.post("/oauth/start")
async def oauth_start(value: OAuthStart, response: Response, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    confirm(value); result, cookie = await service.oauth_start(db, user, **value.model_dump(exclude={"confirmed"}))
    _cookie(response, cookie); return result


@router.get("/oauth/requests/{request_id}")
async def oauth_request(response: Response, request_id: str = Path(min_length=36, max_length=36), user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result, cookie = await service.oauth_cookie_request(db, user, request_id)
    _cookie(response, cookie); return result


@router.get("/oauth/callback")
async def oauth_callback(request: Request, state: str | None = Query(None, max_length=200), code: str | None = Query(None, max_length=4096), db: AsyncSession = Depends(get_db)):
    outcome = "failed"
    try:
        await service.oauth_callback(db, state, request.cookies.get(service.COOKIE), code); outcome = "connected"
    except (HTTPException, provider.OpsProviderError): await db.rollback()
    response = RedirectResponse("/media-ops?meta_ops=" + outcome, status_code=303)
    response.delete_cookie(service.COOKIE, path="/api/v1/meta-operations/oauth", secure=True, httponly=True, samesite="lax")
    return response


class LeasedResponse(Response):
    def __init__(self, body, slot):
        super().__init__(body, media_type="image/jpeg", headers=HEADERS); self.slot = slot
    async def __call__(self, scope, receive, send):
        try: await super().__call__(scope, receive, send)
        finally: self.slot.release()


@router.api_route("/delivery/{token}.jpg", methods=["GET", "HEAD"], include_in_schema=False)
async def public_delivery(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    at = time.monotonic()
    while _public_times and _public_times[0] < at - 60: _public_times.popleft()
    if len(_public_times) >= 120 or sum(value > at - 2 for value in _public_times) >= 8:
        return Response(status_code=429, headers={**HEADERS, "Retry-After": "2"})
    _public_times.append(at)
    loop = asyncio.get_running_loop(); slot = _public_slots.setdefault(loop, asyncio.Semaphore(4))
    await slot.acquire()
    try: body = await service.public_delivery(db, token)
    except HTTPException:
        slot.release(); return Response(status_code=404, headers=HEADERS)
    except Exception:
        slot.release(); return Response(status_code=503, headers=HEADERS)
    except BaseException:
        slot.release(); raise
    if request.method == "HEAD":
        slot.release(); return Response(media_type="image/jpeg", headers={**HEADERS, "Content-Length": str(len(body))})
    return LeasedResponse(body, slot)
