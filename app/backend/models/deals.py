from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint


class Deals(Base):
    __tablename__ = "deals"
    __table_args__ = (
        UniqueConstraint("opportunity_id", name="uq_deals_opportunity_id"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    source_payment_id = Column(Integer, nullable=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True, index=True)
    engagement_id = Column(Integer, ForeignKey("customer_engagements.id", ondelete="SET NULL"), nullable=True, index=True)
    business_line_id = Column(Integer, ForeignKey("business_lines.id", ondelete="SET NULL"), nullable=True, index=True)
    product_id = Column(Integer, ForeignKey("product_catalog.id", ondelete="SET NULL"), nullable=True, index=True)
    product_plan_id = Column(Integer, ForeignKey("product_plans.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_id = Column(Integer, nullable=False)
    customer_name = Column(String, nullable=True)
    sales_employee_id = Column(Integer, nullable=True)
    sales_name = Column(String, nullable=True)
    product_type = Column(String, nullable=False)
    package_name = Column(String, nullable=True)
    package_platforms = Column(String, nullable=True)
    billing_cycle = Column(String, nullable=True)
    deal_amount = Column(Float, nullable=False)
    is_paid = Column(Boolean, nullable=True)
    service_start_date = Column(DateTime(timezone=True), nullable=True)
    service_end_date = Column(DateTime(timezone=True), nullable=True)
    needs_group = Column(Boolean, nullable=True)
    is_handed_over = Column(Boolean, nullable=True)
    is_transferred_ops = Column(Boolean, nullable=True)
    notes = Column(String, nullable=True)
    deal_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
