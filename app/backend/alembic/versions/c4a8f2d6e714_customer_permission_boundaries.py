"""Owner-controlled customer sharing and private content boundaries.

Revision ID: c4a8f2d6e714
Revises: b3e7c1d9a614
"""
from alembic import op
import sqlalchemy as sa

revision = "c4a8f2d6e714"
down_revision = "b3e7c1d9a614"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("customer_access_grants", sa.Column("scopes", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("customer_access_grants", sa.Column("finance_access", sa.String(20), nullable=False, server_default="none"))
    for name in ("can_export", "can_delete", "can_reassign"):
        op.add_column("customer_access_grants", sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()))
    # Existing read/write grants are retained. No finance, export or deletion
    # permission is inferred from sharing, role or sales ownership.
    with op.batch_alter_table("customer_access_grants") as batch:
        batch.alter_column("access_level", existing_type=sa.String(20), server_default="read_only")
    op.add_column("customers", sa.Column("private_notes", sa.String(), nullable=True))
    op.add_column("customer_materials", sa.Column("visibility", sa.String(20), nullable=False, server_default="team"))
    op.create_table(
        "customer_access_audits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("actor_name", sa.String(), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_customer_access_audits_customer_id", "customer_access_audits", ["customer_id"])
    op.create_table(
        "customer_record_audits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("module", sa.String(32), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("actor_name", sa.String(255), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_customer_record_audits_customer_id", "customer_record_audits", ["customer_id"])


def downgrade():
    raise RuntimeError("Customer permission denials and private audit data must be retained; use a forward migration")
