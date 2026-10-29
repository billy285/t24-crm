"""Add empty native media operations workflow tables only."""
from alembic import op
import sqlalchemy as sa

revision = "b7c2d9e4a601"
down_revision = "a8d4e2c6f901"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("media_operation_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(255), nullable=False),
        sa.Column("service_progress_id", sa.Integer()),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("assignee_id", sa.Integer(), nullable=False),
        sa.Column("assignee_name", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("material_id", sa.Integer()),
        sa.Column("material_title", sa.String(255)),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("blocked_from_status", sa.String(16)),
        sa.Column("block_reason", sa.Text()),
        sa.Column("review_note", sa.Text()),
        sa.Column("proof_url", sa.Text()),
        sa.Column("proof_material_id", sa.Integer()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("client_request_id", sa.String(64), nullable=False),
        sa.Column("creation_fingerprint", sa.String(64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("created_by_id", "client_request_id", name="uq_media_operation_create_request"),
        sa.CheckConstraint("revision >= 1", name="ck_media_operation_revision"),
        sa.CheckConstraint("status IN ('draft','in_review','ready','completed','blocked')", name="ck_media_operation_status"))
    for field in ("customer_id", "assignee_id", "status", "due_at"):
        op.create_index("ix_media_operation_tasks_" + field, "media_operation_tasks", [field])
    op.create_table("media_operation_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("media_operation_tasks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("actor_name", sa.String(255), nullable=False),
        sa.Column("before_status", sa.String(16)),
        sa.Column("after_status", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(64)),
        sa.Column("request_fingerprint", sa.String(64)),
        sa.Column("note", sa.Text()),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("task_id", "revision", name="uq_media_operation_event_revision"),
        sa.UniqueConstraint("task_id", "request_id", name="uq_media_operation_event_request"))
    op.create_index("ix_media_operation_events_task_id", "media_operation_events", ["task_id"])


def downgrade():
    raise RuntimeError("Preserve content delivery history; use a forward migration")
