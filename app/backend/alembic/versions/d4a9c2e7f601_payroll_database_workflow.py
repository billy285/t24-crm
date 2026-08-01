"""add database payroll workflow

Revision ID: d4a9c2e7f601
Revises: c8e4f1a2b6d9
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4a9c2e7f601"
down_revision: Union[str, Sequence[str], None] = "c8e4f1a2b6d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("payroll_sheets"):
        op.create_table(
            "payroll_sheets",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("month", sa.String(length=7), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="CNY"),
            sa.Column("confirmed_at", sa.DateTime(timezone=True)), sa.Column("confirmed_by", sa.String()),
            sa.Column("paid_at", sa.DateTime(timezone=True)), sa.Column("paid_by", sa.String()),
            sa.Column("reopened_at", sa.DateTime(timezone=True)), sa.Column("reopened_by", sa.String()),
            sa.Column("reopen_reason", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("month", name="uq_payroll_sheet_month"),
        )
        op.create_index("ix_payroll_sheets_month", "payroll_sheets", ["month"])
        op.create_index("ix_payroll_sheets_status", "payroll_sheets", ["status"])
    if not inspector.has_table("payroll_items"):
        op.create_table(
            "payroll_items",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("sheet_id", sa.Integer(), nullable=False), sa.Column("employee_id", sa.Integer()),
            sa.Column("employee_code", sa.String()), sa.Column("employee_name", sa.String(), nullable=False),
            sa.Column("department", sa.String()), sa.Column("hire_date", sa.String()),
            sa.Column("payment_method", sa.String(length=32), nullable=False, server_default="alipay"),
            sa.Column("payment_account_encrypted", sa.Text()), sa.Column("payment_account_last4", sa.String(length=8)),
            *[sa.Column(name, sa.Float(), nullable=False, server_default="0") for name in (
                "base_salary", "fixed_performance", "commission", "bonus", "allowance", "reimbursement",
                "absence_deduction", "performance_deduction", "salary_advance_deduction", "other_deduction"
            )],
            sa.Column("payment_status", sa.String(length=24), nullable=False, server_default="pending"),
            sa.Column("payment_date", sa.String()), sa.Column("payment_reference", sa.String()),
            sa.Column("receipt_url", sa.Text()), sa.Column("notes", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("sheet_id", "employee_id", name="uq_payroll_sheet_employee"),
        )
        op.create_index("ix_payroll_items_sheet_id", "payroll_items", ["sheet_id"])
        op.create_index("ix_payroll_items_employee_id", "payroll_items", ["employee_id"])
    if not inspector.has_table("payroll_audit_logs"):
        op.create_table(
            "payroll_audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("sheet_id", sa.Integer(), nullable=False), sa.Column("item_id", sa.Integer()),
            sa.Column("action", sa.String(length=48), nullable=False), sa.Column("actor_id", sa.String(), nullable=False),
            sa.Column("actor_name", sa.String()), sa.Column("actor_role", sa.String(), nullable=False),
            sa.Column("reason", sa.Text()), sa.Column("snapshot_json", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_payroll_audit_logs_sheet_id", "payroll_audit_logs", ["sheet_id"])
        op.create_index("ix_payroll_audit_logs_item_id", "payroll_audit_logs", ["item_id"])
        op.create_index("ix_payroll_audit_logs_action", "payroll_audit_logs", ["action"])


def downgrade() -> None:
    op.drop_table("payroll_audit_logs")
    op.drop_table("payroll_items")
    op.drop_table("payroll_sheets")
