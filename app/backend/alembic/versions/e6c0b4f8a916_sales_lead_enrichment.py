"""Add sales-only profiles, revision audit and actual dial snapshots.

Revision ID: e6c0b4f8a916
Revises: d5b9a3e7f815
"""
from alembic import op
import sqlalchemy as sa

revision = "e6c0b4f8a916"
down_revision = "d5b9a3e7f815"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("sales_lead_enrichments",
        sa.Column("lead_id", sa.Integer(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("contacts", sa.JSON(), nullable=False),
        sa.Column("preferred_contact_id", sa.String(64)),
        sa.Column("interest_product_ids", sa.JSON(), nullable=False),
        sa.Column("need_summary", sa.Text()), sa.Column("best_contact_time", sa.String(300)),
        sa.Column("verification", sa.String(16), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=False), sa.Column("updated_by_name", sa.String(255)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("sales_lead_enrichment_audits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("lead_id", sa.Integer(), nullable=False), sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False), sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False), sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False), sa.Column("actor_name", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("lead_id", "revision", name="uq_sales_enrichment_revision"))
    op.create_index("ix_sales_lead_enrichment_audits_lead_id", "sales_lead_enrichment_audits", ["lead_id"])
    op.create_table("sales_dial_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.Integer(), nullable=False), sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("sales_employee_id", sa.Integer(), nullable=False), sa.Column("dial_phone", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False))
    for field in ("task_id", "lead_id", "sales_employee_id", "started_at"):
        op.create_index("ix_sales_dial_attempts_" + field, "sales_dial_attempts", [field])
    op.add_column("sales_daily_dial_tasks", sa.Column("dial_phone", sa.String(64), nullable=True))
    op.add_column("sales_call_activities", sa.Column("dial_phone", sa.String(64), nullable=True))
    op.add_column("sales_call_activities", sa.Column("dial_attempt_id", sa.Integer(), nullable=True))
    op.create_index("ix_sales_call_activities_dial_attempt_id", "sales_call_activities", ["dial_attempt_id"], unique=True)


def downgrade():
    raise RuntimeError("Preserve sales enrichment and historical dial snapshots; use a forward migration")
