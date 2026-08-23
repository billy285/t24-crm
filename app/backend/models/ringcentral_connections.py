from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func


class RingCentralConnections(Base):
    """Per-employee RingCentral OAuth connection kept separate from CRM records."""

    __tablename__ = "ringcentral_connections"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    employee_id = Column(Integer, nullable=False, unique=True, index=True)
    employee_name = Column(String, nullable=True)
    ringcentral_account_id = Column(String, nullable=True, index=True)
    ringcentral_extension_id = Column(String, nullable=True, index=True)
    extension_number = Column(String, nullable=True)
    access_token_encrypted = Column(Text, nullable=False)
    refresh_token_encrypted = Column(Text, nullable=True)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    scopes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    webhook_subscription_id = Column(String, nullable=True, index=True)
    webhook_subscription_status = Column(String, nullable=True, index=True)
    webhook_expires_at = Column(DateTime(timezone=True), nullable=True)
    last_event_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
