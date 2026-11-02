"""Private monthly draft preparation policies; never publication permission."""
from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint


class MediaMonthlyAutomationPolicy(Base):
    __tablename__ = "media_monthly_automation_policies"
    __table_args__ = (UniqueConstraint("owner_id", "customer_id", "platform", name="uq_monthly_auto_policy"),)
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, nullable=False)
    platform = Column(String(24), nullable=False)
    revision = Column(Integer, nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
    lead_days = Column(Integer, nullable=False)
    local_time = Column(String(5), nullable=False)
    timezone = Column(String(80), nullable=False)
    profile_revision = Column(Integer, nullable=False)
    source_signature = Column(String(64), nullable=False)
    runtime_fingerprint = Column(String(64), nullable=False)
    first_target_month = Column(String(7), nullable=False)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MediaMonthlyAutomationOccurrence(Base):
    __tablename__ = "media_monthly_automation_occurrences"
    __table_args__ = (
        UniqueConstraint("owner_id", "customer_id", "platform", "month", name="uq_monthly_auto_occurrence"),
        UniqueConstraint("owner_id", "request_id", name="uq_monthly_auto_generation_request"),
    )
    id = Column(Integer, primary_key=True)
    policy_id = Column(Integer, ForeignKey("media_monthly_automation_policies.id", ondelete="RESTRICT"), nullable=False)
    policy_revision = Column(Integer, nullable=False)
    owner_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, nullable=False)
    customer_name = Column(String(255), nullable=False)
    platform = Column(String(24), nullable=False)
    month = Column(String(7), nullable=False)
    request_id = Column(String(36), nullable=False)
    source_signature = Column(String(64), nullable=False)
    runtime_fingerprint = Column(String(64), nullable=False)
    generation_input = Column(JSON, nullable=True)
    run_id = Column(Integer, ForeignKey("media_monthly_runs.id", ondelete="RESTRICT"), nullable=True)
    status = Column(String(20), nullable=False)
    message = Column(String(300), nullable=False)
    ai_attempted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MediaMonthlyAutomationRequest(Base):
    __tablename__ = "media_monthly_automation_requests"
    __table_args__ = (UniqueConstraint("owner_id", "request_id", name="uq_monthly_auto_policy_request"),)
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, nullable=False)
    customer_id = Column(Integer, nullable=False)
    platform = Column(String(24), nullable=False)
    request_id = Column(String(36), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    result = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
