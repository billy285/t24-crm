"""Add empty owner-only monthly draft profiles, runs and items."""
from alembic import op
import sqlalchemy as sa

revision = "df0ba123b469"
down_revision = "cefa9b12a358"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("media_monthly_profiles", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), nullable=False), sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("public_facts", sa.JSON(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False), sa.Column("menu_item_ids", sa.JSON(), nullable=False), sa.Column("images", sa.JSON(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "customer_id", name="uq_monthly_profile_owner_customer"))
    op.create_table("media_monthly_runs", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), nullable=False), sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("media_monthly_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False), sa.Column("month", sa.String(7), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False), sa.Column("runtime", sa.JSON(), nullable=False), sa.Column("consent", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("revision", sa.Integer(), nullable=False), sa.Column("ai_used", sa.Boolean(), nullable=False),
        sa.Column("message", sa.String(300), nullable=False), sa.Column("adopt_request_id", sa.String(36)), sa.Column("adopt_fingerprint", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "request_id", name="uq_monthly_run_request"), sa.UniqueConstraint("owner_id", "adopt_request_id", name="uq_monthly_adopt_request"),
        sa.UniqueConstraint("owner_id", "customer_id", "month", "input_hash", name="uq_monthly_run_inputs"))
    op.create_index("ix_media_monthly_runs_customer_id", "media_monthly_runs", ["customer_id"])
    op.create_table("media_monthly_items", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("media_monthly_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("slot_id", sa.String(16), nullable=False), sa.Column("proposed_publish_at", sa.DateTime(timezone=True), nullable=False), sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("title", sa.String(200), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("owner_summary", sa.Text(), nullable=False), sa.Column("material_id", sa.Integer()), sa.Column("image_version_id", sa.String(32)), sa.Column("image_sha256", sa.String(64)),
        sa.Column("menu_item_ids", sa.JSON(), nullable=False), sa.Column("quality_warnings", sa.JSON(), nullable=False), sa.Column("revision", sa.Integer(), nullable=False), sa.Column("copy_hash", sa.String(64), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("media_operation_tasks.id", ondelete="RESTRICT"), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "slot_id", name="uq_monthly_item_slot"))
    op.create_index("ix_media_monthly_items_run_id", "media_monthly_items", ["run_id"])


def downgrade():
    op.drop_index("ix_media_monthly_items_run_id", table_name="media_monthly_items")
    op.drop_table("media_monthly_items")
    op.drop_index("ix_media_monthly_runs_customer_id", table_name="media_monthly_runs")
    op.drop_table("media_monthly_runs")
    op.drop_table("media_monthly_profiles")
