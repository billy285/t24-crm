from core.database import Base
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint


class Tasks(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("automation_issue_id", name="uq_tasks_automation_issue_id"),
        UniqueConstraint("opportunity_id", name="uq_tasks_opportunity_id"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    title = Column(String, nullable=False)
    customer_id = Column(Integer, nullable=True)
    customer_name = Column(String, nullable=True)
    assignee_id = Column(Integer, nullable=True)
    assignee_name = Column(String, nullable=True)
    collaborator_names = Column(String, nullable=True)
    task_type = Column(String, nullable=True)
    priority = Column(String, nullable=True)
    status = Column(String, nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
    notes = Column(String, nullable=True)
    attachment_link = Column(String, nullable=True)
    source_type = Column(String(32), nullable=True, index=True)
    automation_issue_id = Column(
        Integer,
        ForeignKey("data_quality_issues.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    opportunity_id = Column(
        Integer,
        ForeignKey("opportunities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    completion_result = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
