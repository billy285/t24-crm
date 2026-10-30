"""Add isolated Google portfolio, scheduling, AI consent and durable drafts."""
from alembic import op
import sqlalchemy as sa

revision = "d9e4f6a7b803"
down_revision = "c8d3e5f6a702"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("google_business_bindings", sa.Column("lifecycle", sa.String(16), nullable=False, server_default="active"))
    op.add_column("google_business_bindings", sa.Column("primary_operator_id", sa.Integer()))
    op.add_column("google_business_bindings", sa.Column("primary_operator_name", sa.String(255)))
    op.add_column("google_business_bindings", sa.Column("lifecycle_reason", sa.String(500)))
    op.add_column("google_business_oauth_states", sa.Column("reconnect_connection_id", sa.Integer()))
    op.add_column("google_business_actions", sa.Column("confirmed_at", sa.DateTime(timezone=True)))
    op.add_column("google_business_actions", sa.Column("approval_id", sa.String(36)))
    op.create_table("google_business_management_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False), sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False), sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_id", "request_id", name="uq_gbp_management_request"))
    op.create_table("google_business_assignment_previews",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False), sa.Column("can_reply", sa.Boolean(), nullable=False),
        sa.Column("can_publish", sa.Boolean(), nullable=False), sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("applied_request_id", sa.String(36)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_google_business_assignment_previews_owner_id", "google_business_assignment_previews", ["owner_id"])
    op.create_table("google_business_schedules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("binding_id", sa.Integer(), sa.ForeignKey("google_business_bindings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False), sa.Column("task_revision", sa.Integer(), nullable=False),
        sa.Column("payload_fingerprint", sa.String(64), nullable=False), sa.Column("operator_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False), sa.Column("request_id", sa.String(36), nullable=False, unique=True),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=False), sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="scheduled"), sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("message", sa.String(255), nullable=False, server_default=""),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("google_business_actions.id", ondelete="RESTRICT")),
        sa.Column("created_by_id", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    for key in ("binding_id", "task_id", "planned_at", "status"):
        op.create_index("ix_google_business_schedules_" + key, "google_business_schedules", [key])
    op.create_table("google_business_ai_consents", sa.Column("owner_id", sa.Integer(), primary_key=True),
        sa.Column("runtime_fingerprint", sa.String(64), nullable=False), sa.Column("active", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("google_business_ai_drafts", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("binding_id", sa.Integer(), sa.ForeignKey("google_business_bindings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False), sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("review_name", sa.String(255), nullable=False), sa.Column("review_version", sa.String(64), nullable=False),
        sa.Column("reply_text", sa.Text(), nullable=False, server_default=""), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("sensitive", sa.Boolean(), nullable=False, server_default="0"), sa.Column("risk_flags", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(255), nullable=False), sa.Column("runtime_fingerprint", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False), sa.Column("approved_reply_hash", sa.String(64)),
        sa.Column("approved_by_id", sa.Integer()), sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("actor_id", "request_id", name="uq_gbp_ai_draft_request"))
    op.create_index("ix_google_business_ai_drafts_binding_id", "google_business_ai_drafts", ["binding_id"])


def downgrade():
    raise RuntimeError("Preserve Google management, scheduling and AI audit history; forward migration only")
