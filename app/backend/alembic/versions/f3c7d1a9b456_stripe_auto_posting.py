"""Empty opt-in automatic receipt authorization and job tables only."""
from alembic import op
import sqlalchemy as sa

revision = "f3c7d1a9b456"
down_revision = "e2b6c0f8a345"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("stripe_auto_posting_policies",
        sa.Column("binding_id", sa.Integer(), sa.ForeignKey("stripe_history_bindings.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True)),
        sa.Column("excluded_through_review_id", sa.Integer(), nullable=False),
        sa.Column("authorized_by_id", sa.Integer(), nullable=False),
        sa.Column("authorized_by_name", sa.String(255), nullable=False),
        sa.Column("owner_note", sa.String(1000), nullable=False),
        sa.Column("scope_fingerprint", sa.String(64), nullable=False),
        sa.Column("trial", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("stripe_auto_posting_jobs",
        sa.Column("review_id", sa.Integer(), sa.ForeignKey("stripe_history_invoice_reviews.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("binding_id", sa.Integer(), sa.ForeignKey("stripe_history_bindings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("authorization_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(64)), sa.Column("reason", sa.String(500)),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id", ondelete="RESTRICT")),
        sa.Column("attempt_count", sa.Integer(), nullable=False), sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.String(64)), sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)), sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_stripe_auto_posting_jobs_binding_id", "stripe_auto_posting_jobs", ["binding_id"])
    op.create_index("ix_stripe_auto_posting_jobs_status", "stripe_auto_posting_jobs", ["status"])


def downgrade():
    raise RuntimeError("Preserve receipt authorizations and accounting audit; use a forward migration")
