"""Owner-approved Stripe history identities and draft evidence, separate from ledger."""
from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func


class StripeHistoryPreview(Base):
    __tablename__ = "stripe_history_previews"
    token = Column(String(64), primary_key=True)
    actor_id = Column(Integer, nullable=False)
    snapshot = Column(JSON, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    binding_id = Column(Integer)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StripeHistoryBinding(Base):
    __tablename__ = "stripe_history_bindings"
    __table_args__ = (UniqueConstraint("account_id", "livemode", "stripe_subscription_id", name="uq_history_provider_subscription"),
        UniqueConstraint("crm_subscription_id", name="uq_history_crm_service"))
    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(255), nullable=False)
    livemode = Column(Boolean, nullable=False)
    stripe_subscription_id = Column(String(255), nullable=False)
    stripe_customer_id = Column(String(255), nullable=False)
    crm_subscription_id = Column(Integer, ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    crm_snapshot = Column(JSON, nullable=False)
    price_snapshot = Column(JSON, nullable=False)
    income_type = Column(String(32), nullable=False)
    sync_from = Column(String(10), nullable=False)
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    needs_refresh = Column(Boolean, nullable=False)
    pilot_evidence = Column(JSON, nullable=False)
    pilot_validated = Column(Boolean, nullable=False)
    verified_by_id = Column(Integer, nullable=False)
    verified_by_name = Column(String(255))
    last_synced_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StripeHistoryInvoiceReview(Base):
    __tablename__ = "stripe_history_invoice_reviews"
    __table_args__ = (UniqueConstraint("account_id", "livemode", "stripe_invoice_id", name="uq_history_provider_invoice"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String(255), nullable=False)
    livemode = Column(Boolean, nullable=False)
    stripe_invoice_id = Column(String(255), nullable=False)
    binding_id = Column(Integer, ForeignKey("stripe_history_bindings.id", ondelete="RESTRICT"), nullable=False, index=True)
    status = Column(String(24), nullable=False)
    snapshot = Column(JSON, nullable=False)
    fingerprint = Column(String(64), nullable=False)
    revision = Column(Integer, nullable=False)
    needs_refresh = Column(Boolean, nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StripeHistoryPosting(Base):
    __tablename__ = "stripe_history_postings"
    __table_args__ = (UniqueConstraint("account_id", "livemode", "stripe_charge_id", name="uq_history_cash_charge"),
        UniqueConstraint("payment_id", name="uq_history_posted_payment"))
    review_id = Column(Integer, ForeignKey("stripe_history_invoice_reviews.id", ondelete="RESTRICT"), primary_key=True)
    account_id = Column(String(255), nullable=False)
    livemode = Column(Boolean, nullable=False)
    stripe_charge_id = Column(String(255), nullable=False)
    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False)
    action = Column(String(24), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    verified_by_id = Column(Integer, nullable=False)
    verified_by_name = Column(String(255))
    verification_note = Column(String(2000), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StripeHistoryEvent(Base):
    __tablename__ = "stripe_history_events"
    event_id = Column(String(255), primary_key=True)
    binding_id = Column(Integer, ForeignKey("stripe_history_bindings.id", ondelete="RESTRICT"), nullable=False)
    event_type = Column(String(80), nullable=False)
    resource_key = Column(String(255), nullable=False)
    signal_status = Column(String(32), nullable=False)
    details = Column(JSON, nullable=False)
    payload_digest = Column(String(64), nullable=False)
    stripe_created_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StripeHistoryAudit(Base):
    __tablename__ = "stripe_history_audits"
    id = Column(Integer, primary_key=True, autoincrement=True)
    binding_id = Column(Integer, ForeignKey("stripe_history_bindings.id", ondelete="RESTRICT"))
    review_id = Column(Integer, ForeignKey("stripe_history_invoice_reviews.id", ondelete="RESTRICT"))
    actor_id = Column(Integer, nullable=False)
    actor_name = Column(String(255))
    action = Column(String(32), nullable=False)
    details = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StripeHistoryPolicy(Base):
    __tablename__ = "stripe_history_policy"
    id = Column(Integer, primary_key=True)
    bulk_enabled = Column(Boolean, nullable=False)
    validated_binding_ids = Column(JSON, nullable=False)
    verified_by_id = Column(Integer, nullable=False)
    verification_note = Column(String(2000), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
