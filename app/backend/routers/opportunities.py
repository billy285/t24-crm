import json
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from models.customers import Customers
from models.deals import Deals
from models.follow_ups import Follow_ups
from models.management_decisions import BusinessLine, CustomerEngagement, ProductCatalog, ProductPlan
from models.opportunities import Opportunities
from models.tasks import Tasks
from schemas.auth import UserResponse
from services.customers import CustomersService


router = APIRouter(prefix="/api/v1/opportunities", tags=["opportunities"])

STAGES = ("initial", "needs_confirmed", "quoted", "negotiating", "payment_pending")
STATUSES = ("open", "on_hold", "won", "lost")
STAGE_PROBABILITIES = {
    "initial": 10,
    "needs_confirmed": 25,
    "quoted": 45,
    "negotiating": 70,
    "payment_pending": 90,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_list(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [str(item) for item in value] if isinstance(value, list) else []


def _json_dict(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


class OpportunityInput(BaseModel):
    customer_id: int = Field(ge=1)
    business_line_id: int = Field(ge=1)
    product_id: Optional[int] = Field(None, ge=1)
    product_plan_id: Optional[int] = Field(None, ge=1)
    title: str = Field(min_length=2, max_length=200)
    stage: Literal["initial", "needs_confirmed", "quoted", "negotiating", "payment_pending"] = "initial"
    status: Literal["open", "on_hold", "won", "lost"] = "open"
    estimated_amount: Optional[float] = Field(None, ge=0)
    currency: str = Field("USD", min_length=3, max_length=3)
    probability: Optional[int] = Field(None, ge=0, le=100)
    owner_employee_id: Optional[int] = None
    owner_name: Optional[str] = Field(None, max_length=160)
    source: Optional[str] = Field(None, max_length=32)
    selected_platforms: list[str] = Field(default_factory=list, max_length=50)
    service_scope: dict = Field(default_factory=dict)
    expected_close_date: Optional[datetime] = None
    next_follow_up_at: Optional[datetime] = None
    pause_until: Optional[datetime] = None
    lost_reason: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=3000)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("selected_platforms")
    @classmethod
    def normalize_platforms(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @model_validator(mode="after")
    def validate_status_fields(self):
        if self.status == "open" and not self.next_follow_up_at:
            raise ValueError("跟进中的商机必须填写下次跟进时间")
        if self.status == "on_hold" and not self.pause_until:
            raise ValueError("暂缓商机必须填写恢复跟进日期")
        if self.status == "lost" and not (self.lost_reason or "").strip():
            raise ValueError("关闭未成交商机必须填写原因")
        return self


class OpportunityPatch(BaseModel):
    business_line_id: Optional[int] = Field(None, ge=1)
    product_id: Optional[int] = Field(None, ge=1)
    product_plan_id: Optional[int] = Field(None, ge=1)
    title: Optional[str] = Field(None, min_length=2, max_length=200)
    stage: Optional[Literal["initial", "needs_confirmed", "quoted", "negotiating", "payment_pending"]] = None
    status: Optional[Literal["open", "on_hold", "won", "lost"]] = None
    estimated_amount: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    probability: Optional[int] = Field(None, ge=0, le=100)
    owner_employee_id: Optional[int] = None
    owner_name: Optional[str] = Field(None, max_length=160)
    source: Optional[str] = Field(None, max_length=32)
    selected_platforms: Optional[list[str]] = Field(None, max_length=50)
    service_scope: Optional[dict] = None
    expected_close_date: Optional[datetime] = None
    next_follow_up_at: Optional[datetime] = None
    pause_until: Optional[datetime] = None
    lost_reason: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=3000)


class FollowUpInput(BaseModel):
    content: str = Field(min_length=2, max_length=3000)
    contact_method: Optional[str] = Field(None, max_length=40)
    stage: Optional[Literal["initial", "needs_confirmed", "quoted", "negotiating", "payment_pending"]] = None
    probability: Optional[int] = Field(None, ge=0, le=100)
    next_follow_up_at: datetime
    customer_needs: Optional[str] = Field(None, max_length=1000)
    customer_pain_points: Optional[str] = Field(None, max_length=1000)


async def _load_context(db: AsyncSession, opportunity: Opportunities):
    line = await db.get(BusinessLine, opportunity.business_line_id)
    product = await db.get(ProductCatalog, opportunity.product_id) if opportunity.product_id else None
    plan = await db.get(ProductPlan, opportunity.product_plan_id) if opportunity.product_plan_id else None
    return line, product, plan


async def _validate_catalog(
    db: AsyncSession,
    business_line_id: int,
    product_id: Optional[int],
    product_plan_id: Optional[int],
    selected_platforms: list[str],
    *,
    require_complete: bool = False,
):
    line = await db.get(BusinessLine, business_line_id)
    if not line or not line.is_active:
        raise HTTPException(status_code=400, detail="请选择有效业务线")
    product = await db.get(ProductCatalog, product_id) if product_id else None
    if product and product.business_line_id != business_line_id:
        raise HTTPException(status_code=400, detail="产品不属于所选业务线")
    plan = await db.get(ProductPlan, product_plan_id) if product_plan_id else None
    if plan and (not product or plan.product_id != product.id):
        raise HTTPException(status_code=400, detail="套餐不属于所选产品")
    if require_complete and (not product or not plan):
        raise HTTPException(status_code=400, detail="成交前必须确认产品和套餐")
    if plan and plan.scope_type == "platforms":
        if len(selected_platforms) > int(plan.platform_limit or 0):
            raise HTTPException(status_code=400, detail=f"该套餐最多可选择 {plan.platform_limit} 个运营平台")
        if require_complete and len(selected_platforms) != int(plan.platform_limit or 0):
            raise HTTPException(status_code=400, detail=f"成交前需确认 {plan.platform_limit} 个实际运营平台")
    return line, product, plan


async def _get_scoped_opportunity(
    db: AsyncSession, opportunity_id: int, current_user: UserResponse
) -> Opportunities:
    opportunity = await db.get(Opportunities, opportunity_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="商机不存在")
    customer = await CustomersService(db).get_by_id(opportunity.customer_id, scope_user=current_user)
    if not customer:
        raise HTTPException(status_code=404, detail="商机不存在或无权访问")
    return opportunity


async def _sync_task(db: AsyncSession, opportunity: Opportunities) -> None:
    task = (await db.execute(select(Tasks).where(Tasks.opportunity_id == opportunity.id))).scalar_one_or_none()
    terminal = opportunity.status in {"won", "lost"}
    due_date = opportunity.next_follow_up_at if opportunity.status == "open" else opportunity.pause_until
    title = f"跟进商机：{opportunity.customer_name} · {opportunity.title}"
    if not task:
        task = Tasks(opportunity_id=opportunity.id, created_at=utcnow())
        db.add(task)
    task.title = title
    task.customer_id = opportunity.customer_id
    task.customer_name = opportunity.customer_name
    task.assignee_id = opportunity.owner_employee_id
    task.assignee_name = opportunity.owner_name
    task.task_type = "sales_follow_up"
    task.priority = "high" if due_date and due_date <= utcnow() else "medium"
    task.status = "completed" if terminal else "pending"
    task.due_date = due_date
    task.notes = f"商机编号：{opportunity.opportunity_code}；阶段：{opportunity.stage}"
    task.source_type = "opportunity"
    task.updated_at = utcnow()
    if terminal:
        task.completion_result = "商机已成交" if opportunity.status == "won" else f"未成交：{opportunity.lost_reason or '-'}"
        task.completed_at = utcnow()
    else:
        task.completion_result = None
        task.completed_at = None


async def _payload(db: AsyncSession, opportunity: Opportunities) -> dict:
    line, product, plan = await _load_context(db, opportunity)
    task = (await db.execute(select(Tasks).where(Tasks.opportunity_id == opportunity.id))).scalar_one_or_none()
    return {
        "id": opportunity.id,
        "opportunity_code": opportunity.opportunity_code,
        "customer_id": opportunity.customer_id,
        "customer_name": opportunity.customer_name,
        "title": opportunity.title,
        "stage": opportunity.stage,
        "status": opportunity.status,
        "estimated_amount": opportunity.estimated_amount,
        "currency": opportunity.currency,
        "probability": opportunity.probability,
        "weighted_amount": round(float(opportunity.estimated_amount or 0) * opportunity.probability / 100, 2),
        "owner_employee_id": opportunity.owner_employee_id,
        "owner_name": opportunity.owner_name,
        "source": opportunity.source,
        "selected_platforms": _json_list(opportunity.selected_platforms),
        "service_scope": _json_dict(opportunity.service_scope_json),
        "expected_close_date": opportunity.expected_close_date,
        "next_follow_up_at": opportunity.next_follow_up_at,
        "last_follow_up_at": opportunity.last_follow_up_at,
        "pause_until": opportunity.pause_until,
        "lost_reason": opportunity.lost_reason,
        "notes": opportunity.notes,
        "business_line": {"id": line.id, "code": line.code, "name": line.name} if line else None,
        "product": {"id": product.id, "code": product.code, "name": product.name} if product else None,
        "plan": {
            "id": plan.id, "code": plan.code, "name": plan.name, "platform_limit": plan.platform_limit,
            "scope_type": plan.scope_type, "pricing_status": plan.pricing_status,
        } if plan else None,
        "task_id": task.id if task else None,
        "converted_deal_id": opportunity.converted_deal_id,
        "converted_engagement_id": opportunity.converted_engagement_id,
        "converted_subscription_id": opportunity.converted_subscription_id,
        "won_at": opportunity.won_at,
        "lost_at": opportunity.lost_at,
        "created_at": opportunity.created_at,
        "updated_at": opportunity.updated_at,
    }


@router.get("/metadata")
async def opportunity_metadata(_current_user: UserResponse = Depends(get_current_user)):
    return {"stages": list(STAGES), "statuses": list(STATUSES), "default_probabilities": STAGE_PROBABILITIES}


@router.get("")
async def list_opportunities(
    customer_id: Optional[int] = Query(None, ge=1),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if customer_id and not await CustomersService(db).get_by_id(customer_id, scope_user=current_user):
        raise HTTPException(status_code=404, detail="客户不存在或无权访问")
    query = select(Opportunities)
    filters = []
    if customer_id:
        filters.append(Opportunities.customer_id == customer_id)
    if status:
        if status not in STATUSES:
            raise HTTPException(status_code=400, detail="商机状态无效")
        filters.append(Opportunities.status == status)
    scope = CustomersService(db)._scope_filter(current_user)
    if scope is not None:
        query = query.join(Customers, Customers.id == Opportunities.customer_id).where(scope)
    query = query.where(*filters)
    count_query = select(func.count()).select_from(query.order_by(None).subquery())
    total = (await db.execute(count_query)).scalar_one()
    rows = (await db.execute(
        query.order_by(Opportunities.next_follow_up_at.asc().nulls_last(), Opportunities.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return {
        "items": [await _payload(db, row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", status_code=201)
async def create_opportunity(
    data: OpportunityInput,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    customer = await CustomersService(db).get_by_id(data.customer_id, scope_user=current_user)
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在或无权访问")
    await _validate_catalog(
        db, data.business_line_id, data.product_id, data.product_plan_id, data.selected_platforms,
        require_complete=data.status == "won",
    )
    payload = data.model_dump(exclude={"selected_platforms", "service_scope"})
    probability = payload.pop("probability")
    opportunity = Opportunities(
        **payload,
        customer_name=customer.business_name,
        opportunity_code=f"OPP-{utcnow():%Y%m%d}-{uuid4().hex[:8].upper()}",
        probability=probability if probability is not None else STAGE_PROBABILITIES[data.stage],
        selected_platforms=json.dumps(data.selected_platforms, ensure_ascii=False),
        service_scope_json=json.dumps(data.service_scope, ensure_ascii=False),
        won_at=utcnow() if data.status == "won" else None,
        lost_at=utcnow() if data.status == "lost" else None,
    )
    db.add(opportunity)
    await db.flush()
    await _sync_task(db, opportunity)
    await db.commit()
    await db.refresh(opportunity)
    return await _payload(db, opportunity)


@router.put("/{opportunity_id}")
async def update_opportunity(
    opportunity_id: int,
    data: OpportunityPatch,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    opportunity = await _get_scoped_opportunity(db, opportunity_id, current_user)
    patch = data.model_dump(exclude_unset=True)
    selected = patch.pop("selected_platforms", _json_list(opportunity.selected_platforms))
    scope = patch.pop("service_scope", _json_dict(opportunity.service_scope_json))
    business_line_id = patch.get("business_line_id", opportunity.business_line_id)
    product_id = patch.get("product_id", opportunity.product_id)
    product_plan_id = patch.get("product_plan_id", opportunity.product_plan_id)
    next_status = patch.get("status", opportunity.status)
    next_follow = patch.get("next_follow_up_at", opportunity.next_follow_up_at)
    pause_until = patch.get("pause_until", opportunity.pause_until)
    lost_reason = patch.get("lost_reason", opportunity.lost_reason)
    if next_status == "open" and not next_follow:
        raise HTTPException(status_code=400, detail="跟进中的商机必须填写下次跟进时间")
    if next_status == "on_hold" and not pause_until:
        raise HTTPException(status_code=400, detail="暂缓商机必须填写恢复跟进日期")
    if next_status == "lost" and not (lost_reason or "").strip():
        raise HTTPException(status_code=400, detail="关闭未成交商机必须填写原因")
    await _validate_catalog(
        db, business_line_id, product_id, product_plan_id, selected, require_complete=next_status == "won"
    )
    for key, value in patch.items():
        setattr(opportunity, key, value.upper() if key == "currency" and value else value)
    opportunity.selected_platforms = json.dumps(selected, ensure_ascii=False)
    opportunity.service_scope_json = json.dumps(scope, ensure_ascii=False)
    if "stage" in patch and "probability" not in patch:
        opportunity.probability = STAGE_PROBABILITIES[opportunity.stage]
    if next_status == "won" and not opportunity.won_at:
        opportunity.won_at = utcnow()
    if next_status == "lost" and not opportunity.lost_at:
        opportunity.lost_at = utcnow()
    await _sync_task(db, opportunity)
    await db.commit()
    await db.refresh(opportunity)
    return await _payload(db, opportunity)


@router.post("/{opportunity_id}/follow-ups", status_code=201)
async def create_opportunity_follow_up(
    opportunity_id: int,
    data: FollowUpInput,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    opportunity = await _get_scoped_opportunity(db, opportunity_id, current_user)
    if opportunity.status != "open":
        raise HTTPException(status_code=400, detail="只有跟进中的商机可以新增跟进记录")
    if data.stage:
        opportunity.stage = data.stage
    opportunity.probability = data.probability if data.probability is not None else STAGE_PROBABILITIES[opportunity.stage]
    opportunity.last_follow_up_at = utcnow()
    opportunity.next_follow_up_at = data.next_follow_up_at
    follow_up = Follow_ups(
        customer_id=opportunity.customer_id,
        opportunity_id=opportunity.id,
        employee_id=int(current_user.id) if str(current_user.id).isdigit() else opportunity.owner_employee_id,
        employee_name=current_user.name or opportunity.owner_name,
        contact_method=data.contact_method,
        content=data.content,
        customer_needs=data.customer_needs,
        customer_pain_points=data.customer_pain_points,
        has_quoted=opportunity.stage in {"quoted", "negotiating", "payment_pending"},
        quote_plan=None,
        close_probability=opportunity.probability,
        stage=opportunity.stage,
        next_follow_date=data.next_follow_up_at,
        created_at=utcnow(),
    )
    db.add(follow_up)
    await _sync_task(db, opportunity)
    await db.commit()
    await db.refresh(follow_up)
    await db.refresh(opportunity)
    return {"follow_up_id": follow_up.id, "opportunity": await _payload(db, opportunity)}


@router.post("/{opportunity_id}/convert")
async def convert_opportunity(
    opportunity_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Convert once, without fabricating payment or starting paid lifecycle."""
    opportunity = await _get_scoped_opportunity(db, opportunity_id, current_user)
    if opportunity.converted_deal_id:
        return {"idempotent": True, "opportunity": await _payload(db, opportunity)}
    line, product, plan = await _validate_catalog(
        db,
        opportunity.business_line_id,
        opportunity.product_id,
        opportunity.product_plan_id,
        _json_list(opportunity.selected_platforms),
        require_complete=True,
    )
    now = utcnow()
    deal = Deals(
        opportunity_id=opportunity.id,
        customer_id=opportunity.customer_id,
        customer_name=opportunity.customer_name,
        sales_employee_id=opportunity.owner_employee_id,
        sales_name=opportunity.owner_name,
        product_type=line.code,
        package_name=plan.name if plan else product.name,
        package_platforms=opportunity.selected_platforms,
        billing_cycle=plan.default_billing_cycle if plan else None,
        deal_amount=float(opportunity.estimated_amount or 0),
        is_paid=False,
        needs_group=False,
        is_handed_over=False,
        is_transferred_ops=False,
        notes="由商机转为待首笔收款；首笔有效收款后才开始客户生命周期。",
        deal_date=now,
        created_at=now,
    )
    db.add(deal)
    await db.flush()
    engagement = CustomerEngagement(
        customer_id=opportunity.customer_id,
        business_line_id=line.id,
        product_id=product.id,
        product_plan_id=plan.id if plan else None,
        engagement_code=f"ENG-{now:%Y%m%d}-{uuid4().hex[:8].upper()}",
        package_name=plan.name if plan else product.name,
        status="pending_setup",
        owner_employee_id=opportunity.owner_employee_id,
        sales_employee_id=opportunity.owner_employee_id,
        billing_cycle=plan.default_billing_cycle if plan else None,
        currency=opportunity.currency,
        selected_platforms=opportunity.selected_platforms,
        service_scope_json=opportunity.service_scope_json,
    )
    db.add(engagement)
    await db.flush()
    opportunity.status = "won"
    opportunity.won_at = opportunity.won_at or now
    opportunity.converted_deal_id = deal.id
    opportunity.converted_engagement_id = engagement.id
    await _sync_task(db, opportunity)
    await db.commit()
    await db.refresh(opportunity)
    return {
        "idempotent": False,
        "deal_id": deal.id,
        "engagement_id": engagement.id,
        "subscription_id": None,
        "lifecycle_started": False,
        "message": "已转为待首笔收款，尚未生成收入或开始付费生命周期",
        "opportunity": await _payload(db, opportunity),
    }
