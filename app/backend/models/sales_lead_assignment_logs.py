from core.database import Base
from sqlalchemy import Column, DateTime, Integer, String, Text, func


class SalesLeadAssignmentLogs(Base):
    """Append-only ownership history for protected phone-sales leads."""

    __tablename__ = "sales_lead_assignment_logs"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    lead_id = Column(Integer, nullable=False, index=True)
    action = Column(String, nullable=False, index=True)
    from_sales_employee_id = Column(Integer, nullable=True, index=True)
    from_sales_employee_name = Column(String, nullable=True)
    to_sales_employee_id = Column(Integer, nullable=True, index=True)
    to_sales_employee_name = Column(String, nullable=True)
    reason = Column(Text, nullable=True)
    effective_until = Column(DateTime(timezone=True), nullable=True, index=True)
    operated_by_id = Column(Integer, nullable=True)
    operated_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
