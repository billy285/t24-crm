"""Sales-only pre-sale profiles; never linked into customer financial records."""
from core.database import Base
from sqlalchemy import Column, DateTime, Integer, JSON, String, Text, UniqueConstraint, func


class SalesLeadEnrichment(Base):
    __tablename__ = "sales_lead_enrichments"
    __table_args__ = {"extend_existing": True}
    lead_id = Column(Integer, primary_key=True)
    revision = Column(Integer, nullable=False, default=1)
    contacts = Column(JSON, nullable=False, default=list)
    preferred_contact_id = Column(String(64), nullable=True)
    interest_product_ids = Column(JSON, nullable=False, default=list)
    need_summary = Column(Text, nullable=True)
    best_contact_time = Column(String(300), nullable=True)
    verification = Column(String(16), nullable=False, default="pending")
    updated_by_id = Column(Integer, nullable=False)
    updated_by_name = Column(String(255), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SalesLeadEnrichmentAudit(Base):
    __tablename__ = "sales_lead_enrichment_audits"
    __table_args__ = (UniqueConstraint("lead_id", "revision", name="uq_sales_enrichment_revision"), {"extend_existing": True})
    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    source = Column(String(16), nullable=False)
    changed_fields = Column(JSON, nullable=False)
    before = Column(JSON, nullable=False)
    after = Column(JSON, nullable=False)
    actor_id = Column(Integer, nullable=False)
    actor_name = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SalesDialAttempt(Base):
    """Append-only evidence of each chosen number, including repeated task dials."""
    __tablename__ = "sales_dial_attempts"
    __table_args__ = {"extend_existing": True}
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, nullable=False, index=True)
    lead_id = Column(Integer, nullable=False, index=True)
    sales_employee_id = Column(Integer, nullable=False, index=True)
    dial_phone = Column(String(64), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
