from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func


class SalesLeadConversionLogs(Base):
    """Audit record connecting a pre-sale lead to its contracted customer."""

    __tablename__ = "sales_lead_conversion_logs"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    lead_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, nullable=False, index=True)
    generated_customer_code = Column(String, nullable=False, index=True)
    duplicate_check_json = Column(Text, nullable=False)
    lead_snapshot_json = Column(Text, nullable=False)
    generate_service_board = Column(Boolean, nullable=False, default=False)
    service_progress_id = Column(Integer, nullable=True)
    converted_by_id = Column(Integer, nullable=False)
    converted_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
