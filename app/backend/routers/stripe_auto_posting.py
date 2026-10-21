"""Owner-only, explicit opt-in controls; no provider writes."""
from typing import Literal
from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from dependencies.auth import get_owner_user
from routers.sales_deal_handoffs import mutate
from schemas.auth import UserResponse
from schemas.stripe_auto_posting import TrialBindings, UpdateAutomaticPolicy
from services import stripe_auto_posting as service

router = APIRouter(prefix='/api/v1/stripe-history-reconciliation/auto-posting', tags=['stripe-auto-posting'])


def private(response):
    response.headers['Cache-Control'] = 'private, no-store'


@router.get('')
async def overview(response: Response, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await service.overview(db, user)


@router.post('/trials')
async def trials(payload: TrialBindings, response: Response, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await mutate(db, lambda: service.trial_bindings(db, payload, user))


@router.patch('/bindings/{binding_id}')
async def update(binding_id: int, payload: UpdateAutomaticPolicy, response: Response, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await mutate(db, lambda: service.update_policy(db, binding_id, payload, user))


@router.get('/jobs')
async def jobs(response: Response, status: Literal['all', 'queued', 'retry', 'manual_required', 'auto_posted', 'manual_completed'] = 'all',
               user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    private(response)
    return await service.jobs(db, user, status)
