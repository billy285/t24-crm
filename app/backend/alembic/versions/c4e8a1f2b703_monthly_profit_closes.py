"""Add immutable monthly RMB profit close snapshots.

Revision ID: c4e8a1f2b703
Revises: b8d3e6f1a205
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa


revision = "c4e8a1f2b703"
down_revision = "b8d3e6f1a205"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monthly_profit_closes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("year_month", sa.String(length=7), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="locked", nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("locked_by", sa.String(length=160), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reopened_by", sa.String(length=160), nullable=True),
        sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reopen_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("year_month", name="uq_monthly_profit_close_month"),
    )
    op.create_index("ix_monthly_profit_closes_year_month", "monthly_profit_closes", ["year_month"], unique=False)
    op.create_index("ix_monthly_profit_closes_status", "monthly_profit_closes", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_monthly_profit_closes_status", table_name="monthly_profit_closes")
    op.drop_index("ix_monthly_profit_closes_year_month", table_name="monthly_profit_closes")
    op.drop_table("monthly_profit_closes")
