from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func


class RingCentralCallRecords(Base):
    """Provider-verified RingCentral call facts kept separate from sales outcomes."""

    __tablename__ = "ringcentral_call_records"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    provider_key = Column(String(255), nullable=False, unique=True, index=True)
    ringcentral_call_id = Column(String, nullable=True, unique=True, index=True)
    ringcentral_session_id = Column(String, nullable=True, index=True)
    telephony_session_id = Column(String, nullable=True, index=True)
    ringcentral_account_id = Column(String, nullable=True, index=True)
    ringcentral_extension_id = Column(String, nullable=True, index=True)
    sales_employee_id = Column(Integer, nullable=False, index=True)
    sales_employee_name = Column(String, nullable=True)
    lead_id = Column(Integer, nullable=True, index=True)
    task_id = Column(Integer, nullable=True, index=True)
    activity_id = Column(Integer, nullable=True, index=True)
    direction = Column(String(24), nullable=True, index=True)
    action = Column(String(64), nullable=True)
    provider_status = Column(String(64), nullable=True, index=True)
    provider_result = Column(String(64), nullable=True, index=True)
    from_phone = Column(String(64), nullable=True)
    to_phone = Column(String(64), nullable=True)
    remote_phone = Column(String(64), nullable=True, index=True)
    connected = Column(Boolean, nullable=False, default=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True, index=True)
    connected_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True, index=True)
    duration_seconds = Column(Integer, nullable=True)
    recording_uri = Column(Text, nullable=True)
    provider_sequence = Column(Integer, nullable=True)
    last_event_uuid = Column(String(128), nullable=True, index=True)
    sync_status = Column(String(32), nullable=False, default="event_received", index=True)
    last_event_at = Column(DateTime(timezone=True), nullable=True)
    synced_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
