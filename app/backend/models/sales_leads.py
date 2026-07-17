from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func


class SalesLeads(Base):
    """Pre-sale merchant leads kept separate from contracted customers."""

    __tablename__ = "sales_leads"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    business_name = Column(String, nullable=False, index=True)
    contact_name = Column(String, nullable=True)
    phone = Column(String, nullable=False, index=True)
    industry = Column(String, nullable=True)
    country = Column(String, nullable=True)
    state = Column(String, nullable=True)
    city = Column(String, nullable=True)
    address = Column(String, nullable=True)
    website = Column(String, nullable=True)
    source = Column(String, nullable=True)
    merchant_pool_id = Column(Integer, nullable=True, index=True)
    analysis_snapshot = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="new", index=True)
    assigned_sales_id = Column(Integer, nullable=True, index=True)
    assigned_sales_name = Column(String, nullable=True)
    team_manager_id = Column(Integer, nullable=True, index=True)
    is_blacklisted = Column(Boolean, nullable=False, default=False, index=True)
    do_not_contact = Column(Boolean, nullable=False, default=False, index=True)
    do_not_contact_reason = Column(String, nullable=True)
    converted_customer_id = Column(Integer, nullable=True, index=True)
    converted_at = Column(DateTime(timezone=True), nullable=True)
    converted_by_id = Column(Integer, nullable=True)
    converted_by_name = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    next_follow_up_at = Column(DateTime(timezone=True), nullable=True)
    last_contact_at = Column(DateTime(timezone=True), nullable=True)
    created_by_id = Column(Integer, nullable=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
