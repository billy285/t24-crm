from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint


class CustomerLifecycleCycle(Base):
    __tablename__ = "customer_lifecycle_cycles"
    __table_args__ = (
        UniqueConstraint("customer_id", "cycle_number", name="uq_customer_lifecycle_cycle"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    customer_id = Column(Integer, nullable=False, index=True)
    cycle_number = Column(Integer, nullable=False, default=1)
    first_payment_id = Column(Integer, nullable=True, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ended_at = Column(DateTime(timezone=True), nullable=True, index=True)
    status = Column(String(24), nullable=False, default="active", index=True)
    start_source = Column(String(24), nullable=False, default="payment")
    start_locked = Column(Boolean, nullable=False, default=False)
    stop_reason = Column(String(48), nullable=True, index=True)
    stop_note = Column(Text, nullable=True)
    confirmed_by_id = Column(String, nullable=True)
    confirmed_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class CustomerLifecycleEvent(Base):
    __tablename__ = "customer_lifecycle_events"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    customer_id = Column(Integer, nullable=False, index=True)
    cycle_id = Column(Integer, nullable=True, index=True)
    event_type = Column(String(32), nullable=False, index=True)
    effective_at = Column(DateTime(timezone=True), nullable=False, index=True)
    source_type = Column(String(32), nullable=True)
    source_id = Column(Integer, nullable=True)
    reason_code = Column(String(48), nullable=True, index=True)
    note = Column(Text, nullable=True)
    actor_id = Column(String, nullable=True)
    actor_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
