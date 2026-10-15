"""Sales prospect collaboration, separate from customer and financial grants."""
from core.database import Base
from sqlalchemy import Column, DateTime, Integer, JSON, String, Text, UniqueConstraint, func


class SalesDossierSummary(Base):
    __tablename__ = "sales_dossier_summaries"
    lead_id = Column(Integer, primary_key=True)
    revision = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False)
    updated_by_id = Column(Integer, nullable=False)
    updated_by_name = Column(String(255))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SalesDossierSummaryAudit(Base):
    __tablename__ = "sales_dossier_summary_audits"
    __table_args__ = (UniqueConstraint("lead_id", "revision", name="uq_sales_dossier_summary_revision"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    before = Column(JSON, nullable=False)
    after = Column(JSON, nullable=False)
    actor_id = Column(Integer, nullable=False)
    actor_name = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SalesDossierGrant(Base):
    __tablename__ = "sales_dossier_grants"
    __table_args__ = (UniqueConstraint("lead_id", "employee_id", name="uq_sales_dossier_grant_employee"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, nullable=False, index=True)
    employee_id = Column(Integer, nullable=False, index=True)
    access = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    invited_by_id = Column(Integer, nullable=False)
    invited_by_name = Column(String(255))
    invited_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_by_id = Column(Integer)
    revoked_by_name = Column(String(255))
    revoked_at = Column(DateTime(timezone=True))


class SalesDossierGrantAudit(Base):
    __tablename__ = "sales_dossier_grant_audits"
    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, nullable=False, index=True)
    employee_id = Column(Integer, nullable=False)
    revision = Column(Integer, nullable=False)
    action = Column(String(16), nullable=False)
    access = Column(String(16), nullable=False)
    actor_id = Column(Integer, nullable=False)
    actor_name = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SalesDossierHandoff(Base):
    __tablename__ = "sales_dossier_handoffs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, nullable=False, index=True)
    from_sales_id = Column(Integer)
    from_sales_name = Column(String(255))
    to_sales_id = Column(Integer, nullable=False)
    to_sales_name = Column(String(255))
    note = Column(Text, nullable=False)
    reason = Column(Text)
    summary = Column(JSON, nullable=False)
    status = Column(String(16), nullable=False)
    created_by_id = Column(Integer, nullable=False)
    created_by_name = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    acknowledged_by_id = Column(Integer)
    acknowledged_by_name = Column(String(255))
    acknowledged_at = Column(DateTime(timezone=True))
    ack_note = Column(Text)
