"""Add empty monthly publication packets and immutable request receipts."""
from alembic import op
import sqlalchemy as sa

revision = "e10cb234c570"
down_revision = "df0ba123b469"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("media_monthly_workflows", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), nullable=False), sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("media_monthly_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False), sa.Column("preview_hash", sa.String(64), nullable=False), sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("reviewed_hash", sa.String(64)), sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("task_refs", sa.JSON(), nullable=False), sa.Column("schedule_refs", sa.JSON(), nullable=False), sa.Column("activation", sa.JSON()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "run_id", name="uq_monthly_workflow_run"))
    op.create_index("ix_media_monthly_workflows_customer_id", "media_monthly_workflows", ["customer_id"])
    op.create_table("media_monthly_workflow_requests", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), nullable=False), sa.Column("run_id", sa.Integer(), sa.ForeignKey("media_monthly_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False), sa.Column("kind", sa.String(20), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "request_id", name="uq_monthly_workflow_request"))


def downgrade():
    op.drop_table("media_monthly_workflow_requests")
    op.drop_index("ix_media_monthly_workflows_customer_id", table_name="media_monthly_workflows")
    op.drop_table("media_monthly_workflows")
