"""Opt-in clerk drafts. Only explicit owner confirmation reaches existing ledgers."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import re
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.customers import Customers
from models.finance_entry_drafts import FinanceEntryDraft, FinanceEntryDraftAudit
from models.payments import Payments
from schemas.auth import UserResponse
from services.customer_permissions import customer_permissions_for_rows, get_customer_permissions
from services.customers import CustomersService
from services.schema_readiness import require_tables

KINDS = {"manual_receipt", "customer_expense", "company_expense"}
STATUSES = {"draft", "submitted", "returned", "posted", "voided"}
EDITABLE = {"draft", "returned"}
TABLES = {"finance_entry_drafts", "finance_entry_draft_audits", "finance_entry_attachments"}
MANUAL_METHODS = ("check", "zelle", "apple_cash", "venmo", "wire", "cash", "credit_card", "other")
DOMAIN_LOCK = int.from_bytes(b"T24FENT", "big")


def now():
    return datetime.now(timezone.utc)


def _actor(user):
    if str(user.role or "").lower() not in {"finance", "super_admin"}:
        raise HTTPException(403, "仅财务登记员和老板可访问登记台")
    try:
        identity = int(user.id)
        if identity <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise HTTPException(403, "员工身份无效")
    return identity


def _owner(user):
    _actor(user)
    if user.role != "super_admin":
        raise HTTPException(403, "仅老板可以核对并记入正式账")


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", value):
        raise HTTPException(422, "请提供有效的防重复请求编号")
    return value


def _money(value):
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("金额必须是有限的非负数字")
    if isinstance(value, bool) or not amount.is_finite() or amount < 0 or amount > Decimal("1000000000000"):
        raise ValueError("金额必须是有限的非负数字")
    return float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class DraftPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    currency: Literal["USD"] = "USD"
    notes: str | None = Field(None, max_length=8000)
    evidence_reference: str | None = Field(None, max_length=1000)


class ReceiptPayload(DraftPayload):
    income_type: str | None = Field(None, max_length=100)
    product_name: str | None = Field(None, max_length=500)
    amount_due: float | None = None
    amount_paid: float | None = None
    management_amount: float | None = None
    ads_recharge_amount: float | None = None
    payment_date: datetime | None = None
    payment_method: Literal["check", "zelle", "apple_cash", "venmo", "wire", "cash", "credit_card", "other"] | None = None
    transaction_reference: str | None = Field(None, max_length=500)
    billing_cycle: Literal["monthly", "quarterly", "semi_annual", "annual", "one_time"] | None = None
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    has_invoice: bool = False

    @field_validator("amount_due", "amount_paid", "management_amount", "ads_recharge_amount", mode="before")
    @classmethod
    def money(cls, value):
        return _money(value)

    @field_validator("transaction_reference")
    @classmethod
    def manual_reference(cls, value):
        if value and re.fullmatch(r"(?:in|pi|ch|cs|sub|evt|re)_[A-Za-z0-9]+", value, re.IGNORECASE):
            raise ValueError("Stripe 交易应使用原订阅核对流程")
        return value


class CustomerExpensePayload(DraftPayload):
    currency: Literal["USD", "CNY"] = "USD"
    expense_type: Literal["website_fee", "domain_fee", "hosting_fee", "design_fee", "other"] | None = None
    expense_category: str | None = Field(None, max_length=100)
    amount: float | None = None
    expense_date: datetime | None = None
    expense_month: str | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def money(cls, value):
        return _money(value)

    @field_validator("expense_month")
    @classmethod
    def month(cls, value):
        if value and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
            raise ValueError("费用月份应为 YYYY-MM")
        return value or None


class CompanyExpensePayload(CustomerExpensePayload):
    # Company amounts are entered by the clerk, never read from company ledgers.
    category: str | None = Field(None, max_length=100)
    category_name: str | None = Field(None, max_length=200)


def normalize_payload(kind, payload, *, complete=False):
    if kind not in KINDS or not isinstance(payload, dict):
        raise HTTPException(422, "登记类型或资料格式无效")
    cls = {"manual_receipt": ReceiptPayload, "customer_expense": CustomerExpensePayload, "company_expense": CompanyExpensePayload}[kind]
    if kind == "company_expense" and any(key in payload for key in ("expense_type", "expense_category")):
        raise HTTPException(422, "公司支出不接收客户费用字段")
    try:
        value = cls.model_validate(payload).model_dump(mode="json", exclude_none=True)
    except ValidationError:
        # Never echo arbitrary submitted fields, secrets or ledger payloads.
        raise HTTPException(422, "登记资料包含无效字段、金额、币种或日期，请检查后重试")
    if complete:
        required = ("income_type", "product_name", "amount_due", "amount_paid", "payment_date", "payment_method") if kind == "manual_receipt" else (("expense_type", "amount", "expense_date") if kind == "customer_expense" else ("category", "amount", "expense_date"))
        if any(value.get(field) is None or value.get(field) == "" for field in required):
            raise HTTPException(422, "请补齐金额、日期、收支类型与产品或用途")
    if kind == "manual_receipt":
        amount = value.get("amount_paid", 0)
        management = value.get("management_amount")
        ads = value.get("ads_recharge_amount")
        if management is None and ads is None:
            management = amount if value.get("income_type") == "management_fee" else 0
            ads = amount if value.get("income_type") == "ads_fee" else 0
        else:
            management, ads = management or 0, ads or 0
        if management + ads > amount + 0.01:
            raise HTTPException(422, "管理费金额与投流金额合计不能大于实收金额")
        if complete and value.get("income_type") == "management_ads_mixed" and (management <= 0 or ads <= 0):
            raise HTTPException(422, "管理费加投流费需要同时填写两项正数金额")
        if value.get("coverage_end"):
            if not value.get("coverage_start"):
                raise HTTPException(422, "请填写服务开始日期")
            start = datetime.fromisoformat(value["coverage_start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(value["coverage_end"].replace("Z", "+00:00"))
            start = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start.astimezone(timezone.utc)
            end = end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end.astimezone(timezone.utc)
            if end <= start:
                raise HTTPException(422, "服务结束日期必须晚于开始日期")
    return value


async def _customer(db, user, customer_id, *, for_write=False):
    if not isinstance(customer_id, int) or isinstance(customer_id, bool) or customer_id <= 0:
        raise HTTPException(422, "请选择客户")
    query = select(Customers).where(Customers.id == customer_id).execution_options(populate_existing=True)
    if for_write:
        query = query.with_for_update()
    customer = await db.scalar(query)
    if customer is None:
        raise HTTPException(404, "客户不可访问")
    permissions = await get_customer_permissions(db, user, customer_id)
    if not permissions.get("modules", {}).get("basic", {}).get("read") or permissions.get("finance_access") not in {"receipts", "profit"}:
        raise HTTPException(404, "客户不可访问或尚未获得收款查看授权")
    return customer


async def authorize_draft(db: AsyncSession, user: UserResponse, draft_id: int, for_edit: bool = False) -> FinanceEntryDraft:
    identity = _actor(user)
    await require_tables(db, TABLES)
    draft = await db.get(FinanceEntryDraft, draft_id, populate_existing=True)
    if not draft or (user.role != "super_admin" and draft.created_by_id != identity):
        raise HTTPException(404, "登记草稿不存在")
    if user.role != "super_admin" and draft.kind != "company_expense":
        await _customer(db, user, draft.customer_id, for_write=for_edit)
    if for_edit and (draft.created_by_id != identity or draft.status not in EDITABLE):
        raise HTTPException(409, "仅本人未提交或已退回的草稿可修改")
    return draft


async def _lock(db):
    await require_tables(db, TABLES)
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        await db.execute(text("UPDATE finance_entry_drafts SET id=id WHERE 0"))
    elif dialect == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": DOMAIN_LOCK})


async def _cas(db, draft, revision, **values):
    if not isinstance(revision, int) or isinstance(revision, bool) or revision != draft.revision:
        raise HTTPException(409, "草稿已更新，请刷新后再操作")
    result = await db.execute(update(FinanceEntryDraft).where(FinanceEntryDraft.id == draft.id, FinanceEntryDraft.revision == revision, FinanceEntryDraft.status == draft.status).values(revision=revision + 1, updated_at=now(), **values).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise HTTPException(409, "草稿正在被其他操作处理，请刷新后再试")
    await db.refresh(draft)
    return draft


async def claim_draft(db, user, draft_id, expected_revision: int, for_edit: bool = True) -> FinanceEntryDraft:
    """Claim a revision inside the caller's transaction; never commits (attachments use this)."""
    await _lock(db)
    draft = await authorize_draft(db, user, draft_id, for_edit=for_edit)
    return await _cas(db, draft, expected_revision)


async def append_audit(db, user, draft, action: str, *, before_status: str | None = None, reason: str | None = None, request_id: str | None = None, request_fingerprint: str | None = None):
    audit = FinanceEntryDraftAudit(draft_id=draft.id, revision=draft.revision, action=action, actor_id=_actor(user), actor_name=user.name or str(user.id), before_status=before_status, after_status=draft.status, reason=reason, request_id=request_id, request_fingerprint=request_fingerprint, payload_snapshot=dict(draft.payload), created_at=now())
    db.add(audit)
    await db.flush()
    return audit


class PostingAborted(BaseException):
    """Bypass old handlers' broad Exception catches; the outer transaction must abort."""


class AtomicLedgerSession:
    """One local facade; original financial handlers/services remain untouched."""
    def __init__(self, db):
        self.db, self.poisoned = db, False

    def __getattr__(self, name):
        return getattr(self.db, name)

    async def commit(self):
        if self.poisoned:
            raise PostingAborted()
        await self.db.flush()

    async def rollback(self):
        self.poisoned = True
        raise PostingAborted()


@asynccontextmanager
async def _write(db):
    try:
        await _lock(db)
        yield
        await db.commit()
    except PostingAborted:
        await db.rollback()
        raise HTTPException(409, "正式入账未完成，草稿与账本均未改变，请核对后重试")
    except (IntegrityError, DBAPIError):
        await db.rollback()
        raise HTTPException(409, "登记记录正在被其他操作处理或已存在，请刷新核对后重试")
    except BaseException:
        await db.rollback()
        raise


def draft_data(draft, user):
    value = {field: getattr(draft, field) for field in ("id", "kind", "customer_id", "customer_name", "payload", "status", "revision", "created_by_id", "created_by_name", "return_reason", "submitted_at", "posted_at", "voided_at", "created_at", "updated_at")}
    if user.role == "super_admin":
        value.update(posted_entity=draft.posted_entity, posted_id=draft.posted_id)
    return value


async def customer_options(db, user):
    _actor(user)
    query = select(Customers).order_by(Customers.business_name, Customers.id)
    for module, level in (("basic", "status"), ("finance", "receipts")):
        scope = CustomersService._scope_filter_for_user(user, module=module, finance_level=level)
        if scope is not None:
            query = query.where(scope)
    rows = list((await db.scalars(query)).all())
    permissions = await customer_permissions_for_rows(db, user, rows)
    result = []
    for customer in rows:
        access = permissions[customer.id]
        if access.get("modules", {}).get("basic", {}).get("read") and access.get("finance_access") in {"receipts", "profit"}:
            result.append({"id": customer.id, "business_name": customer.business_name, "customer_code": customer.customer_code})
    return {"items": result}


async def list_drafts(db, user, *, status=None, skip=0, limit=50):
    identity = _actor(user)
    await require_tables(db, TABLES)
    if status is not None and status not in STATUSES:
        raise HTTPException(422, "草稿状态无效")
    clauses = []
    if user.role != "super_admin":
        visible = [item["id"] for item in (await customer_options(db, user))["items"]]
        clauses.extend([FinanceEntryDraft.created_by_id == identity, (FinanceEntryDraft.kind == "company_expense") | FinanceEntryDraft.customer_id.in_(visible)])
    if status:
        clauses.append(FinanceEntryDraft.status == status)
    total = await db.scalar(select(func.count(FinanceEntryDraft.id)).where(*clauses))
    rows = (await db.scalars(select(FinanceEntryDraft).where(*clauses).order_by(FinanceEntryDraft.updated_at.desc(), FinanceEntryDraft.id.desc()).offset(skip).limit(limit))).all()
    return {"items": [draft_data(row, user) for row in rows], "total": total, "skip": skip, "limit": limit}


async def create_draft(db, user, *, client_request_id, kind, customer_id, payload):
    identity, key = _actor(user), _key(client_request_id)
    value = normalize_payload(kind, payload)
    if kind == "company_expense" and customer_id is not None:
        raise HTTPException(422, "公司支出不关联客户")
    async with _write(db):
        customer = None if kind == "company_expense" else await _customer(db, user, customer_id, for_write=True)
        fingerprint = _hash({"kind": kind, "customer_id": customer_id, "payload": value})
        previous = await db.scalar(select(FinanceEntryDraft).where(FinanceEntryDraft.created_by_id == identity, FinanceEntryDraft.client_request_id == key))
        if previous:
            await authorize_draft(db, user, previous.id)
            if previous.creation_fingerprint != fingerprint:
                raise HTTPException(409, "请求编号已经用于其他登记内容")
            return draft_data(previous, user)
        row = FinanceEntryDraft(kind=kind, customer_id=customer_id, customer_name=customer.business_name if customer else None, created_by_id=identity, created_by_name=user.name or str(user.id), client_request_id=key, creation_fingerprint=fingerprint, payload=value, status="draft", revision=1, created_at=now(), updated_at=now())
        db.add(row)
        await db.flush()
        await append_audit(db, user, row, "created", request_id=key, request_fingerprint=fingerprint)
        result = draft_data(row, user)
    return result


async def edit_draft(db, user, draft_id, *, expected_revision, payload):
    async with _write(db):
        row = await authorize_draft(db, user, draft_id, for_edit=True)
        value = normalize_payload(row.kind, payload)
        before = row.status
        await _cas(db, row, expected_revision, payload=value)
        await append_audit(db, user, row, "edited", before_status=before)
        result = draft_data(row, user)
    return result


async def _has_evidence(db, draft):
    if len(str(draft.payload.get("evidence_reference") or "").strip()) >= 3:
        return True
    try:
        from services.finance_entry_attachments import has_active_attachment
    except ImportError:
        return False
    return await has_active_attachment(db, draft.id)


async def _replay(db, row, request_id, action, fingerprint):
    prior = await db.scalar(select(FinanceEntryDraftAudit).where(FinanceEntryDraftAudit.draft_id == row.id, FinanceEntryDraftAudit.request_id == request_id))
    if prior:
        if prior.action != action or prior.request_fingerprint != fingerprint:
            raise HTTPException(409, "请求编号已用于其他操作")
        return True
    return False


async def _post_ledger(db, owner, row):
    # Reuse the existing, complete financial path, including existing period locks.
    facade = AtomicLedgerSession(db)
    if row.kind != "company_expense":
        customer = await _customer(db, owner, row.customer_id, for_write=True)
        row.customer_name = customer.business_name
    value = normalize_payload(row.kind, row.payload, complete=True)
    value.pop("evidence_reference", None)
    if row.kind == "manual_receipt":
        from routers.payments import PaymentsData, create_payments
        paid = value["amount_paid"]
        management, ads = value.get("management_amount"), value.get("ads_recharge_amount")
        if management is None and ads is None:
            management = paid if value["income_type"] == "management_fee" else 0
            ads = paid if value["income_type"] == "ads_fee" else 0
        management, ads = management or 0, ads or 0
        reference = str(value.get("transaction_reference") or "").strip()
        if reference:
            duplicate = await db.scalar(select(Payments.id).where(Payments.customer_id == row.customer_id, Payments.payment_method == value["payment_method"], func.lower(func.trim(Payments.transaction_reference)) == reference.lower()).limit(1))
            if duplicate:
                raise HTTPException(409, "这位客户的相同付款方式及交易凭据已有正式收款，请在原账本核对，避免重复入账")
        value.update(customer_id=row.customer_id, customer_name=row.customer_name, management_amount=management, ads_recharge_amount=ads, income_type="management_ads_mixed" if management > 0 and ads > 0 else value["income_type"], payment_mode="manual_collection", stripe_fee_amount=0, net_amount=paid, outstanding_amount=max(round(value["amount_due"] - paid, 2), 0), expense_month=value["payment_date"][:7], recorded_by=row.created_by_name, sync_to_deal=False)
        ledger = await create_payments(PaymentsData.model_validate(value), current_user=owner, db=facade)
        entity = "payments"
    elif row.kind == "customer_expense":
        from routers.expenses import ExpensesData, create_expenses
        value.update(customer_id=row.customer_id, customer_name=row.customer_name, recorded_by=row.created_by_name)
        ledger = await create_expenses(ExpensesData.model_validate(value), current_user=owner, db=facade)
        entity = "expenses"
    else:
        from routers.company_expenses import Company_expensesData, create_company_expenses
        value.update(recorded_by=row.created_by_name)
        ledger = await create_company_expenses(Company_expensesData.model_validate(value), current_user=owner, db=facade)
        entity = "company_expenses"
    if facade.poisoned or not ledger or not isinstance(ledger.id, int) or isinstance(ledger.id, bool) or ledger.id <= 0:
        raise PostingAborted()
    return entity, ledger.id


async def transition_draft(db, user, draft_id, *, expected_revision, request_id, action, reason=None):
    _actor(user)
    key = _key(request_id)
    if action not in {"submit", "return", "void", "post"}:
        raise HTTPException(422, "登记操作无效")
    if action != "submit":
        _owner(user)
    if action in {"return", "void"} and not 3 <= len(str(reason or "").strip()) <= 1000:
        raise HTTPException(422, "请填写至少3个字的处理原因")
    fingerprint = _hash({"action": action, "revision": expected_revision, "reason": reason})
    async with _write(db):
        row = await authorize_draft(db, user, draft_id)
        if await _replay(db, row, key, action, fingerprint):
            return draft_data(row, user)
        if action == "submit":
            await authorize_draft(db, user, draft_id, for_edit=True)
            normalize_payload(row.kind, row.payload, complete=True)
            if not await _has_evidence(db, row):
                raise HTTPException(422, "请添加有效凭据附件，或填写至少3个字的凭据说明/编号")
        elif row.status == "posted" or row.status == "voided" or (action in {"return", "post"} and row.status != "submitted"):
            raise HTTPException(409, "当前草稿状态不允许此操作")
        before = row.status
        target = {"submit": "submitted", "return": "returned", "void": "voided", "post": "posted"}[action]
        await _cas(db, row, expected_revision)
        if action == "post":
            if not await _has_evidence(db, row):
                raise HTTPException(409, "凭据已失效，请退回登记员补充后再核对")
            row.posted_entity, row.posted_id = await _post_ledger(db, user, row)
            row.posted_at = now()
        if action == "submit":
            row.submitted_at = now()
        if action == "void":
            row.voided_at = now()
        row.status = target
        row.return_reason = reason.strip() if reason else None
        await db.flush()
        await append_audit(db, user, row, action, before_status=before, reason=row.return_reason, request_id=key, request_fingerprint=fingerprint)
        result = draft_data(row, user)
    return result
