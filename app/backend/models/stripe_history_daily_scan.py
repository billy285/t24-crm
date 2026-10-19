"""Durable cursors and short leases for scoped Stripe history rechecks only."""
from core.database import Base
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String


class StripeHistoryScanState(Base):
    __tablename__ = "stripe_history_scan_states"
    binding_id = Column(Integer, ForeignKey("stripe_history_bindings.id", ondelete="RESTRICT"), primary_key=True)
    scan_for = Column(String(10))
    completed_for = Column(String(10))
    target_end = Column(DateTime(timezone=True))
    range_start = Column(DateTime(timezone=True))
    range_end = Column(DateTime(timezone=True))
    cursor = Column(String(255))
    covered_through = Column(DateTime(timezone=True))
    lease_token = Column(String(64))
    lease_until = Column(DateTime(timezone=True))
    retry_at = Column(DateTime(timezone=True))
    failure_count = Column(Integer, nullable=False, default=0)
    last_error_code = Column(String(40))
    last_attempt_at = Column(DateTime(timezone=True))
    last_completed_at = Column(DateTime(timezone=True))
    page_count = Column(Integer, nullable=False, default=0)
    invoice_count = Column(Integer, nullable=False, default=0)
    discovered_count = Column(Integer, nullable=False, default=0)
