from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text


class Subscriptions(Base):
    __tablename__ = "subscriptions"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    customer_id = Column(Integer, nullable=False)
    customer_name = Column(String, nullable=True)
    deal_id = Column(Integer, nullable=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True, index=True)
    engagement_id = Column(Integer, ForeignKey("customer_engagements.id", ondelete="SET NULL"), nullable=True, index=True)
    business_line_id = Column(Integer, ForeignKey("business_lines.id", ondelete="SET NULL"), nullable=True, index=True)
    product_id = Column(Integer, ForeignKey("product_catalog.id", ondelete="SET NULL"), nullable=True, index=True)
    product_plan_id = Column(Integer, ForeignKey("product_plans.id", ondelete="SET NULL"), nullable=True, index=True)
    package_name = Column(String, nullable=False)
    package_price = Column(Float, nullable=False)
    list_price_snapshot = Column(Float, nullable=True)
    pricing_source = Column(String(24), nullable=True)
    selected_platforms = Column(Text, nullable=True)
    service_scope_json = Column(Text, nullable=True)
    billing_cycle = Column(String, nullable=True)
    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    auto_renew = Column(Boolean, nullable=True)
    renewal_person = Column(String, nullable=True)
    last_payment_date = Column(DateTime(timezone=True), nullable=True)
    next_payment_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, nullable=True)
    renewal_result = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
