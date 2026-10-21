"""Explicit owner authorizations and durable automatic receipt work; no seeds."""
from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, func


class StripeAutoPostingPolicy(Base):
    __tablename__ = "stripe_auto_posting_policies"
    binding_id = Column(Integer, ForeignKey("stripe_history_bindings.id", ondelete="RESTRICT"), primary_key=True)
    enabled = Column(Boolean, nullable=False)
    revision = Column(Integer, nullable=False)
    effective_from = Column(DateTime(timezone=True))
    excluded_through_review_id = Column(Integer, nullable=False)
    authorized_by_id = Column(Integer, nullable=False)
    authorized_by_name = Column(String(255), nullable=False)
    owner_note = Column(String(1000), nullable=False)
    scope_fingerprint = Column(String(64), nullable=False)
    trial = Column(JSON, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StripeAutoPostingJob(Base):
    __tablename__ = "stripe_auto_posting_jobs"
    review_id = Column(Integer, ForeignKey("stripe_history_invoice_reviews.id", ondelete="RESTRICT"), primary_key=True)
    binding_id = Column(Integer, ForeignKey("stripe_history_bindings.id", ondelete="RESTRICT"), nullable=False, index=True)
    policy_revision = Column(Integer, nullable=False)
    authorization_snapshot = Column(JSON, nullable=False)
    status = Column(String(24), nullable=False, index=True)
    reason_code = Column(String(64))
    reason = Column(String(500))
    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="RESTRICT"))
    attempt_count = Column(Integer, nullable=False)
    retry_at = Column(DateTime(timezone=True))
    lease_token = Column(String(64))
    lease_until = Column(DateTime(timezone=True))
    last_attempt_at = Column(DateTime(timezone=True))
    processed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
