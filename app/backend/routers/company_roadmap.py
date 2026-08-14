from __future__ import annotations

from datetime import date, datetime, timezone
import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from dependencies.auth import get_admin_user, get_current_user
from models.company_roadmap import (
    CashAccount,
    CashAccountBalance,
    CashAuditLog,
    CashPeriod,
    CashRestriction,
    CompanyStrategySettings,
    StrategyRecommendationDecision,
)
from models.tasks import Tasks
from schemas.auth import UserResponse
from services.company_roadmap import (
    RESTRICTION_LABELS,
    actor_name,
    add_cash_audit,
    build_company_roadmap_overview,
    build_restriction_suggestions,
    cash_period_payload,
)


router = APIRouter(prefix="/api/v1/company-roadmap", tags=["company-roadmap"])
ALLOWED_ROLES = {"admin", "super_admin", "finance"}
ACCOUNT_TYPES = {"bank", "payment_platform", "cash", "other"}


def cash_account_payload(row: CashAccount) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "account_type": row.account_type,
        "currency": row.currency,
        "masked_identifier": row.masked_identifier,
        "is_active": bool(row.is_active),
        "sort_order": row.sort_order,
        "notes": row.notes,
    }


def ensure_finance_role(user: UserResponse) -> str:
    role = str(user.role or "").lower()
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="无权访问公司战略与现金数据")
    return role


def valid_month(value: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise HTTPException(status_code=400, detail="月份格式应为 YYYY-MM")
    return value


class StrategySettingsInput(BaseModel):
    target_start_date: date
    target_end_date: date
    five_year_profit_target_cny: float = Field(gt=0, le=1_000_000_000)
    monthly_fixed_expense_cny: float = Field(gt=0, le=100_000_000)
    cash_reserve_months: int = Field(ge=1, le=36)
    default_usd_cny_rate: float = Field(gt=0.1, lt=20)
    current_focus: Optional[str] = Field(None, max_length=240)


class CashAccountInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    account_type: str = "bank"
    currency: Literal["USD", "CNY"] = "CNY"
    masked_identifier: Optional[str] = Field(None, max_length=80)
    is_active: bool = True
    sort_order: int = Field(0, ge=0, le=999)
    notes: Optional[str] = Field(None, max_length=1000)

    @field_validator("account_type")
    @classmethod
    def validate_account_type(cls, value: str) -> str:
        if value not in ACCOUNT_TYPES:
            raise ValueError("无效的账户类型")
        return value

    @field_validator("masked_identifier")
    @classmethod
    def validate_masked_identifier(cls, value: Optional[str]) -> Optional[str]:
        value = (value or "").strip() or None
        if value and len(re.findall(r"\d", value)) > 6:
            raise ValueError("只允许填写账户简称或最多 6 位脱敏末号，请勿保存完整账号")
        return value


class BalanceInput(BaseModel):
    account_id: int = Field(ge=1)
    balance: float = Field(ge=0, le=10_000_000_000)


class RestrictionInput(BaseModel):
    category: str
    description: str = Field(min_length=1, max_length=240)
    currency: Literal["USD", "CNY"]
    amount: float = Field(gt=0, le=10_000_000_000)
    source_ref: Optional[str] = Field(None, max_length=160)
    notes: Optional[str] = Field(None, max_length=1000)

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        if value not in RESTRICTION_LABELS:
            raise ValueError("无效的受限资金类别")
        return value


class CashPeriodInput(BaseModel):
    snapshot_date: date
    usd_cny_rate: float = Field(gt=0.1, lt=20)
    notes: Optional[str] = Field(None, max_length=2000)
    balances: list[BalanceInput] = Field(default_factory=list, max_length=100)
    restrictions: list[RestrictionInput] = Field(default_factory=list, max_length=300)


class CashPeriodTransition(BaseModel):
    action: Literal["lock", "reopen"]
    reason: Optional[str] = Field(None, max_length=1000)


class RecommendationDecisionInput(BaseModel):
    status: Literal["accepted", "deferred", "rejected", "completed"]
    decision_note: Optional[str] = Field(None, max_length=2000)
    next_review_date: Optional[date] = None
    create_task: bool = False


@router.get("/overview")
async def get_company_roadmap_overview(
    month: Optional[str] = Query(None),
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ensure_finance_role(current_user)
    if month:
        valid_month(month)
    return await build_company_roadmap_overview(db, selected_month=month)


@router.put("/settings")
async def update_strategy_settings(
    payload: StrategySettingsInput,
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.target_end_date <= payload.target_start_date:
        raise HTTPException(status_code=400, detail="目标结束日期必须晚于开始日期")
    row = (
        await db.execute(select(CompanyStrategySettings).where(CompanyStrategySettings.settings_key == "company"))
    ).scalar_one_or_none()
    values = payload.model_dump()
    values["updated_by"] = actor_name(current_user)
    if row:
        for key, value in values.items():
            setattr(row, key, value)
    else:
        row = CompanyStrategySettings(settings_key="company", **values)
        db.add(row)
    await db.commit()
    return {"message": "公司目标设置已保存"}


@router.post("/cash-accounts", status_code=201)
async def create_cash_account(
    payload: CashAccountInput,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ensure_finance_role(current_user)
    row = CashAccount(**payload.model_dump(), created_by=actor_name(current_user))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "account": cash_account_payload(row), "message": "现金账户已新增"}


@router.put("/cash-accounts/{account_id}")
async def update_cash_account(
    account_id: int,
    payload: CashAccountInput,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ensure_finance_role(current_user)
    row = await db.get(CashAccount, account_id)
    if not row:
        raise HTTPException(status_code=404, detail="现金账户不存在")
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "account": cash_account_payload(row), "message": "现金账户已更新"}


@router.put("/cash-periods/{year_month}")
async def save_cash_period(
    year_month: str,
    payload: CashPeriodInput,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ensure_finance_role(current_user)
    year_month = valid_month(year_month)
    if year_month > date.today().strftime("%Y-%m"):
        raise HTTPException(status_code=400, detail="不能建立未来月份的现金快照")
    if payload.snapshot_date.strftime("%Y-%m") != year_month:
        raise HTTPException(status_code=400, detail="快照日期必须属于所选月份")
    account_ids = list(dict.fromkeys(item.account_id for item in payload.balances))
    if len(account_ids) != len(payload.balances):
        raise HTTPException(status_code=400, detail="同一账户在一个快照中不能重复")
    accounts = []
    if account_ids:
        accounts = (
            await db.execute(select(CashAccount).where(CashAccount.id.in_(account_ids)))
        ).scalars().all()
    account_by_id = {int(row.id): row for row in accounts}
    if len(account_by_id) != len(account_ids):
        raise HTTPException(status_code=400, detail="现金账户不存在或已被移除")
    source_refs = [item.source_ref for item in payload.restrictions if item.source_ref]
    if len(source_refs) != len(set(source_refs)):
        raise HTTPException(status_code=400, detail="同一个系统建议不能重复加入")

    period = (
        await db.execute(select(CashPeriod).where(CashPeriod.year_month == year_month))
    ).scalar_one_or_none()
    if period and period.status == "locked":
        raise HTTPException(status_code=409, detail="已确认的现金快照已锁定，请先填写原因重新打开")
    if not period:
        period = CashPeriod(
            year_month=year_month,
            snapshot_date=payload.snapshot_date,
            status="draft",
            usd_cny_rate=payload.usd_cny_rate,
            notes=payload.notes,
            created_by=actor_name(current_user),
        )
        db.add(period)
        await db.flush()
    else:
        period.snapshot_date = payload.snapshot_date
        period.usd_cny_rate = payload.usd_cny_rate
        period.notes = payload.notes

    await db.execute(delete(CashAccountBalance).where(CashAccountBalance.period_id == period.id))
    await db.execute(delete(CashRestriction).where(CashRestriction.period_id == period.id))
    await db.flush()
    for item in payload.balances:
        account = account_by_id[item.account_id]
        rate = payload.usd_cny_rate if account.currency == "USD" else 1.0
        db.add(CashAccountBalance(
            period_id=period.id,
            account_id=account.id,
            currency=account.currency,
            balance=item.balance,
            rate_to_cny=rate,
            balance_cny=round(item.balance * rate, 2),
        ))
    for item in payload.restrictions:
        rate = payload.usd_cny_rate if item.currency == "USD" else 1.0
        db.add(CashRestriction(
            period_id=period.id,
            category=item.category,
            description=item.description,
            currency=item.currency,
            amount=item.amount,
            rate_to_cny=rate,
            amount_cny=round(item.amount * rate, 2),
            source_ref=item.source_ref,
            notes=item.notes,
        ))
    await db.flush()
    await add_cash_audit(db, period, current_user, "saved")
    await db.commit()
    return await cash_period_payload(db, period)


@router.post("/cash-periods/{year_month}/transition")
async def transition_cash_period(
    year_month: str,
    payload: CashPeriodTransition,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    role = ensure_finance_role(current_user)
    year_month = valid_month(year_month)
    period = (
        await db.execute(select(CashPeriod).where(CashPeriod.year_month == year_month))
    ).scalar_one_or_none()
    if not period:
        raise HTTPException(status_code=404, detail="现金快照不存在")
    now = datetime.now(timezone.utc)
    actor = actor_name(current_user)
    if payload.action == "lock":
        if period.status == "locked":
            return await cash_period_payload(db, period)
        balance_count = len((await db.execute(
            select(CashAccountBalance.id).where(CashAccountBalance.period_id == period.id)
        )).scalars().all())
        if not balance_count:
            raise HTTPException(status_code=409, detail="至少录入一个账户余额后才能确认")
        if year_month == date.today().strftime("%Y-%m"):
            suggestions = await build_restriction_suggestions(db, float(period.usd_cny_rate))
            recorded_refs = set((await db.execute(
                select(CashRestriction.source_ref).where(CashRestriction.period_id == period.id)
            )).scalars().all())
            missing = [row for row in suggestions if row["source_ref"] not in recorded_refs]
            if missing:
                labels = "、".join(row["category_label"] for row in missing)
                raise HTTPException(
                    status_code=409,
                    detail=f"还有 {len(missing)} 项系统受限资金建议未加入：{labels}。请先加入并核对后再确认。",
                )
        period.status = "locked"
        period.locked_at = now
        period.locked_by = actor
    else:
        if role not in {"admin", "super_admin"}:
            raise HTTPException(status_code=403, detail="只有管理员可以重新打开现金快照")
        if period.status != "locked":
            raise HTTPException(status_code=409, detail="只有已确认快照可以重新打开")
        if not (payload.reason or "").strip():
            raise HTTPException(status_code=400, detail="重新打开必须填写原因")
        period.status = "draft"
        period.reopened_at = now
        period.reopened_by = actor
        period.reopen_reason = payload.reason.strip()
    await db.flush()
    await add_cash_audit(db, period, current_user, payload.action, reason=payload.reason)
    await db.commit()
    return await cash_period_payload(db, period)


@router.get("/cash-periods/{year_month}/audit")
async def get_cash_period_audit(
    year_month: str,
    current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ensure_finance_role(current_user)
    year_month = valid_month(year_month)
    period = (
        await db.execute(select(CashPeriod).where(CashPeriod.year_month == year_month))
    ).scalar_one_or_none()
    if not period:
        return []
    rows = (
        await db.execute(
            select(CashAuditLog)
            .where(CashAuditLog.period_id == period.id)
            .order_by(CashAuditLog.id.desc())
            .limit(100)
        )
    ).scalars().all()
    return [{
        "id": row.id,
        "action": row.action,
        "actor_name": row.actor_name,
        "actor_role": row.actor_role,
        "reason": row.reason,
        "created_at": row.created_at,
    } for row in rows]


@router.post("/recommendations/{recommendation_key}/decision")
async def save_recommendation_decision(
    recommendation_key: str,
    payload: RecommendationDecisionInput,
    current_user: UserResponse = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    overview = await build_company_roadmap_overview(db)
    recommendation = overview["recommendation"]
    if recommendation["key"] != recommendation_key:
        raise HTTPException(status_code=409, detail="该建议已随最新数据变化，请刷新后重新处理")
    if payload.status in {"deferred", "rejected"} and not (payload.decision_note or "").strip():
        raise HTTPException(status_code=400, detail="暂缓或不采纳时请填写原因")
    decision = (
        await db.execute(
            select(StrategyRecommendationDecision).where(
                StrategyRecommendationDecision.recommendation_key == recommendation_key
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    task = None
    if payload.create_task and payload.status == "accepted":
        if decision and decision.task_id:
            task = await db.get(Tasks, decision.task_id)
        if not task:
            task = Tasks(
                title=f"【公司里程碑】{recommendation['title']}",
                task_type="management_decision",
                priority="high" if recommendation["level"] == "critical" else "medium",
                status="pending",
                due_date=datetime.combine(payload.next_review_date, datetime.min.time(), tzinfo=timezone.utc) if payload.next_review_date else None,
                notes=f"原因：{recommendation['why']}\n下一步：{recommendation['action']}",
                source_type="company_roadmap",
                created_at=now,
                updated_at=now,
            )
            db.add(task)
            await db.flush()
    values = {
        "title": recommendation["title"],
        "rationale": recommendation["why"],
        "recommended_action": recommendation["action"],
        "status": payload.status,
        "decision_note": (payload.decision_note or "").strip() or None,
        "next_review_date": payload.next_review_date,
        "task_id": task.id if task else decision.task_id if decision else None,
        "decided_by_id": str(current_user.id),
        "decided_by_name": actor_name(current_user),
        "decided_at": now,
    }
    if decision:
        for key, value in values.items():
            setattr(decision, key, value)
    else:
        decision = StrategyRecommendationDecision(recommendation_key=recommendation_key, **values)
        db.add(decision)
    await db.commit()
    return {"message": "经营决策已记录", "status": decision.status, "task_id": decision.task_id}
