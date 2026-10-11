"""A separately stored personal workspace; provider operations remain read-only."""
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.private_workspace import PrivateOwner, private_access_allowed, require_private_owner
from models.private_workspace import PrivateItem
from schemas.private_workspace import (
    ActionStatus, MailBucket, PrivateItemCreate, PrivateItemPatch, PrivateItemResponse, PrivateMailFeedbackCreate, PrivatePreferencesPatch, SourceId,
    PrivateMailTranslationBatch, PrivateMailTranslationRequest,
)
from services.private_workspace import (
    complete_oauth, connect_source, disconnect_source, get_private_db, item_response, list_items,
    preferences_for, set_mail_feedback, stored_preferences_for, sync_source, update_private_preferences, workspace_overview,
)


def private_no_cache(response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


router = APIRouter(prefix="/api/v1/private-workspace", tags=["private-workspace"],
                   dependencies=[Depends(private_no_cache)])


@router.get("/access")
async def access(allowed: bool = Depends(private_access_allowed)):
    return {"allowed": allowed}


@router.get("")
async def overview(
    owner: PrivateOwner = Depends(require_private_owner),
    private_db: AsyncSession = Depends(get_private_db),
):
    return await workspace_overview(private_db, owner.employee_id)


@router.get("/items")
async def items(
    source_id: SourceId | None = None,
    kind: str | None = Query(default=None, max_length=48),
    action_status: ActionStatus | None = None,
    mail_bucket: MailBucket | None = None,
    limit: int = Query(default=100, ge=1, le=100),
    owner: PrivateOwner = Depends(require_private_owner),
    private_db: AsyncSession = Depends(get_private_db),
):
    return await list_items(private_db, owner.employee_id, source_id=source_id, kind=kind,
                            action_status=action_status, limit=limit, mail_bucket=mail_bucket)


@router.post("/items", status_code=201)
async def create_item(
    payload: PrivateItemCreate,
    owner: PrivateOwner = Depends(require_private_owner),
    private_db: AsyncSession = Depends(get_private_db),
):
    row = PrivateItem(owner_id=owner.employee_id, external_id=str(uuid4()), status="manual", evidence={},
                      action_status="open", **payload.model_dump())
    private_db.add(row)
    await private_db.commit()
    return {"item": PrivateItemResponse(**item_response(row, await stored_preferences_for(private_db, owner.employee_id))).model_dump()}


async def _owned_item(private_db, owner_id: str, item_id: str):
    row = (await private_db.execute(select(PrivateItem).where(
        PrivateItem.id == item_id, PrivateItem.owner_id == owner_id,
    ))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="未找到此私人事项")
    return row


@router.patch("/items/{item_id}")
async def update_item(
    item_id: str,
    payload: PrivateItemPatch,
    owner: PrivateOwner = Depends(require_private_owner),
    private_db: AsyncSession = Depends(get_private_db),
):
    row = await _owned_item(private_db, owner.employee_id, item_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("action_status") == "snoozed" and not changes.get("snoozed_until", row.snoozed_until):
        raise HTTPException(status_code=422, detail="稍后处理需要设置提醒时间")
    if "title" in changes:
        row.local_title = changes["title"]
    if "summary" in changes:
        row.local_summary = changes["summary"]
    if "action_status" in changes:
        row.action_status = changes["action_status"]
        if row.action_status != "snoozed":
            row.snoozed_until = None
    if "snoozed_until" in changes and row.action_status == "snoozed":
        row.snoozed_until = changes["snoozed_until"]
    await private_db.commit()
    return {"item": PrivateItemResponse(**item_response(row, await stored_preferences_for(private_db, owner.employee_id))).model_dump()}


@router.delete("/items/{item_id}")
async def archive_item(
    item_id: str,
    owner: PrivateOwner = Depends(require_private_owner),
    private_db: AsyncSession = Depends(get_private_db),
):
    row = await _owned_item(private_db, owner.employee_id, item_id)
    if row.source_id != "manual":
        raise HTTPException(status_code=409, detail="来源记录不可删除，可标记为已处理")
    row.action_status = "archived"
    row.snoozed_until = None
    await private_db.commit()
    return {"item": PrivateItemResponse(**item_response(row)).model_dump()}


@router.post("/items/{item_id}/mail-feedback")
async def mail_feedback(
    item_id: str,
    payload: PrivateMailFeedbackCreate,
    owner: PrivateOwner = Depends(require_private_owner),
    private_db: AsyncSession = Depends(get_private_db),
):
    return await set_mail_feedback(private_db, owner.employee_id, item_id, payload.feedback,
                                   apply_to_sender=payload.apply_to_sender)


@router.post("/mail-translations/batch")
async def mail_translation_batch(
    payload: PrivateMailTranslationBatch,
    owner: PrivateOwner = Depends(require_private_owner),
    private_db: AsyncSession = Depends(get_private_db),
):
    from services.private_mail_translation_service import translate_batch
    return await translate_batch(private_db, owner.employee_id, payload.item_ids)


@router.post("/items/{item_id}/mail-translation")
async def mail_translation(
    item_id: str,
    payload: PrivateMailTranslationRequest,
    owner: PrivateOwner = Depends(require_private_owner),
    private_db: AsyncSession = Depends(get_private_db),
):
    from services.private_mail_translation_service import translate_item
    return await translate_item(private_db, owner.employee_id, item_id, mode=payload.mode)


@router.get("/preferences")
async def preferences(
    owner: PrivateOwner = Depends(require_private_owner),
    private_db: AsyncSession = Depends(get_private_db),
):
    return await preferences_for(private_db, owner.employee_id)


@router.patch("/preferences")
async def update_preferences(
    payload: PrivatePreferencesPatch,
    owner: PrivateOwner = Depends(require_private_owner),
    private_db: AsyncSession = Depends(get_private_db),
):
    return await update_private_preferences(private_db, owner.employee_id, payload.model_dump(exclude_unset=True))


@router.post("/sources/{source_id}/connect")
async def connect(
    source_id: SourceId,
    owner: PrivateOwner = Depends(require_private_owner),
    private_db: AsyncSession = Depends(get_private_db),
):
    return await connect_source(private_db, owner.employee_id, source_id)


@router.post("/sources/{source_id}/disconnect")
async def disconnect(
    source_id: SourceId,
    owner: PrivateOwner = Depends(require_private_owner),
    private_db: AsyncSession = Depends(get_private_db),
):
    return await disconnect_source(private_db, owner.employee_id, source_id)


@router.post("/sources/{source_id}/sync")
async def synchronize(
    source_id: SourceId,
    owner: PrivateOwner = Depends(require_private_owner),
    private_db: AsyncSession = Depends(get_private_db),
):
    return await sync_source(private_db, owner.employee_id, source_id)


@router.get("/oauth/{source_id}/callback", include_in_schema=False)
async def oauth_callback(
    source_id: SourceId,
    state: str | None = Query(default=None, max_length=200),
    code: str | None = Query(default=None, max_length=4096),
    error: str | None = Query(default=None, max_length=200),
    business_db: AsyncSession = Depends(get_db),
    private_db: AsyncSession = Depends(get_private_db),
):
    outcome = "expired"
    if state and len(state) >= 20:
        try:
            connected = await complete_oauth(private_db, business_db, source_id, state, code, error)
            outcome = "connected" if connected else "incomplete"
        except HTTPException as exc:
            if exc.status_code not in {400, 403}:
                raise
            outcome = "expired" if exc.status_code == 400 else "incomplete"
    return RedirectResponse(
        url=f"/private-workspace?view={source_id}&source={source_id}&connection={outcome}",
        status_code=303, headers={"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer"},
    )
