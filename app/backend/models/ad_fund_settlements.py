from core.database import Base
from sqlalchemy import Column, DateTime, Float, Integer, String, UniqueConstraint


class AdFundSettlement(Base):
    __tablename__ = "ad_fund_settlements"
    __table_args__ = (
        UniqueConstraint("customer_id", "year_month", "currency", name="uq_ad_fund_customer_month_currency"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    customer_id = Column(Integer, nullable=False, index=True)
    customer_name = Column(String, nullable=True)
    year_month = Column(String, nullable=False, index=True)
    currency = Column(String, nullable=False, default="USD")
    opening_balance = Column(Float, nullable=False, default=0)
    funds_received = Column(Float, nullable=False, default=0)
    actual_ad_spend = Column(Float, nullable=False, default=0)
    customer_refund_amount = Column(Float, nullable=False, default=0)
    recognized_spread_amount = Column(Float, nullable=False, default=0)
    adjustment_amount = Column(Float, nullable=False, default=0)
    closing_balance = Column(Float, nullable=False, default=0)
    status = Column(String, nullable=False, default="draft", index=True)
    notes = Column(String, nullable=True)
    recorded_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    user_id = Column(String, nullable=False, index=True)
