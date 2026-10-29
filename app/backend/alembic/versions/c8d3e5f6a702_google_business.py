"""Add empty isolated Google Business connection and action tables."""
from alembic import op
import sqlalchemy as sa

revision = "c8d3e5f6a702"
down_revision = "b7c2d9e4a601"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("google_business_connections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.Integer(), nullable=False), sa.Column("label", sa.String(255), nullable=False),
        sa.Column("token_encrypted", sa.Text()), sa.Column("active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("needs_reconnect", sa.Boolean(), nullable=False, server_default="0"), sa.Column("last_error", sa.String(100)),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_google_business_connections_owner_id", "google_business_connections", ["owner_id"])
    op.create_table("google_business_oauth_states",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("cookie_hash", sa.String(64), nullable=False), sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("verifier_encrypted", sa.Text(), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_google_business_oauth_states_expires_at", "google_business_oauth_states", ["expires_at"])
    op.create_table("google_business_bindings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(255), nullable=False), sa.Column("connection_id", sa.Integer(), sa.ForeignKey("google_business_connections.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("location_name", sa.String(200), nullable=False), sa.Column("location_id", sa.String(100), nullable=False), sa.Column("title", sa.String(255), nullable=False),
        sa.Column("address", sa.Text(), nullable=False, server_default=""), sa.Column("active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"), sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("customer_id", name="uq_google_business_customer"), sa.UniqueConstraint("location_name", name="uq_google_business_location"), sa.UniqueConstraint("location_id", name="uq_google_business_global_location"))
    op.create_index("ix_google_business_bindings_customer_id", "google_business_bindings", ["customer_id"])
    op.create_table("google_business_grants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("binding_id", sa.Integer(), sa.ForeignKey("google_business_bindings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False), sa.Column("can_reply", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("can_publish", sa.Boolean(), nullable=False, server_default="0"), sa.Column("granted_by_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("binding_id", "employee_id", name="uq_google_business_grant"))
    for field in ("binding_id", "employee_id"):
        op.create_index("ix_google_business_grants_" + field, "google_business_grants", [field])
    op.create_table("google_business_actions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("binding_id", sa.Integer(), sa.ForeignKey("google_business_bindings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False), sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False), sa.Column("actor_name", sa.String(255), nullable=False),
        sa.Column("task_id", sa.Integer()), sa.Column("target_name", sa.String(255)), sa.Column("payload", sa.JSON()),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"), sa.Column("dispatch_started_at", sa.DateTime(timezone=True)), sa.Column("provider_name", sa.String(255)),
        sa.Column("provider_state", sa.String(32)), sa.Column("provider_url", sa.Text()), sa.Column("message", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("actor_id", "request_id", name="uq_google_business_action_request"))
    for field in ("binding_id", "task_id"):
        op.create_index("ix_google_business_actions_" + field, "google_business_actions", [field])


def downgrade():
    raise RuntimeError("Preserve provider actions and authorization audit; use forward migration")
