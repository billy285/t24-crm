"""Add read-only and read-write customer team access levels.

Revision ID: b3e7c1d5f902
Revises: f5d8a2c7b901
Create Date: 2026-08-19
"""

from alembic import op
import sqlalchemy as sa


revision = "b3e7c1d5f902"
down_revision = "f5d8a2c7b901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customer_access_grants",
        sa.Column("access_level", sa.String(length=20), nullable=False, server_default="read_write"),
    )


def downgrade() -> None:
    with op.batch_alter_table("customer_access_grants") as batch_op:
        batch_op.drop_column("access_level")
