from core.database import Base
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)


class SalesPartner(Base):
    __tablename__ = "sales_partners"
    __table_args__ = (UniqueConstraint("partner_code", name="uq_sales_partners_code"), {"extend_existing": True})

    id = Column(Integer, primary_key=True, autoincrement=True)
    partner_code = Column(String(48), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    partner_type = Column(String(24), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(24), nullable=False, default="active", index=True)
    joined_at = Column(Date, nullable=False)
    stopped_at = Column(Date, nullable=True, index=True)
    contact_name = Column(String(120), nullable=True)
    contact_phone = Column(String(64), nullable=True)
    contact_email = Column(String(160), nullable=True)
    notes = Column(Text, nullable=True)
    created_by_id = Column(String(64), nullable=True)
    created_by_name = Column(String(160), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CommissionAgreement(Base):
    __tablename__ = "commission_agreements"
    __table_args__ = (
        UniqueConstraint("partner_id", "version", name="uq_commission_agreements_partner_version"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    partner_id = Column(Integer, ForeignKey("sales_partners.id", ondelete="RESTRICT"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    business_line_id = Column(Integer, ForeignKey("business_lines.id", ondelete="RESTRICT"), nullable=True, index=True)
    product_id = Column(Integer, ForeignKey("product_catalog.id", ondelete="RESTRICT"), nullable=True, index=True)
    first_order_rate = Column(Float, nullable=False)
    renewal_rate = Column(Float, nullable=False)
    activity_decay_json = Column(Text, nullable=False)
    refund_guard_days = Column(Integer, nullable=False, default=30)
    effective_from = Column(Date, nullable=False, index=True)
    effective_to = Column(Date, nullable=True, index=True)
    status = Column(String(24), nullable=False, default="active", index=True)
    notes = Column(Text, nullable=True)
    created_by_id = Column(String(64), nullable=True)
    created_by_name = Column(String(160), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CustomerCommissionAttribution(Base):
    __tablename__ = "customer_commission_attributions"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    engagement_id = Column(Integer, ForeignKey("customer_engagements.id", ondelete="SET NULL"), nullable=True, index=True)
    partner_id = Column(Integer, ForeignKey("sales_partners.id", ondelete="RESTRICT"), nullable=False, index=True)
    attribution_role = Column(String(24), nullable=False, default="primary", index=True)
    effective_from = Column(Date, nullable=False, index=True)
    effective_to = Column(Date, nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    source_note = Column(Text, nullable=True)
    created_by_id = Column(String(64), nullable=True)
    created_by_name = Column(String(160), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CommissionEntry(Base):
    __tablename__ = "commission_entries"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_commission_entries_idempotency"), {"extend_existing": True})

    id = Column(Integer, primary_key=True, autoincrement=True)
    partner_id = Column(Integer, ForeignKey("sales_partners.id", ondelete="RESTRICT"), nullable=False, index=True)
    agreement_id = Column(Integer, ForeignKey("commission_agreements.id", ondelete="RESTRICT"), nullable=False, index=True)
    attribution_id = Column(Integer, ForeignKey("customer_commission_attributions.id", ondelete="RESTRICT"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    engagement_id = Column(Integer, ForeignKey("customer_engagements.id", ondelete="SET NULL"), nullable=True, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False, index=True)
    refund_id = Column(Integer, ForeignKey("finance_refunds.id", ondelete="RESTRICT"), nullable=True, index=True)
    original_entry_id = Column(Integer, ForeignKey("commission_entries.id", ondelete="RESTRICT"), nullable=True, index=True)
    entry_type = Column(String(32), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="estimated", index=True)
    service_month = Column(String(7), nullable=False, index=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False, index=True)
    currency = Column(String(3), nullable=False, index=True)
    gross_receipt_amount = Column(Float, nullable=False)
    eligible_service_amount = Column(Float, nullable=False)
    contract_rate = Column(Float, nullable=False)
    inactivity_months = Column(Integer, nullable=False, default=0)
    activity_multiplier = Column(Float, nullable=False, default=1)
    commission_amount = Column(Float, nullable=False)
    snapshot_json = Column(Text, nullable=False)
    idempotency_key = Column(String(180), nullable=False, index=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    payable_at = Column(DateTime(timezone=True), nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    payout_reference = Column(String(160), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CommissionStatusEvent(Base):
    __tablename__ = "commission_status_events"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    commission_entry_id = Column(Integer, ForeignKey("commission_entries.id", ondelete="CASCADE"), nullable=False, index=True)
    from_status = Column(String(32), nullable=True)
    to_status = Column(String(32), nullable=False, index=True)
    reason = Column(Text, nullable=True)
    actor_id = Column(String(64), nullable=True)
    actor_name = Column(String(160), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
