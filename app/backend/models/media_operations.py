"""Additive content delivery workflow, with no financial or permission mutations."""
from core.database import Base
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func


class MediaOperationTask(Base):
    __tablename__ = "media_operation_tasks"
    __table_args__ = (
        UniqueConstraint("created_by_id", "client_request_id", name="uq_media_operation_create_request"),
        CheckConstraint("revision >= 1", name="ck_media_operation_revision"),
        CheckConstraint("status IN ('draft','in_review','ready','completed','blocked')", name="ck_media_operation_status"),
        {"extend_existing": True},
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False, index=True)
    customer_name = Column(String(255), nullable=False)
    service_progress_id = Column(Integer, nullable=True)
    title = Column(String(200), nullable=False)
    platform = Column(String(32), nullable=False)
    due_at = Column(DateTime(timezone=True), nullable=False, index=True)
    timezone = Column(String(80), nullable=False)
    assignee_id = Column(Integer, nullable=False, index=True)
    assignee_name = Column(String(255), nullable=False)
    content = Column(Text, nullable=False, default="", server_default="")
    material_id = Column(Integer, nullable=True)
    material_title = Column(String(255), nullable=True)
    status = Column(String(16), nullable=False, default="draft", server_default="draft", index=True)
    blocked_from_status = Column(String(16), nullable=True)
    block_reason = Column(Text, nullable=True)
    review_note = Column(Text, nullable=True)
    proof_url = Column(Text, nullable=True)
    proof_material_id = Column(Integer, nullable=True)
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    created_by_id = Column(Integer, nullable=False)
    client_request_id = Column(String(64), nullable=False)
    creation_fingerprint = Column(String(64), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MediaOperationEvent(Base):
    __tablename__ = "media_operation_events"
    __table_args__ = (
        UniqueConstraint("task_id", "revision", name="uq_media_operation_event_revision"),
        UniqueConstraint("task_id", "request_id", name="uq_media_operation_event_request"),
        {"extend_existing": True},
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("media_operation_tasks.id", ondelete="RESTRICT"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    action = Column(String(24), nullable=False)
    actor_id = Column(Integer, nullable=False)
    actor_name = Column(String(255), nullable=False)
    before_status = Column(String(16), nullable=True)
    after_status = Column(String(16), nullable=False)
    request_id = Column(String(64), nullable=True)
    request_fingerprint = Column(String(64), nullable=True)
    note = Column(Text, nullable=True)
    snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MediaOperationPublicationSpec(Base):
    """Only explicit structured publication settings; legacy tasks need no row."""
    __tablename__ = "media_operation_publication_specs"
    task_id = Column(Integer, ForeignKey("media_operation_tasks.id", ondelete="RESTRICT"), primary_key=True)
    spec = Column(JSON, nullable=False)
