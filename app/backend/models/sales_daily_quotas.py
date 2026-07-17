from core.database import Base
from sqlalchemy import Column, Date, DateTime, Integer, String, UniqueConstraint, func


class SalesDailyQuotas(Base):
    """Manager-controlled daily dial target. Missing rows use the default target of 100."""

    __tablename__ = "sales_daily_quotas"
    __table_args__ = (UniqueConstraint("sales_employee_id", "target_date", name="uq_sales_daily_quota"), {"extend_existing": True})

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    sales_employee_id = Column(Integer, nullable=False, index=True)
    target_date = Column(Date, nullable=False, index=True)
    target_count = Column(Integer, nullable=False, default=100)
    updated_by_id = Column(Integer, nullable=True)
    updated_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
