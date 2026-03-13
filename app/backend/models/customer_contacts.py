from core.database import Base
from sqlalchemy import Column, DateTime, Integer, String


class Customer_contacts(Base):
    __tablename__ = "customer_contacts"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    customer_id = Column(Integer, nullable=False)
    contact_name = Column(String, nullable=False)
    contact_phone = Column(String, nullable=True)
    contact_role = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)