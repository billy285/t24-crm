from core.database import Base
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, func


class MonthlyProfitClose(Base):
    """Immutable owner-profit snapshot for a closed calendar month."""

    __tablename__ = "monthly_profit_closes"
    __table_args__ = (
        UniqueConstraint("year_month", name="uq_monthly_profit_close_month"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    year_month = Column(String(7), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="locked", index=True)
    snapshot_json = Column(Text, nullable=False)
    locked_by = Column(String(160), nullable=True)
    locked_at = Column(DateTime(timezone=True), nullable=True)
    reopened_by = Column(String(160), nullable=True)
    reopened_at = Column(DateTime(timezone=True), nullable=True)
    reopen_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
