"""Add empty private asset studio profiles, jobs and request receipts."""
from alembic import op
import sqlalchemy as sa

revision = "f21dc345d681"
down_revision = "e10cb234c570"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("media_asset_profiles", sa.Column("owner_id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), primary_key=True), sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("media_asset_jobs", sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.Integer(), nullable=False), sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False), sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False), sa.Column("lease_token", sa.String(32)), sa.Column("lease_at", sa.DateTime(timezone=True)),
        sa.Column("output", sa.JSON()), sa.Column("adoption", sa.JSON()), sa.Column("error_code", sa.String(40)),
        sa.Column("message", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("owner_id", "request_id", name="uq_media_asset_job_request"))
    op.create_index("ix_media_asset_jobs_customer_id", "media_asset_jobs", ["customer_id"])
    op.create_table("media_asset_requests", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False), sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False), sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("owner_id", "request_id", name="uq_media_asset_request"))


def downgrade():
    op.drop_table("media_asset_requests")
    op.drop_index("ix_media_asset_jobs_customer_id", table_name="media_asset_jobs")
    op.drop_table("media_asset_jobs")
    op.drop_table("media_asset_profiles")
