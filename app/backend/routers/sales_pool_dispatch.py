from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from schemas.auth import UserResponse
from services.sales_pool_dispatch import apply_dispatch_plan, build_dispatch_plan

router = APIRouter(prefix='/api/v1/sales-pool-dispatch', tags=['sales-pool-dispatch'])


class DispatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    merchant_ids: list[int] = Field(min_length=1, max_length=200)
    sales_ids: list[int] = Field(min_length=1, max_length=50)

    @field_validator('merchant_ids', 'sales_ids')
    @classmethod
    def unique_positive_ids(cls, values):
        if any(value <= 0 for value in values) or len(values) != len(set(values)):
            raise ValueError('请选择不重复的有效ID')
        return values


class DispatchConfirmRequest(DispatchRequest):
    plan_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


@router.post('/preview')
async def preview_dispatch(payload: DispatchRequest, current_user: UserResponse = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    return await build_dispatch_plan(db, current_user, payload.merchant_ids, payload.sales_ids)


@router.post('/confirm')
async def confirm_dispatch(payload: DispatchConfirmRequest, current_user: UserResponse = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    return await apply_dispatch_plan(db, current_user, payload.merchant_ids, payload.sales_ids, payload.plan_sha256)
