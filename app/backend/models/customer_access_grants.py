from core.database import Base
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func


class CustomerAccessGrant(Base):
    """Explicit customer visibility granted by an administrator.

    This table only controls whether an employee may read a customer. It does
    not change sales ownership, project ownership, commissions, or finance
    permissions.
    """

    __tablename__ = "customer_access_grants"
    __table_args__ = (
        UniqueConstraint("customer_id", "employee_id", name="uq_customer_access_grant"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    granted_by_id = Column(String, nullable=True)
    granted_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
