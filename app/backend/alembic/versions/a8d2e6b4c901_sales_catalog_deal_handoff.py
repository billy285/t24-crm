"""Add fixed-catalog sale handoff receipts; no historical or financial rewrites.

Revision ID: a8d2e6b4c901
Revises: f7d1c5a9b027
"""
from alembic import op
import sqlalchemy as sa

revision = "a8d2e6b4c901"
down_revision = "f7d1c5a9b027"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("sales_deal_plan_policies",
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("product_plans.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("collection_policy", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=False),
        sa.Column("updated_by_name", sa.String(255)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("sales_deal_handoffs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("engagement_id", sa.Integer(), nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("subscription_id", sa.Integer()),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("catalog_token", sa.String(64), nullable=False),
        sa.Column("plan_snapshot", sa.JSON(), nullable=False),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("collection_method", sa.String(32), nullable=False),
        sa.Column("operations_owner_employee_id", sa.Integer(), nullable=False),
        sa.Column("operations_owner_name", sa.String(255), nullable=False),
        sa.Column("operations_status", sa.String(24), nullable=False),
        sa.Column("operations_acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("operations_ack_note", sa.Text()),
        sa.Column("payment_id", sa.Integer(), unique=True),
        sa.Column("payment_status", sa.String(24), nullable=False),
        sa.Column("payment_fingerprint", sa.String(64)),
        sa.Column("payment_confirmed_by_id", sa.Integer()),
        sa.Column("payment_confirmed_by_name", sa.String(255)),
        sa.Column("payment_confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("registered_by_id", sa.Integer(), nullable=False),
        sa.Column("registered_by_name", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("lead_id", name="uq_sales_deal_handoff_lead"),
        sa.UniqueConstraint("idempotency_key", name="uq_sales_deal_handoff_request"))
    for field in ("lead_id", "customer_id", "engagement_id", "operations_owner_employee_id"):
        op.create_index(f"ix_sales_deal_handoffs_{field}", "sales_deal_handoffs", [field])


def downgrade():
    raise RuntimeError("Preserve registered handoff and verification evidence; use a forward migration")
