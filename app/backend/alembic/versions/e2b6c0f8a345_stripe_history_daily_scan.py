"""Add empty Stripe history recheck state; never seed or alter financial rows."""
from alembic import op
import sqlalchemy as sa

revision = "e2b6c0f8a345"
down_revision = "d1a5b9e7f234"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("stripe_history_scan_states",
        sa.Column("binding_id", sa.Integer(), sa.ForeignKey("stripe_history_bindings.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("scan_for", sa.String(10)),
        sa.Column("completed_for", sa.String(10)),
        sa.Column("target_end", sa.DateTime(timezone=True)),
        sa.Column("range_start", sa.DateTime(timezone=True)),
        sa.Column("range_end", sa.DateTime(timezone=True)),
        sa.Column("cursor", sa.String(255)),
        sa.Column("covered_through", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.String(64)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(40)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_completed_at", sa.DateTime(timezone=True)),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("invoice_count", sa.Integer(), nullable=False),
        sa.Column("discovered_count", sa.Integer(), nullable=False))


def downgrade():
    raise RuntimeError("Preserve scan checkpoints; use a forward migration")
