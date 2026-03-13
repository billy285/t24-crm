from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Integer, String


class Customers(Base):
    __tablename__ = "customers"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    customer_code = Column(String, nullable=True)
    business_name = Column(String, nullable=False)
    contact_name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    wechat = Column(String, nullable=True)
    email = Column(String, nullable=True)
    address = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    website = Column(String, nullable=True)
    google_business_link = Column(String, nullable=True)
    facebook_link = Column(String, nullable=True)
    instagram_link = Column(String, nullable=True)
    yelp_link = Column(String, nullable=True)
    has_ordering_system = Column(Boolean, nullable=True)
    current_platform = Column(String, nullable=True)
    monthly_orders = Column(Integer, nullable=True)
    source = Column(String, nullable=True)
    sales_person = Column(String, nullable=True)
    sales_employee_id = Column(Integer, nullable=True)
    level = Column(String, nullable=True)
    status = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)