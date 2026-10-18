"""Add independent renewal signals and explicit operational kickoff evidence.

Revision c0f4a8d6e123, additive only, no existing business row/schema changes.
"""
from alembic import op
import sqlalchemy as sa

revision = "c0f4a8d6e123"
down_revision = "b9e3f7c5d012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("service_renewal_signals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("handoff_id", sa.Integer(), sa.ForeignKey("sales_deal_handoffs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subscription_id", sa.String(255), nullable=False),
        sa.Column("resource_key", sa.String(255), nullable=False),
        sa.Column("resource_type", sa.String(24), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("amount_minor", sa.Integer()),
        sa.Column("currency", sa.String(3)), sa.Column("due_date", sa.String(10)), sa.Column("period_end", sa.String(10)),
        sa.Column("latest_event_id", sa.String(255), nullable=False),
        sa.Column("latest_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("resource_key", name="uq_service_renewal_resource"))
    for name in ("handoff_id", "subscription_id"):
        op.create_index(f"ix_service_renewal_signals_{name}", "service_renewal_signals", [name])
    op.create_table("service_renewal_events",
        sa.Column("event_id", sa.String(255), primary_key=True),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("service_renewal_signals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False), sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("stripe_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("service_kickoffs",
        sa.Column("handoff_id", sa.Integer(), sa.ForeignKey("sales_deal_handoffs.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("first_delivery_due_date", sa.String(10), nullable=False),
        sa.Column("template_snapshot", sa.JSON(), nullable=False), sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False), sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("service_kickoff_audits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("handoff_id", sa.Integer(), sa.ForeignKey("service_kickoffs.handoff_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("item_key", sa.String(80)), sa.Column("action", sa.String(24), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False), sa.Column("actor_name", sa.String(255)),
        sa.Column("before", sa.JSON()), sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_service_kickoff_audits_handoff_id", "service_kickoff_audits", ["handoff_id"])


def downgrade():
    raise RuntimeError("Preserve renewal and operational evidence; use a forward migration")
