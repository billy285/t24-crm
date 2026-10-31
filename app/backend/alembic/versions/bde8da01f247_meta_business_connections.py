"""Add empty, independent owner-only Meta connection tables."""
from alembic import op
import sqlalchemy as sa

revision = "bde8da01f247"
down_revision = "acd7c9d0e136"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("meta_business_connections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.Integer(), nullable=False), sa.Column("label", sa.String(255), nullable=False),
        sa.Column("token_encrypted", sa.Text()), sa.Column("granted_scopes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("needs_reconnect", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_error", sa.String(40)), sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_meta_business_connections_owner_id", "meta_business_connections", ["owner_id"])
    op.create_table("meta_business_oauth_states",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.Integer(), nullable=False), sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False), sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("cookie_hash", sa.String(64), nullable=False), sa.Column("flow_encrypted", sa.Text(), nullable=False),
        sa.Column("reconnect_connection_id", sa.Integer()), sa.Column("expected_revision", sa.Integer()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "request_id", name="uq_meta_oauth_request"))
    op.create_index("ix_meta_business_oauth_states_expires_at", "meta_business_oauth_states", ["expires_at"])
    op.create_table("meta_business_assets",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("connection_id", sa.Integer(), sa.ForeignKey("meta_business_connections.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("connection_revision", sa.Integer(), nullable=False), sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("external_id", sa.String(80), nullable=False), sa.Column("page_id", sa.String(80), nullable=False),
        sa.Column("name", sa.String(255), nullable=False), sa.Column("username", sa.String(255)),
        sa.Column("linked_page_name", sa.String(255)), sa.Column("observations", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="1"), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("platform IN ('facebook','instagram')", name="ck_meta_asset_platform"))
    op.create_index("ix_meta_business_assets_connection_id", "meta_business_assets", ["connection_id"])
    op.create_table("meta_business_bindings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False), sa.Column("customer_name", sa.String(255), nullable=False),
        sa.Column("connection_id", sa.Integer(), sa.ForeignKey("meta_business_connections.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("connection_revision", sa.Integer(), nullable=False), sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("external_id", sa.String(80), nullable=False), sa.Column("page_id", sa.String(80), nullable=False),
        sa.Column("asset_name", sa.String(255), nullable=False), sa.Column("asset_username", sa.String(255)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="1"), sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("platform IN ('facebook','instagram')", name="ck_meta_binding_platform"))
    for field in ("owner_id", "customer_id"):
        op.create_index("ix_meta_business_bindings_" + field, "meta_business_bindings", [field])
    op.create_index("uq_meta_active_customer_platform", "meta_business_bindings", ["customer_id", "platform"], unique=True,
                    sqlite_where=sa.text("active = 1"), postgresql_where=sa.text("active"))
    op.create_index("uq_meta_active_global_asset", "meta_business_bindings", ["platform", "external_id"], unique=True,
                    sqlite_where=sa.text("active = 1"), postgresql_where=sa.text("active"))
    op.create_table("meta_business_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("binding_id", sa.Integer(), sa.ForeignKey("meta_business_bindings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "request_id", name="uq_meta_management_request"))


def downgrade():
    raise RuntimeError("Preserve Meta authorization history; use an explicitly reviewed forward migration")
