"""Group separately reviewed platform drafts without backfilling old tasks."""
from alembic import op
import sqlalchemy as sa

revision = "acd7c9d0e136"
down_revision = "fbc6b8c9d025"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("media_content_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("created_by_id", "request_id", name="uq_media_content_plan_request"))
    op.create_index("ix_media_content_plans_customer_id", "media_content_plans", ["customer_id"])
    op.create_table("media_content_plan_tasks",
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("media_operation_tasks.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("media_content_plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.UniqueConstraint("plan_id", "platform", name="uq_media_content_plan_platform"))
    op.create_index("ix_media_content_plan_tasks_plan_id", "media_content_plan_tasks", ["plan_id"])


def downgrade():
    raise RuntimeError("Preserve content plans and separately reviewed platform history; forward migration only")
