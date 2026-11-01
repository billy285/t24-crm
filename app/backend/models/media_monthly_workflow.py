"""Owner-only immutable monthly publication packets and operation receipts."""
from core.database import Base
from sqlalchemy import Column, Integer, String, JSON, DateTime, ForeignKey, UniqueConstraint


class MediaMonthlyWorkflow(Base):
    __tablename__ = "media_monthly_workflows"
    __table_args__ = (UniqueConstraint("owner_id", "run_id", name="uq_monthly_workflow_run"),)
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, nullable=False)
    customer_id = Column(Integer, nullable=False, index=True)
    run_id = Column(Integer, ForeignKey("media_monthly_runs.id", ondelete="RESTRICT"), nullable=False)
    revision = Column(Integer, nullable=False)
    status = Column(String(24), nullable=False)
    snapshot = Column(JSON, nullable=False)
    preview_hash = Column(String(64), nullable=False)
    source_hash = Column(String(64), nullable=False)
    reviewed_hash = Column(String(64), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    task_refs = Column(JSON, nullable=False)
    schedule_refs = Column(JSON, nullable=False)
    activation = Column(JSON, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MediaMonthlyWorkflowRequest(Base):
    __tablename__ = "media_monthly_workflow_requests"
    __table_args__ = (UniqueConstraint("owner_id", "request_id", name="uq_monthly_workflow_request"),)
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, nullable=False)
    run_id = Column(Integer, ForeignKey("media_monthly_runs.id", ondelete="RESTRICT"), nullable=False)
    request_id = Column(String(36), nullable=False)
    kind = Column(String(20), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    result = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
