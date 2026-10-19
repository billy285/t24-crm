"""Owner-only historical binding, pending receipts and explicit confirmation."""
from typing import Literal
from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from dependencies.auth import get_owner_user
from routers.sales_deal_handoffs import mutate
from schemas.auth import UserResponse
from schemas.stripe_history_reconciliation import (ActivateBulk, BindingConfirm, BindingPreview, BindingStatus, ConfirmInvoice, SyncInvoices, VerifyPilot)
from services import stripe_history_reconciliation as service

router = APIRouter(prefix="/api/v1/stripe-history-reconciliation", tags=["stripe-history-reconciliation"])


def private(response):
    response.headers["Cache-Control"] = "private, no-store"


@router.get("/reminders")
async def reminders(response: Response, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    from services.stripe_history_daily_scan import reminders as owner_reminders
    private(response)
    return await owner_reminders(db, user)


@router.get("/overview")
async def overview(response: Response, background_tasks: BackgroundTasks, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    result = await service.overview(db, user)
    background_tasks.add_task(service.process_pending_history)
    return result


@router.get("/crm-services")
async def services(response: Response, search: str = Query("", max_length=100), user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await service.crm_services(db, user, search)


@router.get("/stripe-subscriptions")
async def subscriptions(response: Response, customer_id: str | None = Query(None, pattern=r"^cus_[A-Za-z0-9_]{1,220}$"),
                        starting_after: str | None = Query(None, pattern=r"^sub_[A-Za-z0-9_]{1,220}$"),
                        user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await service.stripe_subscriptions(db, user, customer_id, starting_after)


@router.post("/bindings/preview")
async def preview(payload: BindingPreview, response: Response, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await mutate(db, lambda: service.preview_binding(db, payload, user))


@router.post("/bindings")
async def bind(payload: BindingConfirm, response: Response, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await mutate(db, lambda: service.confirm_binding(db, payload, user))


@router.patch("/bindings/{binding_id}")
async def update(binding_id: int, payload: BindingStatus, response: Response, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await mutate(db, lambda: service.update_binding(db, binding_id, payload, user))


@router.post("/bindings/{binding_id}/sync")
async def sync(binding_id: int, payload: SyncInvoices, response: Response, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await mutate(db, lambda: service.sync_invoices(db, binding_id, payload, user))


@router.post("/bindings/{binding_id}/validate-pilot")
async def validate_pilot(binding_id: int, payload: VerifyPilot, response: Response, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await mutate(db, lambda: service.validate_pilot(db, binding_id, payload, user))


@router.post("/pilot/bulk-activation")
async def bulk(payload: ActivateBulk, response: Response, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await mutate(db, lambda: service.activate_bulk(db, payload, user))


@router.get("/invoice-reviews")
async def reviews(response: Response, status: Literal["all", "pending_review", "needs_refresh", "exception", "confirmed", "linked_existing"] = "all",
                  user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await service.reviews(db, user, status)


@router.get("/invoice-reviews/{review_id}")
async def detail(review_id: int, response: Response, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await service.detail(db, review_id, user)


@router.post("/invoice-reviews/{review_id}/refresh")
async def refresh(review_id: int, response: Response, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await mutate(db, lambda: service.refresh_review(db, review_id, user))


@router.post("/invoice-reviews/{review_id}/confirm")
async def confirm(review_id: int, payload: ConfirmInvoice, response: Response, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await mutate(db, lambda: service.confirm_invoice(db, review_id, payload, user))
