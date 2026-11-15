"""Monthly channel commission statements and their daily reconciliation receipt."""

from alembic import op
import sqlalchemy as sa

revision = "k76cd890c136"
down_revision = "j65bc789b025"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "commission_statements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("partner_id", sa.Integer(), sa.ForeignKey("sales_partners.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("paid_amount", sa.Float()),
        sa.Column("paid_snapshot_json", sa.Text()),
        sa.Column("issues_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("payout_reference", sa.String(160)),
        sa.Column("paid_by_id", sa.String(64)),
        sa.Column("paid_by_name", sa.String(160)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("payout_reference", name="uq_commission_statement_payout"),
        sa.UniqueConstraint("month", "partner_id", "currency", name="uq_commission_statement_period"),
    )
    op.create_table(
        "commission_statement_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("statement_id", sa.Integer(), sa.ForeignKey("commission_statements.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("origin_statement_id", sa.Integer(), sa.ForeignKey("commission_statements.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("commission_entries.id", ondelete="RESTRICT"), nullable=False),
        sa.UniqueConstraint("entry_id", name="uq_commission_statement_entry"),
    )
    op.create_index("ix_commission_statement_lines_statement", "commission_statement_lines", ["statement_id"])
    op.create_index("ix_commission_statement_lines_origin", "commission_statement_lines", ["origin_statement_id"])
    op.create_table(
        "commission_statement_cycles",
        sa.Column("business_date", sa.Date(), primary_key=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("commission_statement_cycles")
    op.drop_table("commission_statement_lines")
    op.drop_table("commission_statements")
