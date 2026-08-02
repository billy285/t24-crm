"""add customer lifecycle analytics

Revision ID: e8b1c7d4f902
Revises: d4a9c2e7f601
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8b1c7d4f902"
down_revision: Union[str, Sequence[str], None] = "d4a9c2e7f601"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("customer_lifecycle_cycles"):
        op.create_table(
            "customer_lifecycle_cycles",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("customer_id", sa.Integer(), nullable=False),
            sa.Column("cycle_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("first_payment_id", sa.Integer()),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ended_at", sa.DateTime(timezone=True)),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
            sa.Column("start_source", sa.String(length=24), nullable=False, server_default="payment"),
            sa.Column("start_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("stop_reason", sa.String(length=48)),
            sa.Column("stop_note", sa.Text()),
            sa.Column("confirmed_by_id", sa.String()),
            sa.Column("confirmed_by_name", sa.String()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("customer_id", "cycle_number", name="uq_customer_lifecycle_cycle"),
        )
        for name in ("customer_id", "first_payment_id", "started_at", "ended_at", "status", "stop_reason"):
            op.create_index(f"ix_customer_lifecycle_cycles_{name}", "customer_lifecycle_cycles", [name])
    if not inspector.has_table("customer_lifecycle_events"):
        op.create_table(
            "customer_lifecycle_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("customer_id", sa.Integer(), nullable=False),
            sa.Column("cycle_id", sa.Integer()),
            sa.Column("event_type", sa.String(length=32), nullable=False),
            sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source_type", sa.String(length=32)),
            sa.Column("source_id", sa.Integer()),
            sa.Column("reason_code", sa.String(length=48)),
            sa.Column("note", sa.Text()),
            sa.Column("actor_id", sa.String()),
            sa.Column("actor_name", sa.String()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        for name in ("customer_id", "cycle_id", "event_type", "effective_at", "reason_code"):
            op.create_index(f"ix_customer_lifecycle_events_{name}", "customer_lifecycle_events", [name])


def downgrade() -> None:
    op.drop_table("customer_lifecycle_events")
    op.drop_table("customer_lifecycle_cycles")
