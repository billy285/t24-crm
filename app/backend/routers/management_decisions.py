from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_finance_user
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


router = APIRouter(prefix="/api/v1/management-decisions", tags=["management-decisions"])


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
        "write_enabled": False,
        "phase": "foundation_read_only",
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
        "write_enabled": False,
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
