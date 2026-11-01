"""Add empty owner-only Google discovery, binding plans, items and receipts."""
from alembic import op
import sqlalchemy as sa

revision = "g32ed456e792"
down_revision = "f21dc345d681"
branch_labels = None
depends_on = None


def times():
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)]


def lease():
    return [sa.Column("lease_token", sa.String(32)), sa.Column("lease_at", sa.DateTime(timezone=True))]


def upgrade():
    op.create_table("google_business_onboarding_catalogs", sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.Integer(), nullable=False), sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer()), sa.Column("revision", sa.Integer(), nullable=False), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("connection_marker", sa.JSON(), nullable=False), sa.Column("locations", sa.JSON(), nullable=False), sa.Column("truncated", sa.Boolean(), nullable=False),
        *lease(), sa.Column("observed_at", sa.DateTime(timezone=True)), sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(40)), sa.Column("message", sa.String(255), nullable=False), *times())
    op.create_table("google_business_onboarding_batches", sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.Integer(), nullable=False), sa.Column("catalog_id", sa.String(32)), sa.Column("customer_id", sa.Integer()),
        sa.Column("kind", sa.String(16), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("preview_hash", sa.String(64), nullable=False), sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("message", sa.String(255), nullable=False), *times())
    op.create_table("google_business_onboarding_items", sa.Column("id", sa.String(32), primary_key=True), sa.Column("batch_id", sa.String(32), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False), sa.Column("position", sa.Integer(), nullable=False), sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("location_name", sa.String(200), nullable=False), sa.Column("request_id", sa.String(36), nullable=False), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False), sa.Column("warnings", sa.JSON(), nullable=False), sa.Column("binding_id", sa.Integer()), *lease(),
        sa.Column("error_code", sa.String(40)), sa.Column("message", sa.String(255), nullable=False), *times(),
        sa.UniqueConstraint("batch_id", "position", name="uq_google_onboarding_position"), sa.UniqueConstraint("owner_id", "request_id", name="uq_google_onboarding_item_request"))
    op.create_index("ix_google_business_onboarding_items_batch_id", "google_business_onboarding_items", ["batch_id"])
    op.create_table("google_business_onboarding_requests", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False), sa.Column("kind", sa.String(16), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(32), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "request_id", name="uq_google_onboarding_request"))


def downgrade():
    op.drop_table("google_business_onboarding_requests")
    op.drop_index("ix_google_business_onboarding_items_batch_id", table_name="google_business_onboarding_items")
    op.drop_table("google_business_onboarding_items")
    op.drop_table("google_business_onboarding_batches")
    op.drop_table("google_business_onboarding_catalogs")
