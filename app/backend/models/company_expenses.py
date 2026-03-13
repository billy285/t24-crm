from core.database import Base
from sqlalchemy import Column, DateTime, Float, Integer, String


class Company_expenses(Base):
    __tablename__ = "company_expenses"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    category = Column(String, nullable=False)
    category_name = Column(String, nullable=True)
    amount = Column(Float, nullable=False)
    currency = Column(String, nullable=True)
    expense_date = Column(DateTime(timezone=True), nullable=True)
    expense_month = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    recorded_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    user_id = Column(String, nullable=False)