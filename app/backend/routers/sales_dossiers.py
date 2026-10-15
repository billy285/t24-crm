"""Invitation-only extra access to prospect dossiers, never to the call queue."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from schemas.sales_dossiers import DossierAck, DossierInvite, DossierRevoke, DossierSummaryUpdate
from schemas.sales_enrichment import SalesEnrichmentUpdate
from services.sales_dossiers import (
    acknowledge_handoff, authorize_dossier, dossier_data, invite_sales,
    require_permission, revoke_sales, save_summary, shared_dossiers,
)
from services.sales_enrichment import apply_enrichment
from services.sales_workflow_locks import lock_sales_workflow

router = APIRouter(prefix="/api/v1/sales-lead-dossiers", tags=["sales-lead-dossiers"])


@router.get("")
async def list_shared_dossiers(shared_only: bool = True,
    current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # There is no inherited/global list on this dedicated discovery endpoint.
    return await shared_dossiers(db, current_user)


@router.get("/{lead_id}")
async def get_dossier(lead_id: int, current_user: UserResponse = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    lead, actor, permissions = await authorize_dossier(db, lead_id, current_user)
    return await dossier_data(db, lead, actor, permissions)


async def _mutate(db, user, lead_id, permission, operation, employee_ids=()):
    try:
        await lock_sales_workflow(db, lead_ids=[lead_id], employee_ids=employee_ids)
        # Re-read employee state, assignment and invitation after the workflow lock.
        lead, actor, permissions = await authorize_dossier(db, lead_id, user)
        require_permission(permissions, permission)
        await operation(lead, actor)
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, "档案正在被其他人更新，请刷新后重试") from error
    except Exception:
        await db.rollback()
        raise
    lead, actor, permissions = await authorize_dossier(db, lead_id, user)
    return await dossier_data(db, lead, actor, permissions)


@router.put("/{lead_id}/summary")
async def update_summary(lead_id: int, payload: DossierSummaryUpdate,
    current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    async def operation(lead, actor):
        await save_summary(db, lead, payload, actor)
    return await _mutate(db, current_user, lead_id, "can_edit_summary", operation)


@router.put("/{lead_id}/enrichment")
async def update_enrichment(lead_id: int, payload: SalesEnrichmentUpdate,
    current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    async def operation(lead, actor):
        await apply_enrichment(db, lead, payload.model_copy(update={"source": "manual"}), actor)
    return await _mutate(db, current_user, lead_id, "can_edit", operation)


@router.post("/{lead_id}/invites")
async def invite(lead_id: int, payload: DossierInvite,
    current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    async def operation(lead, actor):
        await invite_sales(db, lead, actor, payload)
    return await _mutate(db, current_user, lead_id, "can_invite", operation, [payload.employee_id])


@router.delete("/{lead_id}/invites/{employee_id}")
async def revoke(lead_id: int, employee_id: int, payload: DossierRevoke | None = None,
    expected_revision: int | None = Query(None, ge=0),
    current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if payload is not None:
        if expected_revision is not None and expected_revision != payload.expected_revision:
            raise HTTPException(422, "权限版本不一致")
        expected_revision = payload.expected_revision
    async def operation(lead, actor):
        await revoke_sales(db, lead, actor, employee_id, expected_revision)
    return await _mutate(db, current_user, lead_id, "can_invite", operation, [employee_id])


@router.post("/{lead_id}/handoffs/{handoff_id}/ack")
async def acknowledge(lead_id: int, handoff_id: int, payload: DossierAck,
    current_user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    async def operation(lead, actor):
        await acknowledge_handoff(db, lead, actor, handoff_id, payload.note)
    # Actual target/current assignment/status are validated by acknowledge_handoff.
    return await _mutate(db, current_user, lead_id, "can_edit_profile", operation)
