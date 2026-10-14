from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func


class CustomerAccessGrant(Base):
    """Only an active, explicit owner invitation grants customer access."""

    __tablename__ = "customer_access_grants"
    __table_args__ = (
        UniqueConstraint("customer_id", "employee_id", name="uq_customer_access_grant"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    access_level = Column(String(20), nullable=False, default="read_only", server_default="read_only")
    scopes = Column(JSON, nullable=False, default=dict, server_default="{}")
    finance_access = Column(String(20), nullable=False, default="none", server_default="none")
    can_export = Column(Boolean, nullable=False, default=False, server_default="0")
    can_delete = Column(Boolean, nullable=False, default=False, server_default="0")
    can_reassign = Column(Boolean, nullable=False, default=False, server_default="0")
    # Fail closed for legacy rows and any non-invitation creation path.
    invitation_source = Column(String(32), nullable=False, default="legacy", server_default="legacy")
    invitation_status = Column(String(24), nullable=False, default="pending_review", server_default="pending_review")
    invited_at = Column(DateTime(timezone=True), nullable=True)
    invited_by_id = Column(String, nullable=True)
    invited_by_name = Column(String, nullable=True)
    granted_by_id = Column(String, nullable=True)
    granted_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CustomerAccessAudit(Base):
    """Immutable permission snapshots, retained even after customer deletion."""

    __tablename__ = "customer_access_audits"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False, index=True)
    actor_id = Column(String, nullable=False)
    actor_name = Column(String, nullable=False)
    before = Column(JSON, nullable=False)
    after = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
