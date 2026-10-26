"""Separate opt-in registration drafts; these are never financial ledger rows."""
from core.database import Base
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func


class FinanceEntryDraft(Base):
    __tablename__ = "finance_entry_drafts"
    __table_args__ = (
        UniqueConstraint("created_by_id", "client_request_id", name="uq_finance_entry_draft_create_request"),
        UniqueConstraint("posted_entity", "posted_id", name="uq_finance_entry_draft_ledger"),
        CheckConstraint("revision >= 1", name="ck_finance_entry_draft_revision"),
        CheckConstraint("status IN ('draft','submitted','returned','posted','voided')", name="ck_finance_entry_draft_status"),
        CheckConstraint("kind IN ('manual_receipt','customer_expense','company_expense')", name="ck_finance_entry_draft_kind"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Deliberately retain historical drafts after a customer/employee is removed.
    customer_id = Column(Integer, nullable=True, index=True)
    customer_name = Column(String(255), nullable=True)
    kind = Column(String(32), nullable=False)
    created_by_id = Column(Integer, nullable=False, index=True)
    created_by_name = Column(String(255), nullable=False)
    client_request_id = Column(String(64), nullable=False)
    creation_fingerprint = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String(16), nullable=False, default="draft", server_default="draft", index=True)
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    return_reason = Column(Text, nullable=True)
    posted_entity = Column(String(32), nullable=True)
    posted_id = Column(Integer, nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    posted_at = Column(DateTime(timezone=True), nullable=True)
    voided_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FinanceEntryDraftAudit(Base):
    __tablename__ = "finance_entry_draft_audits"
    __table_args__ = (
        UniqueConstraint("draft_id", "revision", name="uq_finance_entry_draft_audit_revision"),
        UniqueConstraint("draft_id", "request_id", name="uq_finance_entry_draft_audit_request"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    draft_id = Column(Integer, ForeignKey("finance_entry_drafts.id", ondelete="RESTRICT"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    action = Column(String(24), nullable=False)
    actor_id = Column(Integer, nullable=False)
    actor_name = Column(String(255), nullable=False)
    before_status = Column(String(16), nullable=True)
    after_status = Column(String(16), nullable=False)
    request_id = Column(String(64), nullable=True)
    request_fingerprint = Column(String(64), nullable=True)
    reason = Column(Text, nullable=True)
    payload_snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
