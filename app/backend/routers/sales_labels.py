import unicodedata
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_current_user
from models.sales_labels import SalesLabel, SalesLabelAssignment
from schemas.auth import UserResponse
from services.merchant_industries import normalize_merchant_industry
from services.merchant_row_locks import lock_merchant_rows
from services.sales_labels import active_labels, add_labels, catalog_item, label_applies, target_labels
from services.sales_workflow_locks import lock_sales_workflow

router = APIRouter(prefix="/api/v1/sales-labels", tags=["sales-labels"])


class LabelDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: Literal["source", "provider", "operation"]
    industry: Literal["all", "restaurant", "beauty"] = "all"
    archived: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value):
        return " ".join(value.split()) if isinstance(value, str) else value


class LabelChange(BaseModel):
    label_id: int = Field(gt=0)
    action: Literal["add", "confirm", "remove"] = "add"


class BulkLabels(BaseModel):
    merchant_ids: list[int] = Field(min_length=1, max_length=200)
    label_ids: list[int] = Field(min_length=1, max_length=20)


def _ensure_catalog_access(user):
    if user.role not in {"super_admin", "admin", "sales_manager", "sales"}:
        raise HTTPException(403, "当前账号没有销售标签权限")


def _ensure_owner(user):
    if user.role != "super_admin":
        raise HTTPException(403, "只有老板可以管理标签目录")


@router.get("")
async def list_labels(user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _ensure_catalog_access(user)
    query = select(SalesLabel).order_by(SalesLabel.archived, SalesLabel.kind, SalesLabel.name)
    if user.role != "super_admin":
        query = query.where(SalesLabel.archived.is_(False))
    return {"items": [catalog_item(item) for item in (await db.execute(query)).scalars()]}


async def _save_definition(db, label, definition):
    normal = unicodedata.normalize("NFKC", definition.name).casefold()
    if len(normal) > 180:
        raise HTTPException(422, "标签名称过长")
    label.name = definition.name
    label.normalized_name = normal
    label.kind = definition.kind
    label.industry = definition.industry
    label.archived = definition.archived
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, "同一分类下已存在相同名称的标签，可从目录中恢复停用标签") from error
    return catalog_item(label)


@router.post("")
async def create_label(definition: LabelDefinition, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _ensure_owner(user)
    await lock_merchant_rows(db, [])
    label = SalesLabel()
    db.add(label)
    return await _save_definition(db, label, definition)


@router.put("/catalog/{label_id}")
async def update_label(label_id: int, definition: LabelDefinition, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _ensure_owner(user)
    await lock_merchant_rows(db, [])
    label = (await db.execute(select(SalesLabel).where(SalesLabel.id == label_id).with_for_update())).scalar_one_or_none()
    if not label:
        raise HTTPException(404, "标签不存在")
    if definition.kind != label.kind or definition.industry != label.industry:
        raise HTTPException(422, "已创建标签保留原类别和行业，请新建另一标签")
    return await _save_definition(db, label, definition)


async def _merchant_targets(db, ids, user, *, for_write=False):
    from routers.merchant_pool import _ensure_pool_role, _manager_scope
    from routers.sales_leads import _get_scoped_lead
    from models.merchant_pool import MerchantPool
    _ensure_pool_role(user)
    ids = set(ids)
    if for_write:
        rows = await lock_merchant_rows(db, ids)
    else:
        rows = (await db.execute(select(MerchantPool).where(MerchantPool.id.in_(ids)))).scalars().all()
    if for_write and any(row.converted_lead_id is not None for row in rows):
        await lock_sales_workflow(db, lead_ids=[row.converted_lead_id for row in rows if row.converted_lead_id is not None])
    if {row.id for row in rows} != ids:
        raise HTTPException(404, "部分商家不存在")
    scope = await _manager_scope(db, user)
    if scope is not None and any(row.created_by_id != int(user.id) for row in rows):
        raise HTTPException(404, "部分商家不在您的权限范围")
    targets = []
    for row in rows:
        if row.pool_status in {"archived", "duplicate", "existing_customer"}:
            raise HTTPException(409, "请在有效商家或对应的销售线索上维护标签")
        lead = await _get_scoped_lead(db, row.converted_lead_id, user) if row.converted_lead_id is not None else None
        targets.append(SimpleNamespace(id=row.id, industry=lead.industry if lead is not None else row.industry))
    return targets


async def _lead_target(db, lead_id, user, *, for_write=False):
    from routers.sales_leads import _ensure_lead_role, _get_scoped_lead
    _ensure_lead_role(user)
    # Serialize any canonical pool mutation first, matching conversion lock order.
    lead = await _get_scoped_lead(db, lead_id, user)
    merchant_id = lead.merchant_pool_id
    if for_write:
        merchants = await lock_merchant_rows(db, [merchant_id] if merchant_id is not None else [])
        await lock_sales_workflow(db, lead_ids=[lead_id])
        lead = await _get_scoped_lead(db, lead_id, user)
        if lead.merchant_pool_id != merchant_id:
            raise HTTPException(409, "线索归属刚有更新，请重新打开标签")
        if not merchants:
            merchant_id = None
    return lead, merchant_id


async def _label_change(db, target, change, user, *, merchant):
    label = (await db.execute(select(SalesLabel).where(SalesLabel.id == change.label_id).with_for_update())).scalar_one_or_none()
    if not label:
        raise HTTPException(404, "标签不存在")
    if user.role == "sales" and label.kind == "source":
        raise HTTPException(403, "名单来源由负责人维护")
    if change.action == "remove":
        target_column = SalesLabelAssignment.merchant_id if merchant else SalesLabelAssignment.lead_id
        await db.execute(delete(SalesLabelAssignment).where(
            target_column == target.id, SalesLabelAssignment.label_id == change.label_id))
    else:
        if label.archived or not label_applies(label, target.industry):
            raise HTTPException(422, "标签已停用或不适用于该行业")
        if change.action == "confirm" and label.kind != "provider":
            raise HTTPException(422, "只有在用系统标签可以确认")
        await add_labels(db, merchants=[target] if merchant else [], leads=[] if merchant else [target],
                         labels=[label], actor_id=int(user.id), provider_confirmed=change.action == "confirm")
    await db.commit()


@router.post("/merchants/bulk")
async def add_merchant_labels(request: BulkLabels, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    targets = await _merchant_targets(db, request.merchant_ids, user, for_write=True)
    labels = await active_labels(db, request.label_ids)
    if any(not label_applies(label, row.industry) for row in targets for label in labels):
        raise HTTPException(422, "有商家行业和所选标签不一致，请先按行业筛选")
    count = await add_labels(db, merchants=targets, labels=labels)
    await db.commit()
    return {"added_count": count}


@router.get("/merchants/{merchant_id}")
async def read_merchant_labels(merchant_id: int, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    target, = await _merchant_targets(db, [merchant_id], user)
    merchants, _ = await target_labels(db, [merchant_id])
    return {"items": merchants.get(merchant_id, []), "industry": normalize_merchant_industry(target.industry)}


@router.put("/merchants/{merchant_id}")
async def change_merchant_label(merchant_id: int, change: LabelChange, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    target, = await _merchant_targets(db, [merchant_id], user, for_write=True)
    await _label_change(db, target, change, user, merchant=True)
    return await read_merchant_labels(merchant_id, user, db)


@router.get("/leads/{lead_id}")
async def read_lead_labels(lead_id: int, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    lead, merchant_id = await _lead_target(db, lead_id, user)
    merchants, leads = await target_labels(db, [merchant_id] if merchant_id is not None else [], [lead_id])
    return {"items": [*merchants.get(merchant_id, []), *leads.get(lead_id, [])],
            "industry": normalize_merchant_industry(lead.industry)}


@router.put("/leads/{lead_id}")
async def change_lead_label(lead_id: int, change: LabelChange, user: UserResponse = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    lead, merchant_id = await _lead_target(db, lead_id, user, for_write=True)
    merchant = merchant_id is not None
    target = SimpleNamespace(id=merchant_id if merchant else lead.id, industry=lead.industry)
    await _label_change(db, target, change, user, merchant=merchant)
    return await read_lead_labels(lead_id, user, db)
