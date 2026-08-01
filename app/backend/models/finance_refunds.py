from core.database import Base
from sqlalchemy import Column, DateTime, Float, Integer, String


class FinanceRefund(Base):
    __tablename__ = "finance_refunds"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    payment_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, nullable=False, index=True)
    customer_name = Column(String, nullable=True)
    refund_amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False, default="USD")
    refund_date = Column(DateTime(timezone=True), nullable=False, index=True)
    provider = Column(String, nullable=False, default="stripe")
    provider_refund_id = Column(String, nullable=True, index=True)
    stripe_fee_refunded_amount = Column(Float, nullable=False, default=0)
    status = Column(String, nullable=False, default="completed", index=True)
    reason = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    recorded_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    user_id = Column(String, nullable=False, index=True)
