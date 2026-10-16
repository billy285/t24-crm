"""Protected sales payment links and an independently signed Stripe callback."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user, get_owner_user
from routers.sales_deal_handoffs import mutate
from schemas.auth import UserResponse
from services import sales_deal_payments as service

router = APIRouter(prefix="/api/v1/sales-deal-payments", tags=["sales-deal-payments"])


@router.get("/status")
async def status(user: UserResponse = Depends(get_owner_user)):
    return {"configured": bool(service.webhook_secret()), "mode": "observations_only",
        "auto_accounting": False, "duplicate_scope": service.DUPLICATE_SCOPE}


@router.post("/webhook")
async def webhook(request: Request, db: AsyncSession = Depends(get_db)):
    # Stream with a hard bound; never load an unbounded body or log it/secrets.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > service.MAX_BODY_BYTES:
            raise HTTPException(413, "回调内容超出限制")
    return await mutate(db, lambda: service.receive_event(db, bytes(body), request.headers.get("stripe-signature")))


@router.get("/{handoff_id}/request")
async def get_payment_request(handoff_id: int, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.get_request(db, handoff_id, user)


@router.post("/{handoff_id}/request")
async def create_payment_request(handoff_id: int, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await mutate(db, lambda: service.create_request(db, handoff_id, user))


@router.get("/{handoff_id}/observations")
async def get_observations(handoff_id: int, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    return await service.observations(db, handoff_id, user)
