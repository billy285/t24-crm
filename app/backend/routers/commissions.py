import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_finance_user
from models.commissions import (
    CommissionAgreement,
    CommissionEntry,
    CommissionStatusEvent,
    CustomerCommissionAttribution,
    SalesPartner,
)
from models.customers import Customers
from models.employees import Employees
from models.management_decisions import BusinessLine, CustomerEngagement, ProductCatalog
from schemas.auth import UserResponse
from services.commissions import DEFAULT_DECAY, scan_commissions, utcnow


router = APIRouter(prefix="/api/v1/commissions", tags=["commissions"])
PARTNER_TYPES = {"agency", "partner", "employee", "direct"}
PARTNER_STATUSES = {"active", "suspended", "terminated", "settled"}
ENTRY_TRANSITIONS = {
    "pending_confirmation": {"confirmed", "reversed"},
    "confirmed": {"payable", "reversed"},
    "payable": {"paid"},
}


def actor_name(user: UserResponse) -> str:
    return user.name or user.email or str(user.id)


def _partner_payload(row: SalesPartner) -> dict:
    return {
        "id": row.id, "partner_code": row.partner_code, "name": row.name,
        "partner_type": row.partner_type, "employee_id": row.employee_id, "status": row.status,
        "joined_at": row.joined_at, "stopped_at": row.stopped_at,
        "contact_name": row.contact_name, "contact_phone": row.contact_phone,
        "contact_email": row.contact_email, "notes": row.notes,
        "created_at": row.created_at, "updated_at": row.updated_at,
    }


def _agreement_payload(row: CommissionAgreement) -> dict:
    try:
        decay = json.loads(row.activity_decay_json)
    except (TypeError, json.JSONDecodeError):
        decay = DEFAULT_DECAY
    return {
        "id": row.id, "partner_id": row.partner_id, "version": row.version,
        "business_line_id": row.business_line_id, "product_id": row.product_id,
        "first_order_rate": row.first_order_rate, "renewal_rate": row.renewal_rate,
        "activity_decay": decay, "refund_guard_days": row.refund_guard_days,
        "effective_from": row.effective_from, "effective_to": row.effective_to,
        "status": row.status, "notes": row.notes, "created_at": row.created_at,
    }


class PartnerInput(BaseModel):
    partner_code: str = Field(min_length=2, max_length=48)
    name: str = Field(min_length=1, max_length=160)
    partner_type: Literal["agency", "partner", "employee", "direct"] = "partner"
    employee_id: Optional[int] = Field(None, gt=0)
    joined_at: date
    contact_name: Optional[str] = Field(None, max_length=120)
    contact_phone: Optional[str] = Field(None, max_length=64)
    contact_email: Optional[str] = Field(None, max_length=160)
    notes: Optional[str] = Field(None, max_length=4000)

    @field_validator("partner_code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,47}", value):
            raise ValueError("渠道编号只能使用字母、数字、下划线或短横线")
        return value

    @model_validator(mode="after")
    def validate_employee(self):
        if self.partner_type == "employee" and not self.employee_id:
            raise ValueError("内部销售必须关联员工")
        return self


class AgreementInput(BaseModel):
    partner_id: int = Field(gt=0)
    business_line_id: Optional[int] = Field(None, gt=0)
    product_id: Optional[int] = Field(None, gt=0)
    first_order_rate: float = Field(ge=0, le=1)
    renewal_rate: float = Field(ge=0, le=1)
    activity_decay: dict[int, float] = Field(default_factory=lambda: DEFAULT_DECAY.copy())
    refund_guard_days: int = Field(default=30, ge=0, le=180)
    effective_from: date
    notes: Optional[str] = Field(None, max_length=4000)

    @field_validator("activity_decay")
    @classmethod
    def validate_decay(cls, value: dict[int, float]) -> dict[int, float]:
        normalized = {int(month): float(rate) for month, rate in value.items()}
        if 0 not in normalized or 6 not in normalized:
            raise ValueError("活跃衰减必须包含 0 月和 6 月")
        if any(month < 0 or month > 24 or rate < 0 or rate > 1 for month, rate in normalized.items()):
            raise ValueError("活跃衰减月份或比例无效")
        ordered = [normalized[key] for key in sorted(normalized)]
        if any(ordered[index] < ordered[index + 1] for index in range(len(ordered) - 1)):
            raise ValueError("停滞时间越长，续费倍率不能升高")
        return normalized


class AttributionInput(BaseModel):
    customer_id: int = Field(gt=0)
    partner_id: int = Field(gt=0)
    engagement_id: Optional[int] = Field(None, gt=0)
    effective_from: date
    source_note: Optional[str] = Field(None, max_length=4000)


class PartnerStatusInput(BaseModel):
    status: Literal["active", "suspended", "terminated", "settled"]
    effective_date: date
    reason: str = Field(min_length=2, max_length=1000)


class EntryTransitionInput(BaseModel):
    to_status: Literal["confirmed", "payable", "paid", "reversed"]
    reason: Optional[str] = Field(None, max_length=1000)
    payout_reference: Optional[str] = Field(None, max_length=160)


@router.get("/dashboard")
async def dashboard(
    month: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    _user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    entry_query = select(CommissionEntry)
    if month:
        entry_query = entry_query.where(CommissionEntry.service_month == month)
    entries = (await db.scalars(entry_query.order_by(CommissionEntry.occurred_at.desc(), CommissionEntry.id.desc()))).all()
    partners = (await db.scalars(select(SalesPartner).order_by(SalesPartner.id.desc()))).all()
    agreements = (await db.scalars(select(CommissionAgreement).order_by(CommissionAgreement.partner_id, CommissionAgreement.version.desc()))).all()
    attributions = (await db.scalars(select(CustomerCommissionAttribution).order_by(CustomerCommissionAttribution.id.desc()))).all()
    customer_ids = {row.customer_id for row in attributions} | {row.customer_id for row in entries}
    customers = (await db.scalars(select(Customers).where(Customers.id.in_(customer_ids)))).all() if customer_ids else []
    customer_map = {row.id: row.business_name for row in customers}
    partner_map = {row.id: row.name for row in partners}
    currencies: dict[str, dict[str, float]] = {}
    for entry in entries:
        bucket = currencies.setdefault(entry.currency, {"pending": 0, "confirmed_expense": 0, "payable": 0, "paid": 0})
        if entry.status == "pending_confirmation": bucket["pending"] += entry.commission_amount
        if entry.status in {"confirmed", "payable", "paid"}: bucket["confirmed_expense"] += entry.commission_amount
        if entry.status == "payable": bucket["payable"] += entry.commission_amount
        if entry.status == "paid": bucket["paid"] += entry.commission_amount
    return {
        "summary": {
            "partner_count": len(partners),
            "active_partner_count": sum(row.status == "active" for row in partners),
            "pending_count": sum(row.status == "pending_confirmation" for row in entries),
            "currencies": {code: {key: round(value, 2) for key, value in values.items()} for code, values in currencies.items()},
            "accounting_rule": "收入按实收总额记录；仅已确认佣金进入渠道佣金费用；发放仅冲减应付，不重复计费",
        },
        "partners": [_partner_payload(row) for row in partners],
        "agreements": [_agreement_payload(row) for row in agreements],
        "attributions": [{
            "id": row.id, "customer_id": row.customer_id, "customer_name": customer_map.get(row.customer_id),
            "engagement_id": row.engagement_id, "partner_id": row.partner_id,
            "partner_name": partner_map.get(row.partner_id), "attribution_role": row.attribution_role,
            "effective_from": row.effective_from, "effective_to": row.effective_to,
            "is_active": row.is_active, "source_note": row.source_note,
        } for row in attributions],
        "entries": [{
            "id": row.id, "partner_id": row.partner_id, "partner_name": partner_map.get(row.partner_id),
            "customer_id": row.customer_id, "customer_name": customer_map.get(row.customer_id),
            "payment_id": row.payment_id, "refund_id": row.refund_id, "original_entry_id": row.original_entry_id,
            "entry_type": row.entry_type, "status": row.status, "service_month": row.service_month,
            "occurred_at": row.occurred_at, "currency": row.currency,
            "gross_receipt_amount": row.gross_receipt_amount, "eligible_service_amount": row.eligible_service_amount,
            "contract_rate": row.contract_rate, "inactivity_months": row.inactivity_months,
            "activity_multiplier": row.activity_multiplier, "commission_amount": row.commission_amount,
            "confirmed_at": row.confirmed_at, "payable_at": row.payable_at,
            "paid_at": row.paid_at, "payout_reference": row.payout_reference,
        } for row in entries],
    }


@router.get("/options")
async def options(
    _user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    employees = (await db.scalars(select(Employees).where(Employees.status.in_(("active", "probation"))).order_by(Employees.name))).all()
    customers = (await db.scalars(select(Customers).order_by(Customers.business_name))).all()
    lines = (await db.scalars(select(BusinessLine).where(BusinessLine.is_active.is_(True)).order_by(BusinessLine.id))).all()
    products = (await db.scalars(select(ProductCatalog).where(ProductCatalog.is_active.is_(True)).order_by(ProductCatalog.name))).all()
    engagements = (await db.scalars(select(CustomerEngagement).order_by(CustomerEngagement.customer_id, CustomerEngagement.id))).all()
    return {
        "employees": [{"id": row.id, "name": row.name, "employee_code": row.employee_code} for row in employees],
        "customers": [{"id": row.id, "name": row.business_name, "code": row.customer_code} for row in customers],
        "business_lines": [{"id": row.id, "name": row.name, "code": row.code} for row in lines],
        "products": [{"id": row.id, "name": row.name, "business_line_id": row.business_line_id} for row in products],
        "engagements": [{"id": row.id, "customer_id": row.customer_id, "package_name": row.package_name, "status": row.status} for row in engagements],
        "default_decay": DEFAULT_DECAY,
    }


@router.post("/partners", status_code=status.HTTP_201_CREATED)
async def create_partner(
    payload: PartnerInput,
    user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    if await db.scalar(select(SalesPartner.id).where(SalesPartner.partner_code == payload.partner_code)):
        raise HTTPException(status_code=409, detail="渠道编号已存在")
    if payload.employee_id and not await db.get(Employees, payload.employee_id):
        raise HTTPException(status_code=404, detail="关联员工不存在")
    row = SalesPartner(**payload.model_dump(), status="active", created_by_id=str(user.id), created_by_name=actor_name(user))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _partner_payload(row)


@router.post("/partners/{partner_id}/status")
async def change_partner_status(
    partner_id: int,
    payload: PartnerStatusInput,
    user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    partner = await db.get(SalesPartner, partner_id)
    if not partner:
        raise HTTPException(status_code=404, detail="渠道不存在")
    if payload.effective_date < partner.joined_at:
        raise HTTPException(status_code=400, detail="生效日期不能早于加入日期")
    partner.status = payload.status
    partner.stopped_at = payload.effective_date if payload.status in {"terminated", "settled"} else None
    partner.notes = "\n".join(filter(None, [partner.notes, f"{payload.effective_date} {payload.status}: {payload.reason}"]))
    if payload.status in {"terminated", "settled"}:
        active_links = (await db.scalars(select(CustomerCommissionAttribution).where(
            CustomerCommissionAttribution.partner_id == partner.id,
            CustomerCommissionAttribution.is_active.is_(True),
        ))).all()
        for link in active_links:
            link.effective_to = payload.effective_date
            link.is_active = False
    await db.commit()
    return _partner_payload(partner)


@router.post("/agreements", status_code=status.HTTP_201_CREATED)
async def create_agreement(
    payload: AgreementInput,
    user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    partner = await db.get(SalesPartner, payload.partner_id)
    if not partner:
        raise HTTPException(status_code=404, detail="渠道不存在")
    if partner.status in {"terminated", "settled"}:
        raise HTTPException(status_code=409, detail="已终止或已结清的渠道不能新增协议")
    if payload.product_id:
        product = await db.get(ProductCatalog, payload.product_id)
        if not product or (payload.business_line_id and product.business_line_id != payload.business_line_id):
            raise HTTPException(status_code=400, detail="产品与业务线不匹配")
    latest_version = await db.scalar(select(func.max(CommissionAgreement.version)).where(CommissionAgreement.partner_id == partner.id)) or 0
    existing = (await db.scalars(select(CommissionAgreement).where(
        CommissionAgreement.partner_id == partner.id,
        CommissionAgreement.status == "active",
        CommissionAgreement.business_line_id.is_(payload.business_line_id) if payload.business_line_id is None else CommissionAgreement.business_line_id == payload.business_line_id,
        CommissionAgreement.product_id.is_(payload.product_id) if payload.product_id is None else CommissionAgreement.product_id == payload.product_id,
        or_(CommissionAgreement.effective_to.is_(None), CommissionAgreement.effective_to >= payload.effective_from),
    ))).all()
    for row in existing:
        if row.effective_from >= payload.effective_from:
            raise HTTPException(status_code=409, detail="该范围已存在同日或更晚生效的协议，请调整生效日期")
        row.effective_to = payload.effective_from - timedelta(days=1)
        row.status = "expired"
    row = CommissionAgreement(
        partner_id=payload.partner_id, version=latest_version + 1,
        business_line_id=payload.business_line_id, product_id=payload.product_id,
        first_order_rate=payload.first_order_rate, renewal_rate=payload.renewal_rate,
        activity_decay_json=json.dumps(payload.activity_decay, sort_keys=True),
        refund_guard_days=payload.refund_guard_days, effective_from=payload.effective_from,
        status="active", notes=payload.notes, created_by_id=str(user.id), created_by_name=actor_name(user),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await scan_commissions(db)
    return _agreement_payload(row)


@router.post("/attributions", status_code=status.HTTP_201_CREATED)
async def create_attribution(
    payload: AttributionInput,
    user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    customer = await db.get(Customers, payload.customer_id)
    partner = await db.get(SalesPartner, payload.partner_id)
    if not customer or not partner:
        raise HTTPException(status_code=404, detail="客户或渠道不存在")
    if partner.status != "active":
        raise HTTPException(status_code=409, detail="只能归属给正常合作中的渠道")
    if payload.engagement_id:
        engagement = await db.get(CustomerEngagement, payload.engagement_id)
        if not engagement or engagement.customer_id != payload.customer_id:
            raise HTTPException(status_code=400, detail="项目不属于所选客户")
    current = (await db.scalars(select(CustomerCommissionAttribution).where(
        CustomerCommissionAttribution.customer_id == payload.customer_id,
        CustomerCommissionAttribution.engagement_id.is_(payload.engagement_id) if payload.engagement_id is None else CustomerCommissionAttribution.engagement_id == payload.engagement_id,
        CustomerCommissionAttribution.attribution_role == "primary",
        CustomerCommissionAttribution.is_active.is_(True),
    ))).all()
    for link in current:
        if link.effective_from >= payload.effective_from:
            raise HTTPException(status_code=409, detail="当前归属的生效日期不早于新归属，请先核对日期")
        link.effective_to = payload.effective_from - timedelta(days=1)
        link.is_active = False
    row = CustomerCommissionAttribution(
        **payload.model_dump(), attribution_role="primary", is_active=True,
        created_by_id=str(user.id), created_by_name=actor_name(user),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await scan_commissions(db)
    return {"id": row.id, "customer_id": row.customer_id, "partner_id": row.partner_id, "effective_from": row.effective_from}


@router.post("/scan")
async def run_scan(
    _user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    return await scan_commissions(db)


@router.post("/entries/{entry_id}/transition")
async def transition_entry(
    entry_id: int,
    payload: EntryTransitionInput,
    user: UserResponse = Depends(get_finance_user),
    db: AsyncSession = Depends(get_db),
):
    entry = await db.get(CommissionEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="佣金记录不存在")
    if payload.to_status not in ENTRY_TRANSITIONS.get(entry.status, set()):
        raise HTTPException(status_code=409, detail=f"不允许从 {entry.status} 变更为 {payload.to_status}")
    if payload.to_status == "reversed" and not (payload.reason or "").strip():
        raise HTTPException(status_code=400, detail="作废必须填写原因")
    agreement = await db.get(CommissionAgreement, entry.agreement_id)
    if payload.to_status == "confirmed" and agreement and entry.entry_type == "first_order":
        guard_ends = entry.occurred_at + timedelta(days=agreement.refund_guard_days)
        if guard_ends.tzinfo is None:
            guard_ends = guard_ends.replace(tzinfo=timezone.utc)
        if utcnow() < guard_ends:
            raise HTTPException(status_code=409, detail=f"首单仍在 {agreement.refund_guard_days} 天退款观察期，{guard_ends.date()} 后可确认")
    if payload.to_status == "paid" and not (payload.payout_reference or "").strip():
        raise HTTPException(status_code=400, detail="标记已发放必须填写付款流水号或凭证编号")
    partner = await db.get(SalesPartner, entry.partner_id)
    if payload.to_status in {"payable", "paid"} and partner and partner.status == "suspended":
        raise HTTPException(status_code=409, detail="该渠道当前暂停结算，请恢复合作或完成复核后再进入应付/发放")
    previous = entry.status
    entry.status = payload.to_status
    now = utcnow()
    if payload.to_status == "confirmed": entry.confirmed_at = now
    if payload.to_status == "payable": entry.payable_at = now
    if payload.to_status == "paid":
        entry.paid_at = now
        entry.payout_reference = payload.payout_reference.strip()
    db.add(CommissionStatusEvent(
        commission_entry_id=entry.id, from_status=previous, to_status=entry.status,
        reason=(payload.reason or "").strip() or None, actor_id=str(user.id), actor_name=actor_name(user),
    ))
    await db.commit()
    return {"id": entry.id, "status": entry.status, "message": "佣金状态已更新，历史快照未改写"}
