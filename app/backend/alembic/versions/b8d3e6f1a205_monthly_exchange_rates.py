"""Add locked monthly exchange rates for RMB management profit.

Revision ID: b8d3e6f1a205
Revises: a7c5e9f2b104
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa


revision = "b8d3e6f1a205"
down_revision = "a7c5e9f2b104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monthly_exchange_rates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("year_month", sa.String(length=7), nullable=False),
        sa.Column("base_currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("quote_currency", sa.String(length=3), server_default="CNY", nullable=False),
        sa.Column("average_rate", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="locked", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("year_month", "base_currency", "quote_currency", name="uq_monthly_exchange_rate_pair"),
    )
    op.create_index("ix_monthly_exchange_rates_year_month", "monthly_exchange_rates", ["year_month"], unique=False)
    op.create_index("ix_monthly_exchange_rates_status", "monthly_exchange_rates", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_monthly_exchange_rates_status", table_name="monthly_exchange_rates")
    op.drop_index("ix_monthly_exchange_rates_year_month", table_name="monthly_exchange_rates")
    op.drop_table("monthly_exchange_rates")
