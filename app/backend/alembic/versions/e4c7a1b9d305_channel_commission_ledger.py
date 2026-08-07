"""Add channel partner commission subledger.

Revision ID: e4c7a1b9d305
Revises: d2f6a9b4c801
Create Date: 2026-08-08
"""

from alembic import op
import sqlalchemy as sa


revision = "e4c7a1b9d305"
down_revision = "d2f6a9b4c801"
branch_labels = None
depends_on = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column], unique=False)


def upgrade() -> None:
    with op.batch_alter_table("payments") as batch_op:
        batch_op.add_column(sa.Column("engagement_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("business_line_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("product_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_payments_engagement_id", "customer_engagements", ["engagement_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_payments_business_line_id", "business_lines", ["business_line_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_payments_product_id", "product_catalog", ["product_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index("ix_payments_engagement_id", ["engagement_id"], unique=False)
        batch_op.create_index("ix_payments_business_line_id", ["business_line_id"], unique=False)
        batch_op.create_index("ix_payments_product_id", ["product_id"], unique=False)

    op.create_table(
        "sales_partners",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("partner_code", sa.String(length=48), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("partner_type", sa.String(length=24), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="active", nullable=False),
        sa.Column("joined_at", sa.Date(), nullable=False),
        sa.Column("stopped_at", sa.Date(), nullable=True),
        sa.Column("contact_name", sa.String(length=120), nullable=True),
        sa.Column("contact_phone", sa.String(length=64), nullable=True),
        sa.Column("contact_email", sa.String(length=160), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.String(length=64), nullable=True),
        sa.Column("created_by_name", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("partner_code", name="uq_sales_partners_code"),
    )
    _indexes("sales_partners", ("partner_code", "partner_type", "employee_id", "status", "stopped_at"))

    op.create_table(
        "commission_agreements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("partner_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("business_line_id", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("first_order_rate", sa.Float(), nullable=False),
        sa.Column("renewal_rate", sa.Float(), nullable=False),
        sa.Column("activity_decay_json", sa.Text(), nullable=False),
        sa.Column("refund_guard_days", sa.Integer(), server_default="30", nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="active", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.String(length=64), nullable=True),
        sa.Column("created_by_name", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["partner_id"], ["sales_partners.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["business_line_id"], ["business_lines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["product_catalog.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("partner_id", "version", name="uq_commission_agreements_partner_version"),
    )
    _indexes("commission_agreements", ("partner_id", "business_line_id", "product_id", "effective_from", "effective_to", "status"))

    op.create_table(
        "customer_commission_attributions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("engagement_id", sa.Integer(), nullable=True),
        sa.Column("partner_id", sa.Integer(), nullable=False),
        sa.Column("attribution_role", sa.String(length=24), server_default="primary", nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.String(length=64), nullable=True),
        sa.Column("created_by_name", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["engagement_id"], ["customer_engagements.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["partner_id"], ["sales_partners.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes("customer_commission_attributions", ("customer_id", "engagement_id", "partner_id", "attribution_role", "effective_from", "effective_to", "is_active"))

    op.create_table(
        "commission_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("partner_id", sa.Integer(), nullable=False),
        sa.Column("agreement_id", sa.Integer(), nullable=False),
        sa.Column("attribution_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("engagement_id", sa.Integer(), nullable=True),
        sa.Column("payment_id", sa.Integer(), nullable=False),
        sa.Column("refund_id", sa.Integer(), nullable=True),
        sa.Column("original_entry_id", sa.Integer(), nullable=True),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="estimated", nullable=False),
        sa.Column("service_month", sa.String(length=7), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("gross_receipt_amount", sa.Float(), nullable=False),
        sa.Column("eligible_service_amount", sa.Float(), nullable=False),
        sa.Column("contract_rate", sa.Float(), nullable=False),
        sa.Column("inactivity_months", sa.Integer(), server_default="0", nullable=False),
        sa.Column("activity_multiplier", sa.Float(), server_default="1", nullable=False),
        sa.Column("commission_amount", sa.Float(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payable_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payout_reference", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["partner_id"], ["sales_partners.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["agreement_id"], ["commission_agreements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["attribution_id"], ["customer_commission_attributions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["engagement_id"], ["customer_engagements.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["refund_id"], ["finance_refunds.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["original_entry_id"], ["commission_entries.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_commission_entries_idempotency"),
    )
    _indexes("commission_entries", ("partner_id", "agreement_id", "customer_id", "engagement_id", "payment_id", "refund_id", "original_entry_id", "entry_type", "status", "service_month", "occurred_at", "currency", "idempotency_key"))

    op.create_table(
        "commission_status_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("commission_entry_id", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("actor_name", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["commission_entry_id"], ["commission_entries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes("commission_status_events", ("commission_entry_id", "to_status"))


def downgrade() -> None:
    for table, columns in (
        ("commission_status_events", ("commission_entry_id", "to_status")),
        ("commission_entries", ("partner_id", "agreement_id", "customer_id", "engagement_id", "payment_id", "refund_id", "original_entry_id", "entry_type", "status", "service_month", "occurred_at", "currency", "idempotency_key")),
        ("customer_commission_attributions", ("customer_id", "engagement_id", "partner_id", "attribution_role", "effective_from", "effective_to", "is_active")),
        ("commission_agreements", ("partner_id", "business_line_id", "product_id", "effective_from", "effective_to", "status")),
        ("sales_partners", ("partner_code", "partner_type", "employee_id", "status", "stopped_at")),
    ):
        for column in columns:
            op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.drop_table(table)
    with op.batch_alter_table("payments") as batch_op:
        batch_op.drop_index("ix_payments_product_id")
        batch_op.drop_index("ix_payments_business_line_id")
        batch_op.drop_index("ix_payments_engagement_id")
        batch_op.drop_constraint("fk_payments_product_id", type_="foreignkey")
        batch_op.drop_constraint("fk_payments_business_line_id", type_="foreignkey")
        batch_op.drop_constraint("fk_payments_engagement_id", type_="foreignkey")
        batch_op.drop_column("product_id")
        batch_op.drop_column("business_line_id")
        batch_op.drop_column("engagement_id")
