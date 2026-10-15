"""Sale registration is operational; verified collection remains owner-only."""
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user, get_finance_user, get_owner_user
from schemas.auth import UserResponse
from services import sales_deal_handoffs as service

router = APIRouter(prefix="/api/v1/sales-deal-handoffs", tags=["sales-deal-handoffs"])


class RegisterSale(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    idempotency_key: str = Field(min_length=16, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    plan_id: int = Field(ge=1)
    catalog_token: str = Field(pattern=r"^[a-f0-9]{64}$")
    selected_platforms: list[str] = Field(default_factory=list, max_length=12)
    service_start_date: date
    service_end_date: date | None = None
    collection_method: Literal["stripe_auto", "bank_transfer", "check", "zelle", "other"]
    operations_owner_employee_id: int = Field(ge=1)
    customer_goal: str = Field(min_length=3, max_length=4000)
    handoff_notes: str | None = Field(default=None, max_length=4000)
    special_commitments: str | None = Field(default=None, max_length=4000)
    confirmation_notes: str = Field(min_length=3, max_length=1000)
    existing_customer_id: int | None = Field(default=None, ge=1)


class VerifyReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    amount_received: Decimal = Field(ge=0, le=1000000, decimal_places=2, allow_inf_nan=False)
    payment_date: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    payment_method: Literal["stripe", "check", "zelle", "bank_transfer", "other"]
    transaction_reference: str = Field(min_length=1, max_length=240)


class AcknowledgeDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    note: str = Field(min_length=3, max_length=2000)


class UpdatePlanPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection_policy: Literal["manual", "stripe_auto"]


async def mutate(db, operation):
    try:
        result = await operation()
        await db.commit()
        return result
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, "成交交接正在更新，本次没有重复写入，请刷新后查看") from error
    except Exception:
        await db.rollback()
        raise


@router.get("/catalog")
async def get_catalog(user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from routers.sales_deal_controls import _ensure_sales_access
    _ensure_sales_access(user)
    return {**await service.catalog(db), "can_manage_catalog": service.is_customer_owner(user)}


@router.get("/queue")
async def get_queue(status: Literal["all", "pending_payment", "pending_operations", "pending_access", "completed"] = "all",
                    user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.queue(db, user, status)


@router.get("/plan-policies")
async def get_plan_policies(user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    return await service.policies(db, user)


@router.put("/plan-policies/{plan_id}")
async def put_plan_policy(plan_id: int, payload: UpdatePlanPolicy, user: UserResponse = Depends(get_owner_user), db: AsyncSession = Depends(get_db)):
    return await mutate(db, lambda: service.save_policy(db, plan_id, payload, user))


@router.get("/leads/{lead_id}")
async def get_lead(lead_id: int, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.lead_status(db, lead_id, user)


@router.post("/leads/{lead_id}")
async def register_sale(lead_id: int, payload: RegisterSale, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await mutate(db, lambda: service.register(db, lead_id, payload, user))


@router.get("/customers/{customer_id}")
async def get_customer_handoffs(customer_id: int, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.customer_handoffs(db, customer_id, user)


@router.get("/{handoff_id}")
async def get_handoff(handoff_id: int, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.get_handoff(db, handoff_id, user)


@router.post("/{handoff_id}/finance-confirmation")
async def verify_receipt(handoff_id: int, payload: VerifyReceipt, user: UserResponse = Depends(get_finance_user), db: AsyncSession = Depends(get_db)):
    return await mutate(db, lambda: service.finance_confirm(db, handoff_id, payload, user))


@router.post("/{handoff_id}/operations-acknowledgment")
async def acknowledge_delivery(handoff_id: int, payload: AcknowledgeDelivery, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await mutate(db, lambda: service.operations_ack(db, handoff_id, payload, user))
