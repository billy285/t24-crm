from core.database import Base
from sqlalchemy import Column, Date, DateTime, Integer, String, UniqueConstraint, func


class SalesDailyDialTasks(Base):
    """A fixed daily calling batch so completing a target does not pull endless new leads."""

    __tablename__ = "sales_daily_dial_tasks"
    __table_args__ = (UniqueConstraint("sales_employee_id", "task_date", "lead_id", name="uq_sales_daily_dial_task"), {"extend_existing": True})

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    sales_employee_id = Column(Integer, nullable=False, index=True)
    task_date = Column(Date, nullable=False, index=True)
    lead_id = Column(Integer, nullable=False, index=True)
    queue_category = Column(String, nullable=False, default="new", index=True)
    status = Column(String, nullable=False, default="pending", index=True)
    dial_started_at = Column(DateTime(timezone=True), nullable=True)
    completed_activity_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
