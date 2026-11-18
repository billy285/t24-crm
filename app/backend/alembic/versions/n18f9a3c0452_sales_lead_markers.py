"""Persist private lead stars and shared sales priorities."""

import sqlalchemy as sa
from alembic import op

revision = "n18f9a3c0452"
down_revision = "m18f9a3c0451"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sales_lead_stars",
        sa.Column("user_id", sa.String(255), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("sales_leads.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sales_lead_stars_lead_id", "sales_lead_stars", ["lead_id"])
    op.create_table(
        "sales_lead_priorities",
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("sales_leads.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("marked_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("sales_lead_priorities")
    op.drop_table("sales_lead_stars")
