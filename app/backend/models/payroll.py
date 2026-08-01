from core.database import Base
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint, func


class PayrollSheets(Base):
    __tablename__ = "payroll_sheets"
    __table_args__ = (UniqueConstraint("month", name="uq_payroll_sheet_month"), {"extend_existing": True})

    id = Column(Integer, primary_key=True, autoincrement=True)
    month = Column(String(7), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="draft", index=True)
    currency = Column(String(3), nullable=False, default="CNY")
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    confirmed_by = Column(String, nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    paid_by = Column(String, nullable=True)
    reopened_at = Column(DateTime(timezone=True), nullable=True)
    reopened_by = Column(String, nullable=True)
    reopen_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class PayrollItems(Base):
    __tablename__ = "payroll_items"
    __table_args__ = (UniqueConstraint("sheet_id", "employee_id", name="uq_payroll_sheet_employee"), {"extend_existing": True})

    id = Column(Integer, primary_key=True, autoincrement=True)
    sheet_id = Column(Integer, nullable=False, index=True)
    employee_id = Column(Integer, nullable=True, index=True)
    employee_code = Column(String, nullable=True)
    employee_name = Column(String, nullable=False)
    department = Column(String, nullable=True)
    hire_date = Column(String, nullable=True)
    payment_method = Column(String(32), nullable=False, default="alipay")
    payment_account_encrypted = Column(Text, nullable=True)
    payment_account_last4 = Column(String(8), nullable=True)
    base_salary = Column(Float, nullable=False, default=0)
    fixed_performance = Column(Float, nullable=False, default=0)
    commission = Column(Float, nullable=False, default=0)
    bonus = Column(Float, nullable=False, default=0)
    allowance = Column(Float, nullable=False, default=0)
    reimbursement = Column(Float, nullable=False, default=0)
    absence_deduction = Column(Float, nullable=False, default=0)
    performance_deduction = Column(Float, nullable=False, default=0)
    salary_advance_deduction = Column(Float, nullable=False, default=0)
    other_deduction = Column(Float, nullable=False, default=0)
    payment_status = Column(String(24), nullable=False, default="pending")
    payment_date = Column(String, nullable=True)
    payment_reference = Column(String, nullable=True)
    receipt_url = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class PayrollAuditLogs(Base):
    __tablename__ = "payroll_audit_logs"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    sheet_id = Column(Integer, nullable=False, index=True)
    item_id = Column(Integer, nullable=True, index=True)
    action = Column(String(48), nullable=False, index=True)
    actor_id = Column(String, nullable=False)
    actor_name = Column(String, nullable=True)
    actor_role = Column(String, nullable=False)
    reason = Column(Text, nullable=True)
    snapshot_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
