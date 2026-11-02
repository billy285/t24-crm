"""Add empty owner-consented monthly draft automation policies and receipts."""
from alembic import op
import sqlalchemy as sa

revision = "h43fe567f803"
down_revision = "g32ed456e792"
branch_labels = None
depends_on = None


def times():
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)]


def upgrade():
    op.create_table("media_monthly_automation_policies", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), nullable=False), sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(24), nullable=False), sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("lead_days", sa.Integer(), nullable=False),
        sa.Column("local_time", sa.String(5), nullable=False), sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("profile_revision", sa.Integer(), nullable=False), sa.Column("source_signature", sa.String(64), nullable=False),
        sa.Column("runtime_fingerprint", sa.String(64), nullable=False), sa.Column("first_target_month", sa.String(7), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)), sa.Column("last_checked_at", sa.DateTime(timezone=True)), *times(),
        sa.UniqueConstraint("owner_id", "customer_id", "platform", name="uq_monthly_auto_policy"))
    op.create_index("ix_media_monthly_automation_policies_owner_id", "media_monthly_automation_policies", ["owner_id"])
    op.create_table("media_monthly_automation_occurrences", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("policy_id", sa.Integer(), sa.ForeignKey("media_monthly_automation_policies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False), sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False), sa.Column("customer_name", sa.String(255), nullable=False),
        sa.Column("platform", sa.String(24), nullable=False), sa.Column("month", sa.String(7), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False), sa.Column("source_signature", sa.String(64), nullable=False),
        sa.Column("runtime_fingerprint", sa.String(64), nullable=False), sa.Column("generation_input", sa.JSON()),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("media_monthly_runs.id", ondelete="RESTRICT")),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("message", sa.String(300), nullable=False),
        sa.Column("ai_attempted_at", sa.DateTime(timezone=True)), *times(),
        sa.UniqueConstraint("owner_id", "customer_id", "platform", "month", name="uq_monthly_auto_occurrence"),
        sa.UniqueConstraint("owner_id", "request_id", name="uq_monthly_auto_generation_request"))
    op.create_index("ix_media_monthly_automation_occurrences_owner_id", "media_monthly_automation_occurrences", ["owner_id"])
    op.create_index("ix_media_monthly_automation_occurrences_ai_attempted_at", "media_monthly_automation_occurrences", ["ai_attempted_at"])
    op.create_table("media_monthly_automation_requests", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), nullable=False), sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(24), nullable=False), sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False), sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "request_id", name="uq_monthly_auto_policy_request"))


def downgrade():
    op.drop_table("media_monthly_automation_requests")
    op.drop_index("ix_media_monthly_automation_occurrences_ai_attempted_at", table_name="media_monthly_automation_occurrences")
    op.drop_index("ix_media_monthly_automation_occurrences_owner_id", table_name="media_monthly_automation_occurrences")
    op.drop_table("media_monthly_automation_occurrences")
    op.drop_index("ix_media_monthly_automation_policies_owner_id", table_name="media_monthly_automation_policies")
    op.drop_table("media_monthly_automation_policies")
