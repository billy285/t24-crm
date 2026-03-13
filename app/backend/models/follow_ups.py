from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Integer, String


class Follow_ups(Base):
    __tablename__ = "follow_ups"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    customer_id = Column(Integer, nullable=False)
    employee_id = Column(Integer, nullable=True)
    employee_name = Column(String, nullable=True)
    contact_method = Column(String, nullable=True)
    content = Column(String, nullable=False)
    customer_needs = Column(String, nullable=True)
    customer_pain_points = Column(String, nullable=True)
    has_quoted = Column(Boolean, nullable=True)
    quote_plan = Column(String, nullable=True)
    close_probability = Column(Integer, nullable=True)
    stage = Column(String, nullable=True)
    next_follow_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)