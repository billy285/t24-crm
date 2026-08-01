"""add refunds and ad fund settlements

Revision ID: b7f3a9c1d2e4
Revises: 3a4981e5cf2d
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7f3a9c1d2e4"
down_revision: Union[str, Sequence[str], None] = "3a4981e5cf2d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "finance_refunds",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("payment_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(), nullable=True),
        sa.Column("refund_amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("refund_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_refund_id", sa.String(), nullable=True),
        sa.Column("stripe_fee_refunded_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("recorded_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("payment_id", "customer_id", "refund_date", "provider_refund_id", "status", "user_id"):
        op.create_index(f"ix_finance_refunds_{column}", "finance_refunds", [column])

    op.create_table(
        "ad_fund_settlements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(), nullable=True),
        sa.Column("year_month", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("opening_balance", sa.Float(), nullable=False, server_default="0"),
        sa.Column("funds_received", sa.Float(), nullable=False, server_default="0"),
        sa.Column("actual_ad_spend", sa.Float(), nullable=False, server_default="0"),
        sa.Column("customer_refund_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("recognized_spread_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("adjustment_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("closing_balance", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("recorded_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", "year_month", "currency", name="uq_ad_fund_customer_month_currency"),
    )
    for column in ("customer_id", "year_month", "status", "user_id"):
        op.create_index(f"ix_ad_fund_settlements_{column}", "ad_fund_settlements", [column])


def downgrade() -> None:
    op.drop_table("ad_fund_settlements")
    op.drop_table("finance_refunds")
