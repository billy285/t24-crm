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
from models.finance_exchange_rates import MonthlyExchangeRate
from schemas.auth import UserResponse
from services.management_decision_preview import build_classification_preview
from services.management_decision_workflow import (
    build_classification_review_queue,
    save_customer_classification_review,
    update_customer_engagement,
)
from services.automation_monitor import automation_overview, create_task_for_issue, run_automation_scan
from services.owner_cockpit import build_owner_cockpit
from services.business_intelligence import build_growth_dashboard


router = APIRouter(prefix="/api/v1/management-decisions", tags=["management-decisions"])


def _can_write(user: UserResponse) -> bool:
    return str(user.role or "").lower() in {"admin", "super_admin"}


class ProjectConfirmation(BaseModel):
    engagement_id: Optional[int] = Field(None, ge=1)
    business_line_code: str = Field(min_length=2, max_length=32)
    product_code: Optional[str] = Field(None, max_length=64)
    product_name: Optional[str] = Field(None, max_length=160)
    package_name: Optional[str] = Field(None, max_length=160)
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


class AutomationIssueTaskBatchRequest(BaseModel):
    issue_ids: list[int] = Field(min_length=1, max_length=200)


class MonthlyExchangeRateRequest(BaseModel):
    average_rate: float = Field(gt=0.1, lt=20)
    source: str = Field(min_length=2, max_length=160)
    notes: Optional[str] = Field(None, max_length=1000)
    status: Literal["draft", "locked"] = "locked"

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        return value.strip()


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
                "package_name": engagement.package_name or product.name,
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


@router.get("/automation/overview")
async def get_automation_overview(
    current_user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    """Return persisted daily scan issues and their linked task status."""
    payload = await automation_overview(db)
    payload["write_enabled"] = _can_write(current_user)
    return payload


@router.get("/owner-cockpit")
async def get_owner_cockpit(
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Owner-facing operating summary built from the same finance and workflow sources."""
    return await build_owner_cockpit(db)


@router.get("/growth-dashboard")
async def get_growth_dashboard(
    start_date: date = Query(date(2026, 1, 1)),
    end_date: date = Query(default_factory=date.today),
    project_capacity_target: int = Query(12, ge=1, le=100),
    capacity_warning_ratio: float = Query(0.85, ge=0.5, le=1),
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Owner-only project economics, health and capacity decision data."""
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")
    return await build_growth_dashboard(
        db,
        start_date=start_date,
        end_date=end_date,
        project_capacity_target=project_capacity_target,
        capacity_warning_ratio=capacity_warning_ratio,
    )


@router.put("/exchange-rates/{year_month}")
async def save_monthly_exchange_rate(
    year_month: str,
    payload: MonthlyExchangeRateRequest,
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        datetime.strptime(year_month, "%Y-%m")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="月份格式必须为 YYYY-MM") from exc
    row = (await db.execute(select(MonthlyExchangeRate).where(
        MonthlyExchangeRate.year_month == year_month,
        MonthlyExchangeRate.base_currency == "USD",
        MonthlyExchangeRate.quote_currency == "CNY",
    ))).scalar_one_or_none()
    if not row:
        row = MonthlyExchangeRate(
            year_month=year_month, base_currency="USD", quote_currency="CNY",
            average_rate=payload.average_rate, source=payload.source,
            status=payload.status, notes=payload.notes,
            recorded_by=current_user.name or current_user.email,
        )
        db.add(row)
    else:
        row.average_rate = payload.average_rate
        row.source = payload.source
        row.status = payload.status
        row.notes = payload.notes
        row.recorded_by = current_user.name or current_user.email
        row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return {
        "id": row.id, "year_month": row.year_month, "base_currency": row.base_currency,
        "quote_currency": row.quote_currency, "average_rate": row.average_rate,
        "source": row.source, "status": row.status, "notes": row.notes,
        "recorded_by": row.recorded_by, "updated_at": row.updated_at,
    }


@router.post("/automation/scan")
async def trigger_automation_scan(
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Run the same idempotent scanner used by the daily background schedule."""
    scan = await run_automation_scan(db, trigger="manual")
    overview = await automation_overview(db)
    return {"scan": scan, "overview": overview}


@router.post("/automation/issues/{issue_id}/task", status_code=201)
async def create_automation_issue_task(
    issue_id: int,
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create one tracked task for a warning that did not require an automatic task."""
    try:
        task = await create_task_for_issue(db, issue_id)
        return {
            "id": task.id,
            "status": task.status,
            "customer_id": task.customer_id,
            "assignee_name": task.assignee_name,
            "due_date": task.due_date,
            "automation_issue_id": task.automation_issue_id,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/automation/issues/tasks-batch")
async def create_automation_issue_tasks_batch(
    request: AutomationIssueTaskBatchRequest,
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create idempotent tracked tasks for the currently selected issues."""
    created: list[dict] = []
    errors: list[dict] = []
    for issue_id in dict.fromkeys(request.issue_ids):
        try:
            task = await create_task_for_issue(db, issue_id)
            created.append({"issue_id": issue_id, "task_id": task.id, "status": task.status})
        except ValueError as exc:
            errors.append({"issue_id": issue_id, "detail": str(exc)})
    return {"processed": len(created), "errors": errors}


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
