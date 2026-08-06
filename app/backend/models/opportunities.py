from core.database import Base
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, func


class Opportunities(Base):
    __tablename__ = "opportunities"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    customer_name = Column(String(255), nullable=False)
    business_line_id = Column(Integer, ForeignKey("business_lines.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("product_catalog.id", ondelete="SET NULL"), nullable=True, index=True)
    product_plan_id = Column(Integer, ForeignKey("product_plans.id", ondelete="SET NULL"), nullable=True, index=True)
    opportunity_code = Column(String(64), nullable=False, unique=True, index=True)
    title = Column(String(200), nullable=False)
    stage = Column(String(32), nullable=False, default="initial", index=True)
    status = Column(String(24), nullable=False, default="open", index=True)
    estimated_amount = Column(Float, nullable=True)
    currency = Column(String(3), nullable=False, default="USD")
    probability = Column(Integer, nullable=False, default=10)
    owner_employee_id = Column(Integer, nullable=True, index=True)
    owner_name = Column(String(160), nullable=True)
    source = Column(String(32), nullable=True, index=True)
    selected_platforms = Column(Text, nullable=True)
    service_scope_json = Column(Text, nullable=True)
    expected_close_date = Column(DateTime(timezone=True), nullable=True, index=True)
    next_follow_up_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_follow_up_at = Column(DateTime(timezone=True), nullable=True)
    pause_until = Column(DateTime(timezone=True), nullable=True, index=True)
    lost_reason = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)
    converted_deal_id = Column(Integer, nullable=True, unique=True)
    converted_engagement_id = Column(Integer, nullable=True, unique=True)
    converted_subscription_id = Column(Integer, nullable=True, unique=True)
    won_at = Column(DateTime(timezone=True), nullable=True)
    lost_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
