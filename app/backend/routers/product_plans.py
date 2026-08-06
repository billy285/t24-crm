import json
import re
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_admin_user, get_current_user
from models.management_decisions import BusinessLine, ProductCatalog, ProductPlan
from schemas.auth import UserResponse


router = APIRouter(prefix="/api/v1/product-plans", tags=["product-plans"])

PRICING_STATUSES = {"draft", "published", "retired"}
SCOPE_TYPES = {"platforms", "restaurant_os", "beauty_os", "generic"}
BILLING_CYCLES = {"monthly", "quarterly", "annual", "one_time"}
CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,79}$")


class ProductInput(BaseModel):
    business_line_id: int = Field(ge=1)
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=160)
    billing_kind: Literal["recurring", "one_time"] = "recurring"
    default_currency: str = Field("USD", min_length=3, max_length=3)
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        value = value.strip().lower()
        if not CODE_PATTERN.fullmatch(value):
            raise ValueError("产品代码只能使用小写字母、数字、下划线或短横线")
        return value


class PlanInput(BaseModel):
    product_id: int = Field(ge=1)
    code: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=2, max_length=160)
    version_label: Optional[str] = Field(None, max_length=80)
    pricing_status: Literal["draft", "published", "retired"] = "draft"
    standard_price: Optional[float] = Field(None, ge=0)
    default_currency: str = Field("USD", min_length=3, max_length=3)
    default_billing_cycle: Optional[Literal["monthly", "quarterly", "annual", "one_time"]] = None
    platform_limit: Optional[int] = Field(None, ge=1, le=50)
    scope_type: Literal["platforms", "restaurant_os", "beauty_os", "generic"] = "generic"
    entitlements: list[str] = Field(default_factory=list, max_length=100)
    is_active: bool = True
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        value = value.strip().lower()
        if not CODE_PATTERN.fullmatch(value):
            raise ValueError("套餐代码只能使用小写字母、数字、下划线或短横线")
        return value

    @field_validator("default_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("entitlements")
    @classmethod
    def normalize_entitlements(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @model_validator(mode="after")
    def validate_business_rules(self):
        if self.pricing_status == "published" and self.standard_price is None:
            raise ValueError("发布套餐前必须填写标准价格")
        if self.scope_type == "platforms" and self.platform_limit is None:
            raise ValueError("代运营套餐必须填写可选平台数量")
        if self.scope_type != "platforms" and self.platform_limit is not None:
            raise ValueError("只有按平台计费的套餐可以设置平台数量")
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("结束日期不能早于开始日期")
        return self


def _safe_json_list(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def _line_payload(row: BusinessLine) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "is_recurring": bool(row.is_recurring),
        "is_active": bool(row.is_active),
    }


def _product_payload(row: ProductCatalog, line: BusinessLine) -> dict:
    return {
        "id": row.id,
        "business_line_id": row.business_line_id,
        "business_line_code": line.code,
        "business_line_name": line.name,
        "code": row.code,
        "name": row.name,
        "billing_kind": row.billing_kind,
        "default_currency": row.default_currency,
        "is_active": bool(row.is_active),
    }


def _plan_payload(row: ProductPlan, product: ProductCatalog, line: BusinessLine) -> dict:
    return {
        "id": row.id,
        "product_id": row.product_id,
        "product_code": product.code,
        "product_name": product.name,
        "business_line_id": line.id,
        "business_line_code": line.code,
        "business_line_name": line.name,
        "code": row.code,
        "name": row.name,
        "version_label": row.version_label,
        "pricing_status": row.pricing_status,
        "standard_price": row.standard_price,
        "default_currency": row.default_currency,
        "default_billing_cycle": row.default_billing_cycle,
        "platform_limit": row.platform_limit,
        "scope_type": row.scope_type,
        "entitlements": _safe_json_list(row.entitlements_json),
        "is_active": bool(row.is_active),
        "effective_from": row.effective_from,
        "effective_to": row.effective_to,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("")
async def list_product_plans(
    active_only: bool = Query(False),
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lines = (await db.execute(select(BusinessLine).order_by(BusinessLine.id))).scalars().all()
    product_query = select(ProductCatalog, BusinessLine).join(BusinessLine, BusinessLine.id == ProductCatalog.business_line_id)
    plan_query = (
        select(ProductPlan, ProductCatalog, BusinessLine)
        .join(ProductCatalog, ProductCatalog.id == ProductPlan.product_id)
        .join(BusinessLine, BusinessLine.id == ProductCatalog.business_line_id)
    )
    if active_only:
        product_query = product_query.where(ProductCatalog.is_active.is_(True), BusinessLine.is_active.is_(True))
        plan_query = plan_query.where(
            ProductPlan.is_active.is_(True), ProductCatalog.is_active.is_(True), BusinessLine.is_active.is_(True)
        )
    products = (await db.execute(product_query.order_by(BusinessLine.id, ProductCatalog.id))).all()
    plans = (await db.execute(plan_query.order_by(BusinessLine.id, ProductCatalog.id, ProductPlan.id))).all()
    return {
        "business_lines": [_line_payload(row) for row in lines if not active_only or row.is_active],
        "products": [_product_payload(product, line) for product, line in products],
        "plans": [_plan_payload(plan, product, line) for plan, product, line in plans],
        "rules": {
            "pricing_statuses": sorted(PRICING_STATUSES),
            "scope_types": sorted(SCOPE_TYPES),
            "billing_cycles": sorted(BILLING_CYCLES),
            "draft_price_allowed": True,
        },
    }


@router.post("/products", status_code=201)
async def create_product(
    payload: ProductInput,
    _current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    line = await db.get(BusinessLine, payload.business_line_id)
    if not line:
        raise HTTPException(status_code=404, detail="业务线不存在")
    duplicate = (await db.execute(select(ProductCatalog).where(ProductCatalog.code == payload.code))).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="产品代码已存在")
    product = ProductCatalog(**payload.model_dump())
    product.default_currency = product.default_currency.upper()
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return _product_payload(product, line)


@router.put("/products/{product_id}")
async def update_product(
    product_id: int,
    payload: ProductInput,
    _current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    product = await db.get(ProductCatalog, product_id)
    line = await db.get(BusinessLine, payload.business_line_id)
    if not product or not line:
        raise HTTPException(status_code=404, detail="产品或业务线不存在")
    duplicate = (await db.execute(
        select(ProductCatalog).where(ProductCatalog.code == payload.code, ProductCatalog.id != product_id)
    )).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="产品代码已存在")
    for key, value in payload.model_dump().items():
        setattr(product, key, value)
    product.default_currency = product.default_currency.upper()
    await db.commit()
    await db.refresh(product)
    return _product_payload(product, line)


@router.post("/plans", status_code=201)
async def create_plan(
    payload: PlanInput,
    _current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    product = await db.get(ProductCatalog, payload.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="产品不存在")
    duplicate = (await db.execute(select(ProductPlan).where(ProductPlan.code == payload.code))).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="套餐代码已存在")
    data = payload.model_dump(exclude={"entitlements"})
    plan = ProductPlan(**data, entitlements_json=json.dumps(payload.entitlements, ensure_ascii=False))
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    line = await db.get(BusinessLine, product.business_line_id)
    return _plan_payload(plan, product, line)


@router.put("/plans/{plan_id}")
async def update_plan(
    plan_id: int,
    payload: PlanInput,
    _current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    plan = await db.get(ProductPlan, plan_id)
    product = await db.get(ProductCatalog, payload.product_id)
    if not plan or not product:
        raise HTTPException(status_code=404, detail="套餐或产品不存在")
    duplicate = (await db.execute(
        select(ProductPlan).where(ProductPlan.code == payload.code, ProductPlan.id != plan_id)
    )).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="套餐代码已存在")
    for key, value in payload.model_dump(exclude={"entitlements"}).items():
        setattr(plan, key, value)
    plan.entitlements_json = json.dumps(payload.entitlements, ensure_ascii=False)
    await db.commit()
    await db.refresh(plan)
    line = await db.get(BusinessLine, product.business_line_id)
    return _plan_payload(plan, product, line)
