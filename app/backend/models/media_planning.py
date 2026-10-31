"""Content briefs group independent platform drafts; no shared publication grant."""
from core.database import Base
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint


class MediaContentPlan(Base):
    __tablename__ = "media_content_plans"
    __table_args__ = (UniqueConstraint("created_by_id", "request_id", name="uq_media_content_plan_request"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False, index=True)
    title = Column(String(200), nullable=False)
    brief = Column(Text, nullable=False)
    created_by_id = Column(Integer, nullable=False)
    request_id = Column(String(36), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class MediaContentPlanTask(Base):
    __tablename__ = "media_content_plan_tasks"
    __table_args__ = (UniqueConstraint("plan_id", "platform", name="uq_media_content_plan_platform"),)
    task_id = Column(Integer, ForeignKey("media_operation_tasks.id", ondelete="RESTRICT"), primary_key=True)
    plan_id = Column(Integer, ForeignKey("media_content_plans.id", ondelete="RESTRICT"), nullable=False, index=True)
    platform = Column(String(32), nullable=False)
