"""Sales contact suppression survives deletion or editing of a prospect."""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func

from core.database import Base


class SalesPhoneSuppression(Base):
    __tablename__ = "sales_phone_suppressions"
    __table_args__ = {"extend_existing": True}
    phone_key = Column(String(64), primary_key=True)
    blocked = Column(Boolean, nullable=False, default=True)
    reason = Column(Text, nullable=False)
    source_lead_id = Column(Integer, nullable=True)
    actor_id = Column(Integer, nullable=True)
    actor_name = Column(String(255), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SalesContactProtectionAudit(Base):
    __tablename__ = "sales_contact_protection_audits"
    __table_args__ = {"extend_existing": True}
    id = Column(Integer, primary_key=True, autoincrement=True)
    phone_key = Column(String(64), nullable=False, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    action = Column(String(32), nullable=False)
    reason = Column(Text, nullable=False)
    actor_id = Column(Integer, nullable=True)
    actor_name = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
