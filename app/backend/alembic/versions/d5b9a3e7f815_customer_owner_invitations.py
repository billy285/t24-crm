"""Explicit owner invitations; legacy permissions await owner confirmation.

Revision ID: d5b9a3e7f815
Revises: c4a8f2d6e714
"""
from alembic import op
import sqlalchemy as sa

revision = "d5b9a3e7f815"
down_revision = "c4a8f2d6e714"
branch_labels = None
depends_on = None


def upgrade():
    # Preserve every prior permission/financial/audit value. Even rows whose
    # granted_by was the owner may have originated from automatic assignment.
    # Additive, inactive defaults never infer a deliberate invitation.
    op.add_column("customer_access_grants", sa.Column("invitation_source", sa.String(32), nullable=False, server_default="legacy"))
    op.add_column("customer_access_grants", sa.Column("invitation_status", sa.String(24), nullable=False, server_default="pending_review"))
    op.add_column("customer_access_grants", sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("customer_access_grants", sa.Column("invited_by_id", sa.String(), nullable=True))
    op.add_column("customer_access_grants", sa.Column("invited_by_name", sa.String(), nullable=True))


def downgrade():
    raise RuntimeError("Invitation boundaries must not fall back to inherited access; use a forward migration")
