from core.database import Base
from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"
    __table_args__ = (
        UniqueConstraint("issue_key", name="uq_data_quality_issues_key"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    issue_key = Column(String(192), nullable=False, index=True)
    code = Column(String(80), nullable=False, index=True)
    category = Column(String(32), nullable=False, default="data_quality", index=True)
    severity = Column(String(16), nullable=False, default="warning", index=True)
    status = Column(String(24), nullable=False, default="open", index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(
        Integer,
        ForeignKey("customer_engagements.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    customer_name = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    suggested_action = Column(Text, nullable=True)
    occurrence_count = Column(Integer, nullable=False, default=1)
    first_detected_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    last_detected_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True, index=True)
    resolution_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AutomationScanRun(Base):
    __tablename__ = "automation_scan_runs"
    __table_args__ = (
        UniqueConstraint("run_key", name="uq_automation_scan_runs_key"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_key = Column(String(96), nullable=False, index=True)
    scan_date = Column(Date, nullable=False, index=True)
    trigger = Column(String(24), nullable=False, default="scheduled", index=True)
    status = Column(String(24), nullable=False, default="running", index=True)
    detected_count = Column(Integer, nullable=False, default=0)
    opened_count = Column(Integer, nullable=False, default=0)
    resolved_count = Column(Integer, nullable=False, default=0)
    task_created_count = Column(Integer, nullable=False, default=0)
    task_updated_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True, index=True)
