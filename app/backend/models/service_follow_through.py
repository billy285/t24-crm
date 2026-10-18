"""Operational follow-through evidence; isolated from financial accounting."""
from core.database import Base
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func


class ServiceRenewalSignal(Base):
    __tablename__ = "service_renewal_signals"
    __table_args__ = (UniqueConstraint("resource_key", name="uq_service_renewal_resource"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    handoff_id = Column(Integer, ForeignKey("sales_deal_handoffs.id", ondelete="RESTRICT"), nullable=False, index=True)
    subscription_id = Column(String(255), nullable=False, index=True)
    resource_key = Column(String(255), nullable=False)
    resource_type = Column(String(24), nullable=False)
    status = Column(String(32), nullable=False)
    amount_minor = Column(Integer)
    currency = Column(String(3))
    due_date = Column(String(10))
    period_end = Column(String(10))
    latest_event_id = Column(String(255), nullable=False)
    latest_event_at = Column(DateTime(timezone=True), nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ServiceRenewalEvent(Base):
    __tablename__ = "service_renewal_events"
    event_id = Column(String(255), primary_key=True)
    signal_id = Column(Integer, ForeignKey("service_renewal_signals.id", ondelete="RESTRICT"), nullable=False)
    event_type = Column(String(80), nullable=False)
    payload_digest = Column(String(64), nullable=False)
    stripe_created_at = Column(DateTime(timezone=True), nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ServiceKickoff(Base):
    __tablename__ = "service_kickoffs"
    handoff_id = Column(Integer, ForeignKey("sales_deal_handoffs.id", ondelete="RESTRICT"), primary_key=True)
    first_delivery_due_date = Column(String(10), nullable=False)
    template_snapshot = Column(JSON, nullable=False)
    revision = Column(Integer, nullable=False)
    items = Column(JSON, nullable=False)
    created_by_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ServiceKickoffAudit(Base):
    __tablename__ = "service_kickoff_audits"
    id = Column(Integer, primary_key=True, autoincrement=True)
    handoff_id = Column(Integer, ForeignKey("service_kickoffs.handoff_id", ondelete="RESTRICT"), nullable=False, index=True)
    item_key = Column(String(80))
    action = Column(String(24), nullable=False)
    actor_id = Column(Integer, nullable=False)
    actor_name = Column(String(255))
    before = Column(JSON)
    after = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
