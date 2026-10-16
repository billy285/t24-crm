"""External payment observations and reconciliation proof; never the CRM ledger."""
from core.database import Base
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, func


class SalesPaymentRequest(Base):
    __tablename__ = "sales_payment_requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    handoff_id = Column(Integer, ForeignKey("sales_deal_handoffs.id", ondelete="RESTRICT"), nullable=False, unique=True)
    reference = Column(String(80), nullable=False, unique=True)
    link_snapshot = Column(JSON, nullable=False)
    created_by_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SalesStripeObservation(Base):
    __tablename__ = "sales_stripe_observations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(Integer, ForeignKey("sales_payment_requests.id", ondelete="RESTRICT"), nullable=False, index=True)
    session_id = Column(String(255), nullable=False, unique=True)
    subscription_id = Column(String(255), index=True)
    invoice_id = Column(String(255), index=True)
    payment_intent_id = Column(String(255), index=True)
    status = Column(String(32), nullable=False)
    match_issues = Column(JSON, nullable=False)
    service_minor = Column(Integer)
    tax_minor = Column(Integer)
    gross_minor = Column(Integer)
    currency = Column(String(3))
    payer_business_name = Column(String(255))
    payer_name = Column(String(255))
    payer_email = Column(String(320))
    stripe_created_at = Column(DateTime(timezone=True))
    checkout_completed_at = Column(DateTime(timezone=True))
    paid_at = Column(DateTime(timezone=True))
    latest_event_at = Column(DateTime(timezone=True), nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SalesStripeEvent(Base):
    __tablename__ = "sales_stripe_events"
    event_id = Column(String(255), primary_key=True)
    observation_id = Column(Integer, ForeignKey("sales_stripe_observations.id", ondelete="RESTRICT"), nullable=False)
    event_type = Column(String(80), nullable=False)
    payload_digest = Column(String(64), nullable=False)
    stripe_created_at = Column(DateTime(timezone=True), nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SalesReceiptEvidence(Base):
    __tablename__ = "sales_receipt_evidence"
    id = Column(Integer, primary_key=True, autoincrement=True)
    handoff_id = Column(Integer, ForeignKey("sales_deal_handoffs.id", ondelete="RESTRICT"), nullable=False, unique=True)
    observation_id = Column(Integer, ForeignKey("sales_stripe_observations.id", ondelete="RESTRICT"), unique=True)
    transaction_reference_digest = Column(String(64), nullable=False, unique=True)
    service_minor = Column(Integer, nullable=False)
    tax_minor = Column(Integer, nullable=False)
    fee_minor = Column(Integer, nullable=False)
    gross_minor = Column(Integer, nullable=False)
    net_minor = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False)
    payment_date = Column(String(10), nullable=False)
    verified_by_id = Column(Integer, nullable=False)
    verified_by_name = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
