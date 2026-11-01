"""Owner-confirmed monthly draft preparation; never a publication queue."""
from core.database import Base
from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, Boolean, ForeignKey, UniqueConstraint


class MediaMonthlyProfile(Base):
    __tablename__ = "media_monthly_profiles"
    __table_args__ = (UniqueConstraint("owner_id", "customer_id", name="uq_monthly_profile_owner_customer"),)
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, nullable=False)
    customer_id = Column(Integer, nullable=False)
    revision = Column(Integer, nullable=False)
    public_facts = Column(JSON, nullable=False)
    rules = Column(JSON, nullable=False)
    menu_item_ids = Column(JSON, nullable=False)
    images = Column(JSON, nullable=False)
    confirmed_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MediaMonthlyRun(Base):
    __tablename__ = "media_monthly_runs"
    __table_args__ = (UniqueConstraint("owner_id", "request_id", name="uq_monthly_run_request"),
                      UniqueConstraint("owner_id", "customer_id", "month", "input_hash", name="uq_monthly_run_inputs"),
                      UniqueConstraint("owner_id", "adopt_request_id", name="uq_monthly_adopt_request"))
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, nullable=False)
    customer_id = Column(Integer, nullable=False, index=True)
    profile_id = Column(Integer, ForeignKey("media_monthly_profiles.id", ondelete="RESTRICT"), nullable=False)
    request_id = Column(String(36), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    input_hash = Column(String(64), nullable=False)
    month = Column(String(7), nullable=False)
    snapshot = Column(JSON, nullable=False)
    runtime = Column(JSON, nullable=False)
    consent = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False)
    revision = Column(Integer, nullable=False)
    ai_used = Column(Boolean, nullable=False)
    message = Column(String(300), nullable=False)
    adopt_request_id = Column(String(36), nullable=True)
    adopt_fingerprint = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MediaMonthlyItem(Base):
    __tablename__ = "media_monthly_items"
    __table_args__ = (UniqueConstraint("run_id", "slot_id", name="uq_monthly_item_slot"),)
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("media_monthly_runs.id", ondelete="RESTRICT"), nullable=False, index=True)
    slot_id = Column(String(16), nullable=False)
    proposed_publish_at = Column(DateTime(timezone=True), nullable=False)
    timezone = Column(String(80), nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    owner_summary = Column(Text, nullable=False)
    material_id = Column(Integer, nullable=True)
    image_version_id = Column(String(32), nullable=True)
    image_sha256 = Column(String(64), nullable=True)
    menu_item_ids = Column(JSON, nullable=False)
    quality_warnings = Column(JSON, nullable=False)
    revision = Column(Integer, nullable=False)
    copy_hash = Column(String(64), nullable=False)
    task_id = Column(Integer, ForeignKey("media_operation_tasks.id", ondelete="RESTRICT"), nullable=True, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
