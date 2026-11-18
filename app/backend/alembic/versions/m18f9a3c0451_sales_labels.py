"""Add shared sales label catalog and merchant or lead links."""

from alembic import op
import sqlalchemy as sa

revision = "m18f9a3c0451"
down_revision = "k76cd890c136"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sales_labels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("normalized_name", sa.String(180), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("industry", sa.String(16), nullable=False, server_default="all"),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("kind", "normalized_name", name="uq_sales_labels_kind_name"),
        sa.CheckConstraint("kind IN ('source', 'provider', 'operation')", name="ck_sales_labels_kind"),
    )
    op.create_table(
        "sales_label_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label_id", sa.Integer(), sa.ForeignKey("sales_labels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("merchant_id", sa.Integer(), sa.ForeignKey("merchant_pool.id", ondelete="CASCADE")),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("sales_leads.id", ondelete="CASCADE")),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confirmed_by", sa.Integer()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("import_batch_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("(merchant_id IS NULL) <> (lead_id IS NULL)", name="ck_sales_label_assignment_target"),
        sa.UniqueConstraint("merchant_id", "label_id", name="uq_sales_label_merchant"),
        sa.UniqueConstraint("lead_id", "label_id", name="uq_sales_label_lead"),
    )
    op.create_index("ix_sales_label_target", "sales_label_assignments", ["label_id", "merchant_id", "lead_id"])


def downgrade():
    op.drop_table("sales_label_assignments")
    op.drop_table("sales_labels")
