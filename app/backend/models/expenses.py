from core.database import Base
from sqlalchemy import Column, DateTime, Float, Integer, String


class Expenses(Base):
    __tablename__ = "expenses"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    customer_id = Column(Integer, nullable=True)
    customer_name = Column(String, nullable=True)
    expense_category = Column(String, nullable=True)
    expense_type = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, nullable=True)
    expense_date = Column(DateTime(timezone=True), nullable=True)
    expense_month = Column(String, nullable=True)
    recorded_by = Column(String, nullable=True)
    payment_date = Column(DateTime(timezone=True), nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    user_id = Column(String, nullable=False)