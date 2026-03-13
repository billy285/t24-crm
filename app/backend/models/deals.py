from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String


class Deals(Base):
    __tablename__ = "deals"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    customer_id = Column(Integer, nullable=False)
    customer_name = Column(String, nullable=True)
    sales_employee_id = Column(Integer, nullable=True)
    sales_name = Column(String, nullable=True)
    product_type = Column(String, nullable=False)
    package_name = Column(String, nullable=True)
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