"""Add customer-specific package name to engagements.

Revision ID: b7e3a1d5f804
Revises: a6d2f9c4e701
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa


revision = "b7e3a1d5f804"
down_revision = "a6d2f9c4e701"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("customer_engagements") as batch_op:
        batch_op.add_column(sa.Column("package_name", sa.String(length=160), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("customer_engagements") as batch_op:
        batch_op.drop_column("package_name")
