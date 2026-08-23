"""Add provider-verified RingCentral call synchronization.

Revision ID: d8a4f2c6b901
Revises: b3e7c1d5f902
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa


revision = "d8a4f2c6b901"
down_revision = "b3e7c1d5f902"
branch_labels = None
depends_on = None


def _table_state(table: str) -> tuple[set[str], set[str]]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set(), set()
    columns = {column["name"] for column in inspector.get_columns(table)}
    indexes = {index["name"] for index in inspector.get_indexes(table)}
    return columns, indexes


def upgrade() -> None:
    activity_columns, activity_indexes = _table_state("sales_call_activities")
    with op.batch_alter_table("sales_call_activities") as batch_op:
        if "ringcentral_connected" not in activity_columns:
            batch_op.add_column(sa.Column("ringcentral_connected", sa.Boolean(), nullable=True))
        if "ix_sales_call_activities_ringcentral_connected" not in activity_indexes:
            batch_op.create_index("ix_sales_call_activities_ringcentral_connected", ["ringcentral_connected"], unique=False)

    connection_columns, connection_indexes = _table_state("ringcentral_connections")
    with op.batch_alter_table("ringcentral_connections") as batch_op:
        additions = (
            sa.Column("webhook_subscription_id", sa.String(), nullable=True),
            sa.Column("webhook_subscription_status", sa.String(), nullable=True),
            sa.Column("webhook_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        )
        for column in additions:
            if column.name not in connection_columns:
                batch_op.add_column(column)
        for column in ("webhook_subscription_id", "webhook_subscription_status"):
            index_name = f"ix_ringcentral_connections_{column}"
            if index_name not in connection_indexes:
                batch_op.create_index(index_name, [column], unique=False)

    call_columns, call_indexes = _table_state("ringcentral_call_records")
    if not call_columns:
        op.create_table(
            "ringcentral_call_records",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("provider_key", sa.String(length=255), nullable=False),
            sa.Column("ringcentral_call_id", sa.String(), nullable=True),
            sa.Column("ringcentral_session_id", sa.String(), nullable=True),
            sa.Column("telephony_session_id", sa.String(), nullable=True),
            sa.Column("ringcentral_account_id", sa.String(), nullable=True),
            sa.Column("ringcentral_extension_id", sa.String(), nullable=True),
            sa.Column("sales_employee_id", sa.Integer(), nullable=False),
            sa.Column("sales_employee_name", sa.String(), nullable=True),
            sa.Column("lead_id", sa.Integer(), nullable=True),
            sa.Column("task_id", sa.Integer(), nullable=True),
            sa.Column("activity_id", sa.Integer(), nullable=True),
            sa.Column("direction", sa.String(length=24), nullable=True),
            sa.Column("action", sa.String(length=64), nullable=True),
            sa.Column("provider_status", sa.String(length=64), nullable=True),
            sa.Column("provider_result", sa.String(length=64), nullable=True),
            sa.Column("from_phone", sa.String(length=64), nullable=True),
            sa.Column("to_phone", sa.String(length=64), nullable=True),
            sa.Column("remote_phone", sa.String(length=64), nullable=True),
            sa.Column("connected", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_seconds", sa.Integer(), nullable=True),
            sa.Column("recording_uri", sa.Text(), nullable=True),
            sa.Column("provider_sequence", sa.Integer(), nullable=True),
            sa.Column("last_event_uuid", sa.String(length=128), nullable=True),
            sa.Column("sync_status", sa.String(length=32), nullable=False, server_default="event_received"),
            sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        call_indexes = set()
    for column in (
        "id", "provider_key", "ringcentral_call_id", "ringcentral_session_id", "telephony_session_id",
        "ringcentral_account_id", "ringcentral_extension_id", "sales_employee_id", "lead_id", "task_id",
        "activity_id", "direction", "provider_status", "provider_result", "remote_phone", "connected",
        "started_at", "ended_at", "last_event_uuid", "sync_status", "synced_at",
    ):
        index_name = f"ix_ringcentral_call_records_{column}"
        if index_name not in call_indexes:
            op.create_index(
                index_name,
                "ringcentral_call_records",
                [column],
                unique=column in {"provider_key", "ringcentral_call_id"},
            )


def downgrade() -> None:
    raise RuntimeError(
        "d8a4f2c6b901 is intentionally irreversible: provider call evidence and "
        "employee attribution must not be deleted by a schema downgrade."
    )
