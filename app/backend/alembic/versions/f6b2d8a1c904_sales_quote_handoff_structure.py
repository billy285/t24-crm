"""Structure sales quotes, handoffs and generated deals.

Revision ID: f6b2d8a1c904
Revises: e4c7a1b9d305
Create Date: 2026-08-10
"""

from alembic import op
import sqlalchemy as sa


revision = "f6b2d8a1c904"
down_revision = "e4c7a1b9d305"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sales_quote_requests") as batch_op:
        batch_op.add_column(sa.Column("business_line_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("product_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("product_plan_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("billing_cycle", sa.String(length=24), server_default="one_time", nullable=False))
        batch_op.create_foreign_key("fk_sales_quotes_business_line", "business_lines", ["business_line_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_sales_quotes_product", "product_catalog", ["product_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_sales_quotes_product_plan", "product_plans", ["product_plan_id"], ["id"], ondelete="SET NULL")
        for column in ("business_line_id", "product_id", "product_plan_id"):
            batch_op.create_index(f"ix_sales_quote_requests_{column}", [column], unique=False)
    op.execute("UPDATE sales_quote_requests SET billing_cycle = CASE WHEN billing_mode = 'subscription' THEN 'monthly' ELSE 'one_time' END")

    with op.batch_alter_table("sales_handoff_checklists") as batch_op:
        batch_op.add_column(sa.Column("operations_owner_employee_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("collaborator_employee_ids", sa.Text(), nullable=True))
        batch_op.create_foreign_key("fk_sales_handoff_operations_owner", "employees", ["operations_owner_employee_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index("ix_sales_handoff_checklists_operations_owner_employee_id", ["operations_owner_employee_id"], unique=False)

    with op.batch_alter_table("deals") as batch_op:
        batch_op.add_column(sa.Column("engagement_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("business_line_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("product_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("product_plan_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_deals_engagement", "customer_engagements", ["engagement_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_deals_business_line", "business_lines", ["business_line_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_deals_product", "product_catalog", ["product_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_deals_product_plan", "product_plans", ["product_plan_id"], ["id"], ondelete="SET NULL")
        for column in ("engagement_id", "business_line_id", "product_id", "product_plan_id"):
            batch_op.create_index(f"ix_deals_{column}", [column], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("deals") as batch_op:
        for column in ("product_plan_id", "product_id", "business_line_id", "engagement_id"):
            batch_op.drop_index(f"ix_deals_{column}")
        for constraint in ("fk_deals_product_plan", "fk_deals_product", "fk_deals_business_line", "fk_deals_engagement"):
            batch_op.drop_constraint(constraint, type_="foreignkey")
        for column in ("product_plan_id", "product_id", "business_line_id", "engagement_id"):
            batch_op.drop_column(column)
    with op.batch_alter_table("sales_handoff_checklists") as batch_op:
        batch_op.drop_index("ix_sales_handoff_checklists_operations_owner_employee_id")
        batch_op.drop_constraint("fk_sales_handoff_operations_owner", type_="foreignkey")
        batch_op.drop_column("collaborator_employee_ids")
        batch_op.drop_column("operations_owner_employee_id")
    with op.batch_alter_table("sales_quote_requests") as batch_op:
        for column in ("product_plan_id", "product_id", "business_line_id"):
            batch_op.drop_index(f"ix_sales_quote_requests_{column}")
        for constraint in ("fk_sales_quotes_product_plan", "fk_sales_quotes_product", "fk_sales_quotes_business_line"):
            batch_op.drop_constraint(constraint, type_="foreignkey")
        for column in ("billing_cycle", "product_plan_id", "product_id", "business_line_id"):
            batch_op.drop_column(column)
