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


def _table_state(table: str) -> tuple[set[str], set[str]]:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(table)}
    indexes = {index["name"] for index in inspector.get_indexes(table)}
    return columns, indexes


def upgrade() -> None:
    lead_columns, lead_indexes = _table_state("sales_leads")
    automation_state_was_missing = "automation_state" not in lead_columns
    with op.batch_alter_table("sales_leads") as batch_op:
        additions = (
            sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("automation_state", sa.String(), server_default="eligible", nullable=False),
            sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("contact_attempt_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("rotation_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("last_assigned_sales_id", sa.Integer(), nullable=True),
            sa.Column("last_recycle_reason", sa.String(), nullable=True),
            sa.Column("last_automation_at", sa.DateTime(timezone=True), nullable=True),
        )
        for column in additions:
            if column.name not in lead_columns:
                batch_op.add_column(column)
        for column in ("assigned_at", "automation_state", "cooldown_until", "last_assigned_sales_id"):
            index_name = f"ix_sales_leads_{column}"
            if index_name not in lead_indexes:
                batch_op.create_index(index_name, [column], unique=False)
    op.execute("UPDATE sales_leads SET assigned_at = updated_at WHERE assigned_sales_id IS NOT NULL AND assigned_at IS NULL")
    automation_update = (
        "UPDATE sales_leads SET automation_state = CASE "
        "WHEN do_not_contact = 1 OR is_blacklisted = 1 OR status = 'blocked' THEN 'blocked' "
        "WHEN status IN ('interested', 'appointment', 'follow_up') THEN 'protected' "
        "WHEN status IN ('won', 'lost') THEN 'closed' ELSE 'eligible' END"
    )
    if not automation_state_was_missing:
        automation_update += " WHERE automation_state IS NULL OR trim(automation_state) = ''"
    op.execute(automation_update)

    dial_columns, dial_indexes = _table_state("sales_daily_dial_tasks")
    with op.batch_alter_table("sales_daily_dial_tasks") as batch_op:
        if "queue_category" not in dial_columns:
            batch_op.add_column(sa.Column("queue_category", sa.String(), server_default="new", nullable=False))
        queue_index = "ix_sales_daily_dial_tasks_queue_category"
        if queue_index not in dial_indexes:
            batch_op.create_index(queue_index, ["queue_category"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("sales_daily_dial_tasks") as batch_op:
        batch_op.drop_index("ix_sales_daily_dial_tasks_queue_category")
        batch_op.drop_column("queue_category")
    with op.batch_alter_table("sales_leads") as batch_op:
        for column in ("last_assigned_sales_id", "cooldown_until", "automation_state", "assigned_at"):
            batch_op.drop_index(f"ix_sales_leads_{column}")
        for column in ("last_automation_at", "last_recycle_reason", "last_assigned_sales_id", "rotation_count", "contact_attempt_count", "cooldown_until", "automation_state", "assigned_at"):
            batch_op.drop_column(column)
