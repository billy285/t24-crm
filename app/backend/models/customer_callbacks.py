from core.database import Base
from sqlalchemy import Column, DateTime, Integer, String


class Customer_callbacks(Base):
    __tablename__ = "customer_callbacks"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    customer_id = Column(Integer, nullable=False)
    employee_id = Column(Integer, nullable=True)
    employee_name = Column(String, nullable=True)
    callback_date = Column(DateTime(timezone=True), nullable=False)
    callback_type = Column(String, nullable=True)
    status = Column(String, nullable=True)
    content = Column(String, nullable=True)
    result = Column(String, nullable=True)
    next_callback_date = Column(DateTime(timezone=True), nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)