"""A fixed-catalog sale receipt, separate from verified financial receipts."""
from core.database import Base
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func


class SalesDealPlanPolicy(Base):
    """Owner-maintained collection policy; a sale snapshots its effective version."""
    __tablename__ = "sales_deal_plan_policies"
    plan_id = Column(Integer, ForeignKey("product_plans.id", ondelete="RESTRICT"), primary_key=True)
    collection_policy = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    updated_by_id = Column(Integer, nullable=False)
    updated_by_name = Column(String(255))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SalesDealHandoff(Base):
    __tablename__ = "sales_deal_handoffs"
    __table_args__ = (
        UniqueConstraint("lead_id", name="uq_sales_deal_handoff_lead"),
        UniqueConstraint("idempotency_key", name="uq_sales_deal_handoff_request"),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, nullable=False, index=True)
    engagement_id = Column(Integer, nullable=False, index=True)
    deal_id = Column(Integer, nullable=False, unique=True)
    subscription_id = Column(Integer)
    idempotency_key = Column(String(80), nullable=False)
    payload_digest = Column(String(64), nullable=False)
    catalog_token = Column(String(64), nullable=False)
    plan_snapshot = Column(JSON, nullable=False)
    source_snapshot = Column(JSON, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(3), nullable=False)
    collection_method = Column(String(32), nullable=False)
    operations_owner_employee_id = Column(Integer, nullable=False, index=True)
    operations_owner_name = Column(String(255), nullable=False)
    operations_status = Column(String(24), nullable=False, default="pending")
    operations_acknowledged_at = Column(DateTime(timezone=True))
    operations_ack_note = Column(Text)
    payment_id = Column(Integer, unique=True)
    payment_status = Column(String(24), nullable=False, default="pending")
    payment_fingerprint = Column(String(64))
    payment_confirmed_by_id = Column(Integer)
    payment_confirmed_by_name = Column(String(255))
    payment_confirmed_at = Column(DateTime(timezone=True))
    registered_by_id = Column(Integer, nullable=False)
    registered_by_name = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
