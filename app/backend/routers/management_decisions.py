from datetime import date, datetime, time, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_admin_user, get_finance_user
from models.customers import Customers
from models.management_decisions import (
    BILLING_CYCLES,
    BUSINESS_LINE_DEFINITIONS,
    COLLECTION_METHODS,
    ENGAGEMENT_STATUSES,
    BusinessLine,
    CustomerEngagement,
    ProductCatalog,
)
from schemas.auth import UserResponse
from services.management_decision_preview import build_classification_preview
from services.management_decision_workflow import (
    build_classification_review_queue,
    save_customer_classification_review,
    update_customer_engagement,
)


router = APIRouter(prefix="/api/v1/management-decisions", tags=["management-decisions"])


def _can_write(user: UserResponse) -> bool:
    return str(user.role or "").lower() in {"admin", "super_admin"}


class ProjectConfirmation(BaseModel):
    engagement_id: Optional[int] = Field(None, ge=1)
    business_line_code: str = Field(min_length=2, max_length=32)
    product_code: Optional[str] = Field(None, max_length=64)
    product_name: Optional[str] = Field(None, max_length=160)
    status: str = "active_paid"
    billing_cycle: Optional[str] = None
    collection_method: Optional[str] = None
    currency: str = Field("USD", min_length=3, max_length=3)
    owner_employee_id: Optional[int] = None
    sales_employee_id: Optional[int] = None
    paid_started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    stop_reason_code: Optional[str] = Field(None, max_length=48)
    stop_note: Optional[str] = Field(None, max_length=1000)
    source_payment_ids: list[int] = Field(default_factory=list)
    source_subscription_ids: list[int] = Field(default_factory=list)


class ClassificationReviewRequest(BaseModel):
    decision: Literal["confirmed", "needs_follow_up"]
    note: Optional[str] = Field(None, max_length=1000)
    projects: list[ProjectConfirmation] = Field(default_factory=list, max_length=12)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if value else None


class EngagementStatusRequest(BaseModel):
    status: str
    effective_date: date
    reason_code: Optional[str] = Field(None, max_length=48)
    note: Optional[str] = Field(None, max_length=1000)


def _business_line_payload(row: BusinessLine) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "is_recurring": bool(row.is_recurring),
        "is_active": bool(row.is_active),
    }


@router.get("/metadata")
async def get_management_decision_metadata(
    current_user: UserResponse = Depends(get_finance_user),
):
    return {
        "business_lines": list(BUSINESS_LINE_DEFINITIONS),
        "engagement_statuses": list(ENGAGEMENT_STATUSES),
        "billing_cycles": list(BILLING_CYCLES),
        "collection_methods": list(COLLECTION_METHODS),
        "write_enabled": _can_write(current_user),
        "phase": "review_and_project_management",
    }


@router.get("/business-lines")
async def list_business_lines(
    active_only: bool = Query(True),
    current_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(BusinessLine).order_by(BusinessLine.id.asc())
    if active_only:
        query = query.where(BusinessLine.is_active.is_(True))
    rows = (await db.execute(query)).scalars().all()
    return {"items": [_business_line_payload(row) for row in rows], "total": len(rows)}


@router.get("/engagements")
async def list_customer_engagements(
    business_line: Optional[str] = Query(None, max_length=32),
    status: Optional[str] = Query(None, max_length=24),
    customer_id: Optional[int] = Query(None, ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    filters = []
    if business_line:
        filters.append(BusinessLine.code == business_line)
    if status:
        filters.append(CustomerEngagement.status == status)
    if customer_id:
        filters.append(CustomerEngagement.customer_id == customer_id)

    base_query = (
        select(CustomerEngagement, BusinessLine, ProductCatalog, Customers)
        .join(BusinessLine, BusinessLine.id == CustomerEngagement.business_line_id)
        .join(ProductCatalog, ProductCatalog.id == CustomerEngagement.product_id)
        .join(Customers, Customers.id == CustomerEngagement.customer_id)
        .where(*filters)
    )
    total = (
        await db.execute(
            select(func.count())
            .select_from(CustomerEngagement)
            .join(BusinessLine, BusinessLine.id == CustomerEngagement.business_line_id)
            .where(*filters)
        )
    ).scalar_one()
    rows = (
        await db.execute(
            base_query
            .order_by(CustomerEngagement.updated_at.desc(), CustomerEngagement.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {
        "items": [
            {
                "id": engagement.id,
                "engagement_code": engagement.engagement_code,
                "customer_id": engagement.customer_id,
                "customer_name": customer.business_name,
                "customer_code": customer.customer_code,
                "business_line": {"code": line.code, "name": line.name},
                "product": {"code": product.code, "name": product.name},
                "status": engagement.status,
                "billing_cycle": engagement.billing_cycle,
                "collection_method": engagement.collection_method,
                "currency": engagement.currency,
                "owner_employee_id": engagement.owner_employee_id,
                "sales_employee_id": engagement.sales_employee_id,
                "trial_started_at": engagement.trial_started_at,
                "paid_started_at": engagement.paid_started_at,
                "stopped_at": engagement.stopped_at,
                "external_system": engagement.external_system,
                "external_store_id": engagement.external_store_id,
                "updated_at": engagement.updated_at,
            }
            for engagement, line, product, customer in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "write_enabled": _can_write(current_user),
    }


@router.get("/classification-preview")
async def get_classification_preview(
    customer_id: Optional[int] = Query(None, ge=1),
    start_date: date = Query(date(2026, 1, 1)),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    """Preview historical classifications without writing any database row."""
    return await build_classification_preview(
        db,
        customer_id=customer_id,
        start_date=start_date,
        page=page,
        page_size=page_size,
    )


@router.get("/classification-review")
async def get_classification_review(
    start_date: date = Query(date(2026, 1, 1)),
    current_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    payload = await build_classification_review_queue(db, start_date)
    payload["write_enabled"] = _can_write(current_user)
    return payload


@router.post("/classification-review/customers/{customer_id}")
async def save_classification_review(
    customer_id: int,
    request: ClassificationReviewRequest,
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await save_customer_classification_review(
            db,
            customer_id=customer_id,
            decision=request.decision,
            projects=[project.model_dump() for project in request.projects],
            note=request.note,
            actor_id=str(current_user.id),
            actor_name=current_user.name or current_user.email or "管理员",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/engagements/{engagement_id}/status")
async def update_engagement_status(
    engagement_id: int,
    request: EngagementStatusRequest,
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    effective_at = datetime.combine(request.effective_date, time.min, tzinfo=timezone.utc)
    try:
        return await update_customer_engagement(
            db,
            engagement_id=engagement_id,
            status=request.status,
            effective_at=effective_at,
            reason_code=request.reason_code,
            note=request.note,
            actor_id=str(current_user.id),
            actor_name=current_user.name or current_user.email or "管理员",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
