from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
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
POTENTIAL_FULL_ACCOUNT_NUMBER = re.compile(r"(?:\d[\s./-]*){7,}")


def looks_like_full_account_number(value: Optional[str]) -> bool:
    """Reject 7+ digits even when separated by spaces or hyphens."""
    if not value:
        return False
    return any(sum(character.isdigit() for character in match.group(0)) >= 7
               for match in POTENTIAL_FULL_ACCOUNT_NUMBER.finditer(value))


def decimal_money(value: object) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


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


def account_input_matches(row: CashAccount, payload: "CashAccountInput") -> bool:
    return (
        row.name.strip().casefold() == payload.name.casefold()
        and row.account_type == payload.account_type
        and row.currency == payload.currency
        and (row.masked_identifier or None) == payload.masked_identifier
        and bool(row.is_active) == payload.is_active
        and int(row.sort_order or 0) == payload.sort_order
        and (row.notes or None) == payload.notes
    )


async def find_active_account_name_conflict(
    db: AsyncSession,
    *,
    name: str,
    currency: str,
    exclude_id: Optional[int] = None,
) -> Optional[CashAccount]:
    rows = (
        await db.execute(
            select(CashAccount).where(
                CashAccount.currency == currency,
                CashAccount.is_active.is_(True),
            )
        )
    ).scalars().all()
    normalized = name.strip().casefold()
    return next(
        (row for row in rows if row.id != exclude_id and row.name.strip().casefold() == normalized),
        None,
    )


async def attach_period_integrity_fields(db: AsyncSession, payload: Optional[dict]) -> Optional[dict]:
    """Add optimistic-lock and immutable account metadata without changing the shared overview service."""
    if not payload:
        return payload
    period_id = int(payload["id"])
    period = await db.get(CashPeriod, period_id)
    if period:
        payload["version"] = int(period.version or 1)
    balance_rows = (
        await db.execute(select(CashAccountBalance).where(CashAccountBalance.period_id == period_id))
    ).scalars().all()
    row_by_id = {int(row.id): row for row in balance_rows}
    for item in payload.get("balances", []):
        row = row_by_id.get(int(item["id"]))
        if not row:
            continue
        item["account_name"] = row.account_name or item.get("account_name")
        item["account_type"] = row.account_type or item.get("account_type")
        item["masked_identifier"] = (
            row.masked_identifier if row.masked_identifier is not None else item.get("masked_identifier")
        )
        item["confirmed_zero"] = bool(row.confirmed_zero)
    return payload


async def stable_cash_period_payload(db: AsyncSession, period: CashPeriod) -> dict:
    payload = await cash_period_payload(db, period)
    return await attach_period_integrity_fields(db, payload) or payload


async def active_account_rows(db: AsyncSession) -> list[CashAccount]:
    return list((
        await db.execute(
            select(CashAccount)
            .where(CashAccount.is_active.is_(True))
            .order_by(CashAccount.sort_order, CashAccount.id)
        )
    ).scalars().all())


def missing_account_message(accounts: list[CashAccount]) -> str:
    names = "、".join(row.name for row in accounts[:8])
    suffix = "等" if len(accounts) > 8 else ""
    return f"还有 {len(accounts)} 个活跃账户未填写余额：{names}{suffix}"


async def system_restriction_changes(db: AsyncSession, period: CashPeriod) -> list[str]:
    latest = await build_restriction_suggestions(db, float(period.usd_cny_rate))
    latest_by_ref = {str(row["source_ref"]): row for row in latest if row.get("source_ref")}
    recorded_rows = (
        await db.execute(select(CashRestriction).where(CashRestriction.period_id == period.id))
    ).scalars().all()
    recorded_by_ref = {
        str(row.source_ref): row
        for row in recorded_rows
        if row.source_ref and str(row.source_ref).startswith("system:")
    }
    changes: list[str] = []
    for source_ref, suggestion in latest_by_ref.items():
        recorded = recorded_by_ref.get(source_ref)
        if not recorded:
            changes.append(f"{suggestion['category_label']}尚未加入")
            continue
        if (
            str(recorded.currency or "").upper() != str(suggestion["currency"]).upper()
            or decimal_money(recorded.amount) != decimal_money(suggestion["amount"])
        ):
            changes.append(
                f"{suggestion['category_label']}已从 {recorded.currency} {decimal_money(recorded.amount)} "
                f"变化为 {suggestion['currency']} {decimal_money(suggestion['amount'])}"
            )
    for source_ref, recorded in recorded_by_ref.items():
        if source_ref not in latest_by_ref:
            changes.append(f"{RESTRICTION_LABELS.get(recorded.category, recorded.category)}已不在最新系统建议中")
    return changes


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

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("账户名称不能为空")
        return value

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

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: Optional[str]) -> Optional[str]:
        return (value or "").strip() or None

    @model_validator(mode="after")
    def reject_sensitive_account_numbers(self):
        for label, value in (
            ("账户名称", self.name),
            ("脱敏末位", self.masked_identifier),
            ("备注", self.notes),
        ):
            if looks_like_full_account_number(value):
                raise ValueError(f"{label}疑似包含完整银行卡号，只允许保存账户简称和最多 6 位末号")
        return self


class BalanceInput(BaseModel):
    account_id: int = Field(ge=1)
    balance: Optional[float] = Field(None, ge=0, le=10_000_000_000)
    confirmed_zero: bool = False

    @model_validator(mode="after")
    def require_value_or_confirmed_zero(self):
        if self.balance is None and not self.confirmed_zero:
            raise ValueError("账户余额未填写；零余额必须明确确认")
        if self.confirmed_zero and self.balance not in (None, 0, 0.0):
            raise ValueError("只有零余额可以标记为已确认零余额")
        if self.balance == 0 and not self.confirmed_zero:
            raise ValueError("零余额必须明确确认")
        return self

    @property
    def effective_balance(self) -> float:
        return float(self.balance or 0)


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
    version: int = Field(ge=0)
    snapshot_date: date
    usd_cny_rate: float = Field(gt=0.1, lt=20)
    notes: Optional[str] = Field(None, max_length=2000)
    balances: list[BalanceInput] = Field(default_factory=list, max_length=100)
    restrictions: list[RestrictionInput] = Field(default_factory=list, max_length=300)


class CashPeriodTransition(BaseModel):
    action: Literal["lock", "reopen"]
    version: int = Field(ge=1)
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
    overview = await build_company_roadmap_overview(db, selected_month=month)
    await attach_period_integrity_fields(db, overview.get("cash_period"))
    return overview


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
    conflict = await find_active_account_name_conflict(
        db,
        name=payload.name,
        currency=payload.currency,
    ) if payload.is_active else None
    if conflict:
        if account_input_matches(conflict, payload):
            return {
                "id": conflict.id,
                "account": cash_account_payload(conflict),
                "message": "相同现金账户已存在，已直接返回原账户",
                "idempotent_replay": True,
            }
        raise HTTPException(
            status_code=409,
            detail="同币种下已有相同名称的活跃账户，请编辑原账户或使用更明确的脱敏名称",
        )
    row = CashAccount(**payload.model_dump(), created_by=actor_name(current_user))
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        conflict = await find_active_account_name_conflict(
            db,
            name=payload.name,
            currency=payload.currency,
        )
        if conflict and account_input_matches(conflict, payload):
            return {
                "id": conflict.id,
                "account": cash_account_payload(conflict),
                "message": "相同现金账户已存在，已直接返回原账户",
                "idempotent_replay": True,
            }
        raise HTTPException(
            status_code=409,
            detail="同币种下已有相同名称的活跃账户，请编辑原账户或使用更明确的脱敏名称",
        ) from exc
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
    if row.currency != payload.currency:
        referenced = (
            await db.execute(
                select(CashAccountBalance.id)
                .where(CashAccountBalance.account_id == account_id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if referenced is not None:
            raise HTTPException(
                status_code=409,
                detail="该账户已有现金快照，币种不能修改；请停用原账户并新增正确币种账户",
            )
    if payload.is_active:
        conflict = await find_active_account_name_conflict(
            db,
            name=payload.name,
            currency=payload.currency,
            exclude_id=account_id,
        )
        if conflict:
            raise HTTPException(
                status_code=409,
                detail="同币种下已有相同名称的活跃账户，请使用更明确的脱敏名称",
            )
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="同币种下已有相同名称的活跃账户，请使用更明确的脱敏名称",
        ) from exc
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
    today = date.today()
    if year_month > today.strftime("%Y-%m"):
        raise HTTPException(status_code=400, detail="不能建立未来月份的现金快照")
    if payload.snapshot_date > today:
        raise HTTPException(status_code=400, detail="现金快照日期不能晚于今天")
    if payload.snapshot_date.strftime("%Y-%m") != year_month:
        raise HTTPException(status_code=400, detail="快照日期必须属于所选月份")
    period = (
        await db.execute(select(CashPeriod).where(CashPeriod.year_month == year_month))
    ).scalar_one_or_none()
    if period and period.status == "locked":
        raise HTTPException(status_code=409, detail="已确认的现金快照已锁定，请先填写原因重新打开")
    if period and int(period.version or 1) != payload.version:
        raise HTTPException(status_code=409, detail="现金快照已被其他人更新，请刷新后再保存")
    if not period and payload.version != 0:
        raise HTTPException(status_code=409, detail="现金快照版本已变化，请刷新后再保存")
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
    active_accounts = await active_account_rows(db)
    missing_accounts = [row for row in active_accounts if int(row.id) not in account_by_id]
    if missing_accounts:
        raise HTTPException(status_code=400, detail=missing_account_message(missing_accounts))
    source_refs = [item.source_ref for item in payload.restrictions if item.source_ref]
    if len(source_refs) != len(set(source_refs)):
        raise HTTPException(status_code=400, detail="同一个系统建议不能重复加入")

    if not period:
        period = CashPeriod(
            year_month=year_month,
            version=1,
            snapshot_date=payload.snapshot_date,
            status="draft",
            usd_cny_rate=payload.usd_cny_rate,
            notes=payload.notes,
            created_by=actor_name(current_user),
        )
        db.add(period)
        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(status_code=409, detail="现金快照已由其他人建立，请刷新后再保存") from exc
    else:
        claimed = await db.execute(
            update(CashPeriod)
            .where(
                CashPeriod.id == period.id,
                CashPeriod.status == "draft",
                CashPeriod.version == payload.version,
            )
            .values(
                snapshot_date=payload.snapshot_date,
                usd_cny_rate=payload.usd_cny_rate,
                notes=payload.notes,
                version=CashPeriod.version + 1,
                updated_at=datetime.now(timezone.utc),
            )
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            await db.rollback()
            raise HTTPException(status_code=409, detail="现金快照已被锁定或更新，请刷新后再保存")
        await db.refresh(period)

    await db.execute(delete(CashAccountBalance).where(CashAccountBalance.period_id == period.id))
    await db.execute(delete(CashRestriction).where(CashRestriction.period_id == period.id))
    await db.flush()
    for item in payload.balances:
        account = account_by_id[item.account_id]
        rate = payload.usd_cny_rate if account.currency == "USD" else 1.0
        balance = item.effective_balance
        db.add(CashAccountBalance(
            period_id=period.id,
            account_id=account.id,
            account_name=account.name,
            account_type=account.account_type,
            masked_identifier=account.masked_identifier,
            currency=account.currency,
            balance=balance,
            confirmed_zero=bool(item.confirmed_zero),
            rate_to_cny=rate,
            balance_cny=round(balance * rate, 2),
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
    await db.refresh(period)
    return await stable_cash_period_payload(db, period)


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
    if int(period.version or 1) != payload.version:
        raise HTTPException(status_code=409, detail="现金快照已被其他人更新，请刷新后再操作")
    now = datetime.now(timezone.utc)
    actor = actor_name(current_user)
    if payload.action == "lock":
        if period.status == "locked":
            return await stable_cash_period_payload(db, period)
        balance_rows = list((await db.execute(
            select(CashAccountBalance).where(CashAccountBalance.period_id == period.id)
        )).scalars().all())
        if not balance_rows:
            raise HTTPException(status_code=409, detail="至少录入一个账户余额后才能确认")
        balance_by_account = {int(row.account_id): row for row in balance_rows}
        missing_accounts = [row for row in await active_account_rows(db) if int(row.id) not in balance_by_account]
        if missing_accounts:
            raise HTTPException(status_code=409, detail=missing_account_message(missing_accounts))
        unconfirmed_zero = [
            row for row in balance_rows
            if decimal_money(row.balance) == Decimal("0.00") and not bool(row.confirmed_zero)
        ]
        if unconfirmed_zero:
            raise HTTPException(status_code=409, detail="存在尚未明确确认的零余额账户，请重新保存后再锁定")
        if year_month == date.today().strftime("%Y-%m"):
            restriction_changes = await system_restriction_changes(db, period)
            if restriction_changes:
                raise HTTPException(
                    status_code=409,
                    detail="系统受限资金建议已变化，请重新核对后再确认：" + "；".join(restriction_changes),
                )
        expected_status = "draft"
        values = {
            "status": "locked",
            "locked_at": now,
            "locked_by": actor,
            "version": CashPeriod.version + 1,
            "updated_at": now,
        }
    else:
        if role not in {"admin", "super_admin"}:
            raise HTTPException(status_code=403, detail="只有管理员可以重新打开现金快照")
        if period.status != "locked":
            raise HTTPException(status_code=409, detail="只有已确认快照可以重新打开")
        if not (payload.reason or "").strip():
            raise HTTPException(status_code=400, detail="重新打开必须填写原因")
        expected_status = "locked"
        values = {
            "status": "draft",
            "reopened_at": now,
            "reopened_by": actor,
            "reopen_reason": payload.reason.strip(),
            "version": CashPeriod.version + 1,
            "updated_at": now,
        }
    transitioned = await db.execute(
        update(CashPeriod)
        .where(
            CashPeriod.id == period.id,
            CashPeriod.status == expected_status,
            CashPeriod.version == payload.version,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if transitioned.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="现金快照已被其他人更新，请刷新后再操作")
    await db.refresh(period)
    await add_cash_audit(db, period, current_user, payload.action, reason=payload.reason)
    await db.commit()
    await db.refresh(period)
    return await stable_cash_period_payload(db, period)


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
    decision_note = (payload.decision_note or "").strip()
    if payload.status in {"deferred", "rejected"} and not decision_note:
        raise HTTPException(status_code=400, detail="暂缓或不采纳时请填写原因")
    decision = (
        await db.execute(
            select(StrategyRecommendationDecision).where(
                StrategyRecommendationDecision.recommendation_key == recommendation_key
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    task = await db.get(Tasks, decision.task_id) if decision and decision.task_id else None
    if payload.status == "completed" and task and not decision_note:
        raise HTTPException(status_code=400, detail="完成有关联任务的经营决策时，请填写处理结果")
    if payload.create_task and payload.status == "accepted":
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

    if task:
        previous_status = str(task.status or "").lower()
        if payload.status == "completed":
            task.status = "completed"
            # A task result may have been entered through the task workbench.
            # Preserve that audit evidence instead of silently replacing it.
            if not str(task.completion_result or "").strip():
                task.completion_result = decision_note
            if previous_status != "completed" or not task.completed_at:
                task.completed_at = now
        elif payload.status == "accepted":
            if previous_status in {"completed", "cancelled"} or not previous_status:
                task.status = "pending"
                task.completed_at = None
            if payload.next_review_date:
                task.due_date = datetime.combine(
                    payload.next_review_date,
                    datetime.min.time(),
                    tzinfo=timezone.utc,
                )
        elif payload.status in {"deferred", "rejected"} and previous_status not in {"completed", "cancelled"}:
            task.status = "cancelled"
            task.completed_at = None
        task.updated_at = now

    values = {
        "title": recommendation["title"],
        "rationale": recommendation["why"],
        "recommended_action": recommendation["action"],
        "status": payload.status,
        "decision_note": decision_note or None,
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
    return {
        "message": "经营决策已记录",
        "status": decision.status,
        "task_id": decision.task_id,
        "task_status": task.status if task else None,
    }
