"""Revocable employee login sessions, separate from all business records."""
from core.database import Base
from sqlalchemy import Column, Integer, String


class EmployeeAuthSession(Base):
    __tablename__ = "employee_auth_sessions"
    __table_args__ = {"extend_existing": True}

    id = Column(String(64), primary_key=True, nullable=False)
    employee_id = Column(Integer, nullable=False, index=True)
    credential_fingerprint = Column(String(64), nullable=False)
    created_at = Column(Integer, nullable=False)
    expires_at = Column(Integer, nullable=False, index=True)
    revoked_at = Column(Integer, nullable=True)
