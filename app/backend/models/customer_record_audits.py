from core.database import Base
from sqlalchemy import Column, DateTime, Integer, JSON, String, func


class CustomerRecordAudit(Base):
    """Private change snapshots; intentionally absent from generic entity APIs."""

    __tablename__ = "customer_record_audits"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False, index=True)
    module = Column(String(32), nullable=False)
    entity_type = Column(String(64), nullable=False)
    entity_id = Column(Integer, nullable=False)
    actor_id = Column(String(64), nullable=False)
    actor_name = Column(String(255), nullable=False)
    action = Column(String(20), nullable=False)
    before = Column(JSON, nullable=False)
    after = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
