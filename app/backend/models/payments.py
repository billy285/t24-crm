from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String


class Payments(Base):
    __tablename__ = "payments"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    customer_id = Column(Integer, nullable=False)
    customer_name = Column(String, nullable=True)
    income_type = Column(String, nullable=True)
    product_name = Column(String, nullable=True)
    amount_due = Column(Float, nullable=False)
    amount_paid = Column(Float, nullable=False)
    currency = Column(String, nullable=True)
    payment_date = Column(DateTime(timezone=True), nullable=True)
    payment_method = Column(String, nullable=True)
    billing_cycle = Column(String, nullable=True)
    coverage_start = Column(DateTime(timezone=True), nullable=True)
    coverage_end = Column(DateTime(timezone=True), nullable=True)
    has_invoice = Column(Boolean, nullable=True)
    outstanding_amount = Column(Float, nullable=True)
    expense_month = Column(String, nullable=True)
    recorded_by = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    user_id = Column(String, nullable=False)