"""Add reusable sales lead automation cycle.

Revision ID: a7c5e9f2b104
Revises: f6b2d8a1c904
Create Date: 2026-08-10
"""

from alembic import op
import sqlalchemy as sa


revision = "a7c5e9f2b104"
down_revision = "f6b2d8a1c904"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sales_leads") as batch_op:
        batch_op.add_column(sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("automation_state", sa.String(), server_default="eligible", nullable=False))
        batch_op.add_column(sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("contact_attempt_count", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("rotation_count", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("last_assigned_sales_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("last_recycle_reason", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("last_automation_at", sa.DateTime(timezone=True), nullable=True))
        for column in ("assigned_at", "automation_state", "cooldown_until", "last_assigned_sales_id"):
            batch_op.create_index(f"ix_sales_leads_{column}", [column], unique=False)
    op.execute("UPDATE sales_leads SET assigned_at = updated_at WHERE assigned_sales_id IS NOT NULL AND assigned_at IS NULL")
    op.execute("UPDATE sales_leads SET automation_state = CASE WHEN do_not_contact = 1 OR is_blacklisted = 1 OR status = 'blocked' THEN 'blocked' WHEN status IN ('interested', 'appointment', 'follow_up') THEN 'protected' WHEN status IN ('won', 'lost') THEN 'closed' ELSE 'eligible' END")

    with op.batch_alter_table("sales_daily_dial_tasks") as batch_op:
        batch_op.add_column(sa.Column("queue_category", sa.String(), server_default="new", nullable=False))
        batch_op.create_index("ix_sales_daily_dial_tasks_queue_category", ["queue_category"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("sales_daily_dial_tasks") as batch_op:
        batch_op.drop_index("ix_sales_daily_dial_tasks_queue_category")
        batch_op.drop_column("queue_category")
    with op.batch_alter_table("sales_leads") as batch_op:
        for column in ("last_assigned_sales_id", "cooldown_until", "automation_state", "assigned_at"):
            batch_op.drop_index(f"ix_sales_leads_{column}")
        for column in ("last_automation_at", "last_recycle_reason", "last_assigned_sales_id", "rotation_count", "contact_attempt_count", "cooldown_until", "automation_state", "assigned_at"):
            batch_op.drop_column(column)
