"""Owner-scoped CNY books stored exclusively in the private database."""
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, Index, Integer, JSON, String, Text, UniqueConstraint

from models.private_workspace import PrivateWorkspaceBase, utcnow


def identity():
    return str(uuid4())


class OwnerRecord:
    id = Column(String(36), primary_key=True, default=identity)
    owner_id = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class PersonalFinanceSettings(PrivateWorkspaceBase):
    __tablename__ = "private_pf_settings"
    owner_id = Column(String(64), primary_key=True)
    initialized = Column(Boolean, nullable=False, default=False)
    budget_minor = Column(BigInteger, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class PersonalCategory(OwnerRecord, PrivateWorkspaceBase):
    __tablename__ = "private_pf_categories"
    __table_args__ = (UniqueConstraint("owner_id", "kind", "normalized_name", name="uq_pf_category_name"),)
    name = Column(String(40), nullable=False)
    normalized_name = Column(String(120), nullable=False)
    kind = Column(String(12), nullable=False)
    icon = Column(String(40), nullable=False, default="circle")
    active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)


class PersonalAccount(OwnerRecord, PrivateWorkspaceBase):
    __tablename__ = "private_pf_accounts"
    __table_args__ = (CheckConstraint("balance_minor >= 0", name="ck_pf_account_nonnegative"),)
    name = Column(String(40), nullable=False)
    kind = Column(String(12), nullable=False)
    currency = Column(String(3), nullable=False, default="CNY")
    opening_balance_minor = Column(BigInteger, nullable=False, default=0)
    balance_minor = Column(BigInteger, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=True)


class PersonalDebt(OwnerRecord, PrivateWorkspaceBase):
    __tablename__ = "private_pf_debts"
    __table_args__ = (CheckConstraint("remaining_minor >= 0 AND remaining_minor <= principal_minor", name="ck_pf_debt_remaining"),)
    name = Column(String(80), nullable=False)
    direction = Column(String(12), nullable=False)
    principal_minor = Column(BigInteger, nullable=False)
    remaining_minor = Column(BigInteger, nullable=False)
    due_date = Column(Date, nullable=True)
    installment_minor = Column(BigInteger, nullable=True)
    note = Column(Text, nullable=False, default="")


class PersonalPlan(OwnerRecord, PrivateWorkspaceBase):
    __tablename__ = "private_pf_plans"
    name = Column(String(80), nullable=False)
    category_id = Column(String(36), nullable=False)
    amount_minor = Column(BigInteger, nullable=False)
    due_date = Column(Date, nullable=False)
    status = Column(String(12), nullable=False, default="pending")
    paid_entry_id = Column(String(36), nullable=True)
    actual_minor = Column(BigInteger, nullable=True)
    paid_date = Column(Date, nullable=True)


class PersonalGoal(OwnerRecord, PrivateWorkspaceBase):
    __tablename__ = "private_pf_goals"
    name = Column(String(80), nullable=False)
    target_minor = Column(BigInteger, nullable=False)
    prepared_minor = Column(BigInteger, nullable=False, default=0)
    target_date = Column(Date, nullable=True)
    active = Column(Boolean, nullable=False, default=True)


class PersonalEntry(OwnerRecord, PrivateWorkspaceBase):
    __tablename__ = "private_pf_entries"
    __table_args__ = (
        UniqueConstraint("owner_id", "client_request_id", name="uq_pf_entry_request"),
        CheckConstraint("amount_minor > 0", name="ck_pf_entry_positive"),
        Index("ix_pf_entry_owner_date", "owner_id", "entry_date", "status"),
    )
    kind = Column(String(12), nullable=False)
    amount_minor = Column(BigInteger, nullable=False)
    account_id = Column(String(36), nullable=False)
    to_account_id = Column(String(36), nullable=True)
    category_id = Column(String(36), nullable=True)
    debt_id = Column(String(36), nullable=True)
    plan_id = Column(String(36), nullable=True)
    counterparty = Column(String(80), nullable=True)
    entry_date = Column(Date, nullable=False)
    note = Column(Text, nullable=False, default="")
    status = Column(String(12), nullable=False, default="active")
    client_request_id = Column(String(36), nullable=False)
    request_hash = Column(String(64), nullable=False)


class PersonalFinanceAudit(OwnerRecord, PrivateWorkspaceBase):
    __tablename__ = "private_pf_audits"
    action = Column(String(32), nullable=False)
    target_id = Column(String(64), nullable=False)
    # Fixed action plus identifiers; never provider credentials or external data.
    detail = Column(Text, nullable=False, default="")


class PersonalFinanceReceipt(OwnerRecord, PrivateWorkspaceBase):
    __tablename__ = "private_pf_receipts"
    __table_args__ = (UniqueConstraint("owner_id", "client_request_id", name="uq_pf_receipt_request"),)
    client_request_id = Column(String(36), nullable=False)
    resource_kind = Column(String(24), nullable=False)
    request_hash = Column(String(64), nullable=False)
    result = Column(JSON, nullable=False)
