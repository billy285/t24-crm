from core.database import Base
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint, func


class MonthlyExchangeRate(Base):
    """Audited monthly management exchange rate.

    Historical owner reports only use locked rows, so a later market move does
    not rewrite an already reviewed month's RMB profit.
    """

    __tablename__ = "monthly_exchange_rates"
    __table_args__ = (
        UniqueConstraint("year_month", "base_currency", "quote_currency", name="uq_monthly_exchange_rate_pair"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    year_month = Column(String(7), nullable=False, index=True)
    base_currency = Column(String(3), nullable=False, default="USD")
    quote_currency = Column(String(3), nullable=False, default="CNY")
    average_rate = Column(Float, nullable=False)
    source = Column(String(160), nullable=False)
    status = Column(String(16), nullable=False, default="locked", index=True)
    notes = Column(Text, nullable=True)
    recorded_by = Column(String(160), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
