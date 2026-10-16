"""Add sales-only payment references, signed observations and owner evidence.

No financial/history/permissions rewrite. Revision b9e3f7c5d012.
"""
from alembic import op
import sqlalchemy as sa

revision = "b9e3f7c5d012"
down_revision = "a8d2e6b4c901"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("sales_payment_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("handoff_id", sa.Integer(), sa.ForeignKey("sales_deal_handoffs.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("reference", sa.String(80), nullable=False, unique=True),
        sa.Column("link_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("sales_stripe_observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("sales_payment_requests.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("session_id", sa.String(255), nullable=False, unique=True),
        sa.Column("subscription_id", sa.String(255)),
        sa.Column("invoice_id", sa.String(255)),
        sa.Column("payment_intent_id", sa.String(255)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("match_issues", sa.JSON(), nullable=False),
        sa.Column("service_minor", sa.Integer()), sa.Column("tax_minor", sa.Integer()),
        sa.Column("gross_minor", sa.Integer()), sa.Column("currency", sa.String(3)),
        sa.Column("payer_business_name", sa.String(255)),
        sa.Column("payer_name", sa.String(255)), sa.Column("payer_email", sa.String(320)),
        sa.Column("stripe_created_at", sa.DateTime(timezone=True)),
        sa.Column("checkout_completed_at", sa.DateTime(timezone=True)),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("latest_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    for name in ("request_id", "subscription_id", "invoice_id", "payment_intent_id"):
        op.create_index(f"ix_sales_stripe_observations_{name}", "sales_stripe_observations", [name])
    op.create_table("sales_stripe_events",
        sa.Column("event_id", sa.String(255), primary_key=True),
        sa.Column("observation_id", sa.Integer(), sa.ForeignKey("sales_stripe_observations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("stripe_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("sales_receipt_evidence",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("handoff_id", sa.Integer(), sa.ForeignKey("sales_deal_handoffs.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("observation_id", sa.Integer(), sa.ForeignKey("sales_stripe_observations.id", ondelete="RESTRICT"), unique=True),
        sa.Column("transaction_reference_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("service_minor", sa.Integer(), nullable=False),
        sa.Column("tax_minor", sa.Integer(), nullable=False), sa.Column("fee_minor", sa.Integer(), nullable=False),
        sa.Column("gross_minor", sa.Integer(), nullable=False), sa.Column("net_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False), sa.Column("payment_date", sa.String(10), nullable=False),
        sa.Column("verified_by_id", sa.Integer(), nullable=False), sa.Column("verified_by_name", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))


def downgrade():
    raise RuntimeError("Preserve payment request and owner reconciliation evidence; use a forward migration")
