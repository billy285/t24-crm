from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, func


class SalesQuoteRequests(Base):
    """Pre-sale quote proposals. They remain independent until a lead is converted."""

    __tablename__ = "sales_quote_requests"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    lead_id = Column(Integer, nullable=False, index=True)
    package_name = Column(String, nullable=False)
    selected_platforms = Column(Text, nullable=True)
    billing_mode = Column(String, nullable=False, default="manual")
    payment_method = Column(String, nullable=False, default="stripe")
    currency = Column(String, nullable=False, default="USD")
    list_amount = Column(Float, nullable=False, default=0)
    discount_amount = Column(Float, nullable=False, default=0)
    final_amount = Column(Float, nullable=False, default=0)
    service_start_date = Column(String, nullable=True)
    service_end_date = Column(String, nullable=True)
    special_terms = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="submitted", index=True)
    submitted_by_id = Column(Integer, nullable=False, index=True)
    submitted_by_name = Column(String, nullable=True)
    reviewed_by_id = Column(Integer, nullable=True)
    reviewed_by_name = Column(String, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SalesHandoffChecklists(Base):
    """A single operational handoff record for a lead before conversion."""

    __tablename__ = "sales_handoff_checklists"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    lead_id = Column(Integer, nullable=False, unique=True, index=True)
    quote_id = Column(Integer, nullable=True, index=True)
    customer_goal = Column(Text, nullable=True)
    key_contacts = Column(Text, nullable=True)
    service_start_date = Column(String, nullable=True)
    service_end_date = Column(String, nullable=True)
    special_commitments = Column(Text, nullable=True)
    operations_owner = Column(String, nullable=True)
    operations_group_created = Column(Boolean, nullable=False, default=False)
    finance_payment_confirmed = Column(Boolean, nullable=False, default=False)
    payment_status = Column(String, nullable=False, default="pending")
    amount_received = Column(Float, nullable=False, default=0)
    payment_date = Column(String, nullable=True)
    payment_reference = Column(String, nullable=True)
    payment_confirmed_by_id = Column(Integer, nullable=True)
    payment_confirmed_by_name = Column(String, nullable=True)
    payment_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    generated_deal_id = Column(Integer, nullable=True, index=True)
    generate_service_board = Column(Boolean, nullable=False, default=False)
    handoff_notes = Column(Text, nullable=True)
    updated_by_id = Column(Integer, nullable=True)
    updated_by_name = Column(String, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
