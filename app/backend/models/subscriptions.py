from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String


class Subscriptions(Base):
    __tablename__ = "subscriptions"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    customer_id = Column(Integer, nullable=False)
    customer_name = Column(String, nullable=True)
    deal_id = Column(Integer, nullable=True)
    package_name = Column(String, nullable=False)
    package_price = Column(Float, nullable=False)
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