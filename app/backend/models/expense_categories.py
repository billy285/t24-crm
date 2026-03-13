from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Integer, String


class Expense_categories(Base):
    __tablename__ = "expense_categories"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    category_key = Column(String, nullable=False)
    category_name = Column(String, nullable=False)
    category_type = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=True)
    sort_order = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)