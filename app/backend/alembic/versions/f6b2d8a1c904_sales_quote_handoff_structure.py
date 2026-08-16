"""Structure sales quotes, handoffs and generated deals.

Revision ID: f6b2d8a1c904
Revises: e5f8a1c3d702
Create Date: 2026-08-10
"""

from alembic import op
import sqlalchemy as sa


revision = "f6b2d8a1c904"
down_revision = "e5f8a1c3d702"
branch_labels = None
depends_on = None


def _table_state(table: str) -> tuple[set[str], set[str], set[tuple[str, ...]]]:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(table)}
    indexes = {index["name"] for index in inspector.get_indexes(table)}
    foreign_keys = {
        tuple(foreign_key.get("constrained_columns") or ())
        for foreign_key in inspector.get_foreign_keys(table)
    }
    return columns, indexes, foreign_keys


def upgrade() -> None:
    quote_columns, quote_indexes, quote_foreign_keys = _table_state("sales_quote_requests")
    billing_cycle_was_missing = "billing_cycle" not in quote_columns
    with op.batch_alter_table("sales_quote_requests") as batch_op:
        additions = (
            sa.Column("business_line_id", sa.Integer(), nullable=True),
            sa.Column("product_id", sa.Integer(), nullable=True),
            sa.Column("product_plan_id", sa.Integer(), nullable=True),
            sa.Column("billing_cycle", sa.String(length=24), server_default="one_time", nullable=False),
        )
        for column in additions:
            if column.name not in quote_columns:
                batch_op.add_column(column)
        for column, constraint_name, target_table in (
            ("business_line_id", "fk_sales_quotes_business_line", "business_lines"),
            ("product_id", "fk_sales_quotes_product", "product_catalog"),
            ("product_plan_id", "fk_sales_quotes_product_plan", "product_plans"),
        ):
            if (column,) not in quote_foreign_keys:
                batch_op.create_foreign_key(
                    constraint_name,
                    target_table,
                    [column],
                    ["id"],
                    ondelete="SET NULL",
                )
            index_name = f"ix_sales_quote_requests_{column}"
            if index_name not in quote_indexes:
                batch_op.create_index(index_name, [column], unique=False)
    if billing_cycle_was_missing:
        op.execute(
            "UPDATE sales_quote_requests SET billing_cycle = "
            "CASE WHEN billing_mode = 'subscription' THEN 'monthly' ELSE 'one_time' END"
        )
    else:
        op.execute(
            "UPDATE sales_quote_requests SET billing_cycle = "
            "CASE WHEN billing_mode = 'subscription' THEN 'monthly' ELSE 'one_time' END "
            "WHERE billing_cycle IS NULL OR trim(billing_cycle) = ''"
        )

    handoff_columns, handoff_indexes, handoff_foreign_keys = _table_state("sales_handoff_checklists")
    with op.batch_alter_table("sales_handoff_checklists") as batch_op:
        if "operations_owner_employee_id" not in handoff_columns:
            batch_op.add_column(sa.Column("operations_owner_employee_id", sa.Integer(), nullable=True))
        if "collaborator_employee_ids" not in handoff_columns:
            batch_op.add_column(sa.Column("collaborator_employee_ids", sa.Text(), nullable=True))
        if ("operations_owner_employee_id",) not in handoff_foreign_keys:
            batch_op.create_foreign_key(
                "fk_sales_handoff_operations_owner",
                "employees",
                ["operations_owner_employee_id"],
                ["id"],
                ondelete="SET NULL",
            )
        owner_index = "ix_sales_handoff_checklists_operations_owner_employee_id"
        if owner_index not in handoff_indexes:
            batch_op.create_index(owner_index, ["operations_owner_employee_id"], unique=False)

    deal_columns, deal_indexes, deal_foreign_keys = _table_state("deals")
    with op.batch_alter_table("deals") as batch_op:
        for column in ("engagement_id", "business_line_id", "product_id", "product_plan_id"):
            if column not in deal_columns:
                batch_op.add_column(sa.Column(column, sa.Integer(), nullable=True))
        for column, constraint_name, target_table in (
            ("engagement_id", "fk_deals_engagement", "customer_engagements"),
            ("business_line_id", "fk_deals_business_line", "business_lines"),
            ("product_id", "fk_deals_product", "product_catalog"),
            ("product_plan_id", "fk_deals_product_plan", "product_plans"),
        ):
            if (column,) not in deal_foreign_keys:
                batch_op.create_foreign_key(
                    constraint_name,
                    target_table,
                    [column],
                    ["id"],
                    ondelete="SET NULL",
                )
            index_name = f"ix_deals_{column}"
            if index_name not in deal_indexes:
                batch_op.create_index(index_name, [column], unique=False)


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
