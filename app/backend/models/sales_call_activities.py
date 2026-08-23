from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func


class SalesCallActivities(Base):
    """Immutable call outcomes recorded by a salesperson in the daily workbench."""

    __tablename__ = "sales_call_activities"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    lead_id = Column(Integer, nullable=False, index=True)
    sales_employee_id = Column(Integer, nullable=False, index=True)
    sales_employee_name = Column(String, nullable=True)
    outcome = Column(String, nullable=False, index=True)
    notes = Column(Text, nullable=True)
    next_follow_up_at = Column(DateTime(timezone=True), nullable=True, index=True)
    call_duration_seconds = Column(Integer, nullable=True)
    ringcentral_connected = Column(Boolean, nullable=True, index=True)
    ringcentral_call_id = Column(String, nullable=True, index=True)
    ringcentral_session_id = Column(String, nullable=True, index=True)
    recording_uri = Column(Text, nullable=True)
    sync_status = Column(String, nullable=False, default="pending_connection", index=True)
    called_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
