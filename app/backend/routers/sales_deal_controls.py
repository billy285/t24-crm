import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from models.sales_deal_controls import SalesHandoffChecklists, SalesQuoteRequests
from models.employees import Employees
from models.management_decisions import BusinessLine, ProductCatalog, ProductPlan
from models.sales_leads import SalesLeads
from schemas.auth import UserResponse


router = APIRouter(prefix="/api/v1/sales-deal-controls", tags=["sales-deal-controls"])

ADMIN_ROLES = {"admin", "super_admin"}
LEAD_ROLES = ADMIN_ROLES | {"sales", "sales_manager"}
MANAGER_ROLES = ADMIN_ROLES | {"sales_manager"}


def _role(user: UserResponse) -> str:
    return str(user.role or "").strip().lower()


def _employee_id(user: UserResponse) -> int:
    try:
        return int(user.id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=403, detail="当前账号未关联有效员工")


def _ensure_sales_access(user: UserResponse) -> None:
    if _role(user) not in LEAD_ROLES:
        raise HTTPException(status_code=403, detail="无权访问报价与成交交接")


def _ensure_manager(user: UserResponse) -> None:
    _ensure_sales_access(user)
    if _role(user) not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="只有销售主管或系统管理员可以审批报价和确认交接")


async def _get_scoped_lead(db: AsyncSession, lead_id: int, user: UserResponse) -> SalesLeads:
    role = _role(user)
    query = select(SalesLeads).where(SalesLeads.id == lead_id)
    if role == "sales":
        query = query.where(SalesLeads.assigned_sales_id == _employee_id(user))
    elif role == "sales_manager":
        report_ids = (await db.scalars(select(Employees.id).where(
            Employees.role == "sales",
            Employees.supervisor == (user.name or ""),
            Employees.status.in_(["active", "probation"]),
        ))).all()
        visible_ids = list({_employee_id(user), *(int(item) for item in report_ids)})
        query = query.where(or_(SalesLeads.team_manager_id == _employee_id(user), SalesLeads.assigned_sales_id.in_(visible_ids)))
    lead = (await db.scalars(query)).one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="销售线索不存在或不在您的权限范围内")
    return lead


def _list_json(raw: Optional[str]) -> list[str]:
    try:
        value = json.loads(raw or "[]")
        return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []
    except (TypeError, ValueError):
        return []


def _quote_data(row: SalesQuoteRequests) -> dict:
    return {
        "id": row.id, "lead_id": row.lead_id, "package_name": row.package_name,
        "business_line_id": row.business_line_id, "product_id": row.product_id,
        "product_plan_id": row.product_plan_id,
        "selected_platforms": _list_json(row.selected_platforms), "billing_mode": row.billing_mode,
        "billing_cycle": row.billing_cycle or ("monthly" if row.billing_mode == "subscription" else "one_time"),
        "payment_method": row.payment_method, "currency": row.currency,
        "list_amount": row.list_amount, "discount_amount": row.discount_amount,
        "final_amount": row.final_amount, "service_start_date": row.service_start_date,
        "service_end_date": row.service_end_date, "special_terms": row.special_terms,
        "status": row.status, "submitted_by_name": row.submitted_by_name,
        "reviewed_by_name": row.reviewed_by_name, "reviewed_at": row.reviewed_at,
        "review_notes": row.review_notes, "created_at": row.created_at,
    }


def _handoff_data(row: Optional[SalesHandoffChecklists]) -> dict:
    if not row:
        return {}
    return {
        "id": row.id, "lead_id": row.lead_id, "quote_id": row.quote_id,
        "customer_goal": row.customer_goal, "key_contacts": row.key_contacts,
        "service_start_date": row.service_start_date, "service_end_date": row.service_end_date,
        "special_commitments": row.special_commitments, "operations_owner": row.operations_owner,
        "operations_owner_employee_id": row.operations_owner_employee_id,
        "collaborator_employee_ids": [int(item) for item in _list_json(row.collaborator_employee_ids) if str(item).isdigit()],
        "operations_group_created": row.operations_group_created,
        "finance_payment_confirmed": row.finance_payment_confirmed,
        "payment_status": row.payment_status or "pending", "amount_received": row.amount_received or 0,
        "payment_date": row.payment_date, "payment_reference": row.payment_reference,
        "payment_confirmed_by_name": row.payment_confirmed_by_name,
        "payment_confirmed_at": row.payment_confirmed_at, "generated_deal_id": row.generated_deal_id,
        "generate_service_board": row.generate_service_board, "handoff_notes": row.handoff_notes,
        "updated_by_name": row.updated_by_name, "updated_at": row.updated_at,
    }


def _blockers(quotes: list[SalesQuoteRequests], handoff: Optional[SalesHandoffChecklists]) -> list[str]:
    approved = next((quote for quote in quotes if quote.status == "approved"), None)
    if not approved:
        return ["需要一张已审批的报价单"]
    if not handoff:
        return ["尚未填写成交交接清单"]
    result = []
    if handoff.quote_id != approved.id:
        result.append("交接清单需要关联当前已审批报价")
    if not (handoff.customer_goal or "").strip():
        result.append("请填写客户目标")
    if not (handoff.key_contacts or "").strip():
        result.append("请填写关键联系人或对接方式")
    if not handoff.operations_owner_employee_id and not (handoff.operations_owner or "").strip():
        result.append("请选择运营对接负责人")
    if not handoff.operations_group_created:
        result.append("请确认已建立运营对接群")
    payment_status = handoff.payment_status or ("paid" if handoff.finance_payment_confirmed else "pending")
    if payment_status != "paid":
        payment_labels = {"pending": "等待收款", "deposit_paid": "已收订金，仍待尾款", "failed": "支付失败，等待处理", "refunded": "款项已退款"}
        result.append(payment_labels.get(payment_status, "等待财务确认全额收款"))
    start_date = handoff.service_start_date or approved.service_start_date
    end_date = handoff.service_end_date or approved.service_end_date
    if approved.billing_cycle != "one_time" and (not start_date or not end_date):
        result.append("周期性服务必须填写服务开始和结束日期")
    return result


class QuoteCreatePayload(BaseModel):
    business_line_id: Optional[int] = Field(default=None, ge=1)
    product_id: Optional[int] = Field(default=None, ge=1)
    product_plan_id: Optional[int] = Field(default=None, ge=1)
    package_name: str = Field(min_length=1, max_length=160)
    selected_platforms: list[str] = Field(default_factory=list, max_length=12)
    billing_mode: str = Field(default="manual", pattern="^(manual|subscription)$")
    billing_cycle: str = Field(default="one_time", pattern="^(monthly|quarterly|semi_annual|annual|one_time)$")
    payment_method: str = Field(default="stripe", pattern="^(stripe|check|zelle|bank_transfer|other)$")
    currency: str = Field(default="USD", max_length=8)
    list_amount: float = Field(ge=0, le=1_000_000)
    discount_amount: float = Field(default=0, ge=0, le=1_000_000)
    service_start_date: Optional[str] = Field(default=None, max_length=32)
    service_end_date: Optional[str] = Field(default=None, max_length=32)
    special_terms: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("package_name")
    @classmethod
    def strip_package(cls, value: str) -> str:
        return value.strip()


class QuoteReviewPayload(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    review_notes: Optional[str] = Field(default=None, max_length=2000)


class HandoffPayload(BaseModel):
    quote_id: Optional[int] = None
    customer_goal: Optional[str] = Field(default=None, max_length=4000)
    key_contacts: Optional[str] = Field(default=None, max_length=4000)
    service_start_date: Optional[str] = Field(default=None, max_length=32)
    service_end_date: Optional[str] = Field(default=None, max_length=32)
    special_commitments: Optional[str] = Field(default=None, max_length=4000)
    operations_owner: Optional[str] = Field(default=None, max_length=160)
    operations_owner_employee_id: Optional[int] = Field(default=None, ge=1)
    collaborator_employee_ids: list[int] = Field(default_factory=list, max_length=20)
    operations_group_created: bool = False
    generate_service_board: bool = False
    handoff_notes: Optional[str] = Field(default=None, max_length=4000)


class FinanceConfirmationPayload(BaseModel):
    payment_status: Optional[str] = Field(default=None, pattern="^(pending|deposit_paid|paid|failed|refunded)$")
    amount_received: Optional[float] = Field(default=None, ge=0, le=1_000_000)
    payment_date: Optional[str] = Field(default=None, max_length=32)
    payment_reference: Optional[str] = Field(default=None, max_length=240)
    finance_payment_confirmed: Optional[bool] = None


async def _validate_catalog_selection(db: AsyncSession, payload: QuoteCreatePayload):
    identifiers = (payload.business_line_id, payload.product_id, payload.product_plan_id)
    if payload.billing_mode == "subscription" and payload.billing_cycle == "one_time":
        raise HTTPException(status_code=400, detail="自动订阅不能使用一次性收费周期")
    if not any(identifiers):
        return None, None, None
    if not payload.business_line_id or not payload.product_id:
        raise HTTPException(status_code=400, detail="结构化报价必须选择业务线和具体产品")
    line = await db.get(BusinessLine, payload.business_line_id)
    product = await db.get(ProductCatalog, payload.product_id)
    plan = await db.get(ProductPlan, payload.product_plan_id) if payload.product_plan_id else None
    if not line or not line.is_active or not product or not product.is_active:
        raise HTTPException(status_code=400, detail="所选业务线或产品已停用，请重新选择")
    if product.business_line_id != line.id:
        raise HTTPException(status_code=400, detail="所选产品不属于当前业务线")
    if plan and (not plan.is_active or plan.product_id != product.id):
        raise HTTPException(status_code=400, detail="所选套餐版本不属于当前产品或已停用")
    selected_platforms = list(dict.fromkeys(item.strip() for item in payload.selected_platforms if item.strip()))
    if plan and plan.platform_limit and len(selected_platforms) > plan.platform_limit:
        raise HTTPException(status_code=400, detail=f"该套餐最多可选择 {plan.platform_limit} 个运营平台")
    return line, product, plan


@router.get("/options")
async def get_sales_deal_options(
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_sales_access(current_user)
    employees = (await db.scalars(
        select(Employees)
        .where(Employees.status.in_(["active", "probation"]))
        .order_by(Employees.department.asc(), Employees.name.asc())
    )).all()
    return {
        "employees": [
            {"id": row.id, "name": row.name, "role": row.role, "department": row.department, "position": row.position}
            for row in employees
        ]
    }


@router.get("/{lead_id}/readiness")
async def get_deal_readiness(
    lead_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_sales_access(current_user)
    lead = await _get_scoped_lead(db, lead_id, current_user)
    quotes = (await db.scalars(select(SalesQuoteRequests).where(SalesQuoteRequests.lead_id == lead.id).order_by(SalesQuoteRequests.created_at.desc()))).all()
    handoff = await db.scalar(select(SalesHandoffChecklists).where(SalesHandoffChecklists.lead_id == lead.id))
    return {
        "lead": {"id": lead.id, "business_name": lead.business_name, "converted_customer_id": lead.converted_customer_id},
        "quotes": [_quote_data(row) for row in quotes], "handoff": _handoff_data(handoff),
        "blockers": _blockers(quotes, handoff),
    }


@router.post("/{lead_id}/quotes", status_code=status.HTTP_201_CREATED)
async def create_quote(
    lead_id: int,
    payload: QuoteCreatePayload,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_sales_access(current_user)
    lead = await _get_scoped_lead(db, lead_id, current_user)
    if lead.converted_customer_id:
        raise HTTPException(status_code=409, detail="该线索已转为正式客户，不能再创建售前报价")
    final_amount = round(payload.list_amount - payload.discount_amount, 2)
    if final_amount < 0:
        raise HTTPException(status_code=400, detail="优惠金额不能大于报价金额")
    if "billing_cycle" not in payload.model_fields_set:
        payload.billing_cycle = "monthly" if payload.billing_mode == "subscription" else "one_time"
    line, product, plan = await _validate_catalog_selection(db, payload)
    package_name = (plan.name if plan else product.name) if product else payload.package_name
    row = SalesQuoteRequests(
        lead_id=lead.id, business_line_id=line.id if line else None, product_id=product.id if product else None,
        product_plan_id=plan.id if plan else None, package_name=package_name,
        selected_platforms=json.dumps(list(dict.fromkeys(payload.selected_platforms)), ensure_ascii=False),
        billing_mode=payload.billing_mode, billing_cycle=payload.billing_cycle,
        payment_method=payload.payment_method, currency=payload.currency.upper(),
        list_amount=payload.list_amount, discount_amount=payload.discount_amount, final_amount=final_amount,
        service_start_date=payload.service_start_date, service_end_date=payload.service_end_date,
        special_terms=payload.special_terms, status="submitted", submitted_by_id=_employee_id(current_user), submitted_by_name=current_user.name,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _quote_data(row)


@router.post("/quotes/{quote_id}/review")
async def review_quote(
    quote_id: int,
    payload: QuoteReviewPayload,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_manager(current_user)
    row = await db.get(SalesQuoteRequests, quote_id)
    if not row:
        raise HTTPException(status_code=404, detail="报价单不存在")
    await _get_scoped_lead(db, row.lead_id, current_user)
    if payload.decision == "approved":
        await db.execute(
            update(SalesQuoteRequests)
            .where(SalesQuoteRequests.lead_id == row.lead_id)
            .where(SalesQuoteRequests.id != row.id)
            .where(SalesQuoteRequests.status == "approved")
            .values(status="superseded", review_notes="已有更新报价获批，本报价自动失效")
        )
        handoff = await db.scalar(select(SalesHandoffChecklists).where(SalesHandoffChecklists.lead_id == row.lead_id))
        if handoff and handoff.quote_id != row.id:
            handoff.finance_payment_confirmed = False
            handoff.payment_status = "pending"
            handoff.amount_received = 0
            handoff.payment_reference = None
            handoff.payment_confirmed_by_id = None
            handoff.payment_confirmed_by_name = None
            handoff.payment_confirmed_at = None
    row.status = payload.decision
    row.review_notes = (payload.review_notes or "").strip() or None
    row.reviewed_by_id = _employee_id(current_user)
    row.reviewed_by_name = current_user.name
    row.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return _quote_data(row)


@router.put("/{lead_id}/handoff")
async def save_handoff(
    lead_id: int,
    payload: HandoffPayload,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_sales_access(current_user)
    lead = await _get_scoped_lead(db, lead_id, current_user)
    if payload.quote_id:
        quote = await db.get(SalesQuoteRequests, payload.quote_id)
        if not quote or quote.lead_id != lead.id:
            raise HTTPException(status_code=400, detail="交接清单只能关联该线索的报价单")
    owner = None
    if payload.operations_owner_employee_id:
        owner = await db.get(Employees, payload.operations_owner_employee_id)
        if not owner or owner.status not in {"active", "probation"}:
            raise HTTPException(status_code=400, detail="运营负责人必须是在职员工")
    collaborator_ids = list(dict.fromkeys(payload.collaborator_employee_ids))
    if collaborator_ids:
        valid_ids = set((await db.scalars(select(Employees.id).where(
            Employees.id.in_(collaborator_ids), Employees.status.in_(["active", "probation"])
        ))).all())
        if valid_ids != set(collaborator_ids):
            raise HTTPException(status_code=400, detail="协作人中包含不存在或已停用的员工")
    row = await db.scalar(select(SalesHandoffChecklists).where(SalesHandoffChecklists.lead_id == lead.id))
    if not row:
        row = SalesHandoffChecklists(lead_id=lead.id)
        db.add(row)
    if row.quote_id and payload.quote_id != row.quote_id:
        row.finance_payment_confirmed = False
        row.payment_status = "pending"
        row.amount_received = 0
        row.payment_reference = None
        row.payment_confirmed_by_id = None
        row.payment_confirmed_by_name = None
        row.payment_confirmed_at = None
    row.quote_id = payload.quote_id
    row.customer_goal = (payload.customer_goal or "").strip() or None
    row.key_contacts = (payload.key_contacts or "").strip() or None
    row.service_start_date = payload.service_start_date
    row.service_end_date = payload.service_end_date
    row.special_commitments = (payload.special_commitments or "").strip() or None
    row.operations_owner_employee_id = owner.id if owner else None
    row.operations_owner = owner.name if owner else ((payload.operations_owner or "").strip() or None)
    row.collaborator_employee_ids = json.dumps(collaborator_ids)
    row.operations_group_created = payload.operations_group_created
    row.generate_service_board = payload.generate_service_board
    row.handoff_notes = (payload.handoff_notes or "").strip() or None
    row.updated_by_id = _employee_id(current_user)
    row.updated_by_name = current_user.name
    await db.commit()
    await db.refresh(row)
    return _handoff_data(row)


@router.post("/{lead_id}/handoff/finance-confirmation")
async def confirm_finance_payment(
    lead_id: int,
    payload: FinanceConfirmationPayload,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_manager(current_user)
    lead = await _get_scoped_lead(db, lead_id, current_user)
    row = await db.scalar(select(SalesHandoffChecklists).where(SalesHandoffChecklists.lead_id == lead.id))
    if not row:
        raise HTTPException(status_code=400, detail="请先填写成交交接清单")
    payment_status = payload.payment_status
    if payment_status is None and payload.finance_payment_confirmed is not None:
        payment_status = "paid" if payload.finance_payment_confirmed else "pending"
    payment_status = payment_status or "pending"
    quote = await db.get(SalesQuoteRequests, row.quote_id) if row.quote_id else None
    final_amount = float(quote.final_amount or 0) if quote else 0.0
    amount_received = float(payload.amount_received or 0)
    if payment_status == "paid":
        amount_received = amount_received or final_amount
        if final_amount > 0 and amount_received + 0.005 < final_amount:
            raise HTTPException(status_code=400, detail="实收金额不足，不能标记为已全额支付")
    elif payment_status == "deposit_paid":
        if amount_received <= 0:
            raise HTTPException(status_code=400, detail="标记已收订金时必须填写实收金额")
        if final_amount > 0 and amount_received >= final_amount:
            raise HTTPException(status_code=400, detail="实收金额已达到报价总额，请选择已全额支付")
    elif payment_status in {"pending", "failed"}:
        amount_received = 0.0
    row.payment_status = payment_status
    row.amount_received = amount_received
    row.payment_date = payload.payment_date or row.payment_date
    row.payment_reference = (payload.payment_reference or "").strip() or None
    row.finance_payment_confirmed = payment_status == "paid"
    row.payment_confirmed_by_id = _employee_id(current_user)
    row.payment_confirmed_by_name = current_user.name
    row.payment_confirmed_at = datetime.now(timezone.utc)
    row.updated_by_id = _employee_id(current_user)
    row.updated_by_name = current_user.name
    await db.commit()
    await db.refresh(row)
    return _handoff_data(row)
