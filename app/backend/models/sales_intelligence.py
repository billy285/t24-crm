"""Sales-only operating records. Existing finance and customer tables are untouched."""

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from core.database import Base


class SalesOperatingSettings(Base):
    __tablename__ = "sales_operating_settings"
    id = Column(Integer, primary_key=True)
    effective_month = Column(String(7), nullable=False, unique=True, index=True)
    payload_json = Column(Text, nullable=False)
    created_by_id = Column(Integer, nullable=False)
    created_by_name = Column(String)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SalesLeadProfiles(Base):
    __tablename__ = "sales_lead_profiles"
    lead_id = Column(Integer, primary_key=True)
    revision = Column(Integer, nullable=False, default=1)
    payload_json = Column(Text, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SalesContactDetails(Base):
    __tablename__ = "sales_contact_details"
    activity_id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, nullable=False, index=True)
    reached_person = Column(String(24), nullable=False, default="unknown")
    rejection_reason = Column(String(200))
    need_summary = Column(Text)
    next_step = Column(Text)
    recorded_by_id = Column(Integer, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SalesInsightEvents(Base):
    __tablename__ = "sales_insight_events"
    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, nullable=False, index=True)
    kind = Column(String(40), nullable=False, index=True)
    actor_id = Column(Integer, nullable=False)
    actor_name = Column(String)
    owner_id = Column(Integer, index=True)
    payload_json = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class SalesMonthlyTargets(Base):
    __tablename__ = "sales_monthly_targets"
    __table_args__ = (
        UniqueConstraint(
            "employee_id", "month", "revision", name="uq_sales_target_revision"
        ),
    )
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, nullable=False, index=True)
    month = Column(String(7), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    manager_id = Column(Integer, index=True)
    employee_name = Column(String)
    payload_json = Column(Text, nullable=False)
    created_by_id = Column(Integer, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SalesCoachingTasks(Base):
    __tablename__ = "sales_coaching_tasks"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, nullable=False, index=True)
    manager_id = Column(Integer, nullable=False, index=True)
    lead_id = Column(Integer, index=True)
    action = Column(Text, nullable=False)
    due_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default="open")
    revision = Column(Integer, nullable=False, default=1)
    completion_note = Column(Text)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at = Column(DateTime(timezone=True))


class SalesSavedViews(Base):
    __tablename__ = "sales_saved_views"
    __table_args__ = (
        UniqueConstraint("employee_id", "name", name="uq_sales_saved_view"),
    )
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, nullable=False, index=True)
    name = Column(String(60), nullable=False)
    payload_json = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
