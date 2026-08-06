"""Add product plans, opportunities and subscription service scope.

Revision ID: d2f6a9b4c801
Revises: c9f4d2a7e615
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "d2f6a9b4c801"
down_revision = "c9f4d2a7e615"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_plans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("version_label", sa.String(length=80), nullable=True),
        sa.Column("pricing_status", sa.String(length=24), server_default="draft", nullable=False),
        sa.Column("standard_price", sa.Float(), nullable=True),
        sa.Column("default_currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("default_billing_cycle", sa.String(length=24), nullable=True),
        sa.Column("platform_limit", sa.Integer(), nullable=True),
        sa.Column("scope_type", sa.String(length=32), server_default="generic", nullable=False),
        sa.Column("entitlements_json", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["product_catalog.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_product_plans_code"),
    )
    for column in ("product_id", "code", "pricing_status", "scope_type", "is_active"):
        op.create_index(f"ix_product_plans_{column}", "product_plans", [column], unique=False)

    op.create_table(
        "opportunities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("business_line_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("product_plan_id", sa.Integer(), nullable=True),
        sa.Column("opportunity_code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("stage", sa.String(length=32), server_default="initial", nullable=False),
        sa.Column("status", sa.String(length=24), server_default="open", nullable=False),
        sa.Column("estimated_amount", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("probability", sa.Integer(), server_default="10", nullable=False),
        sa.Column("owner_employee_id", sa.Integer(), nullable=True),
        sa.Column("owner_name", sa.String(length=160), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("selected_platforms", sa.Text(), nullable=True),
        sa.Column("service_scope_json", sa.Text(), nullable=True),
        sa.Column("expected_close_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_follow_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_follow_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pause_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lost_reason", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("converted_deal_id", sa.Integer(), nullable=True),
        sa.Column("converted_engagement_id", sa.Integer(), nullable=True),
        sa.Column("converted_subscription_id", sa.Integer(), nullable=True),
        sa.Column("won_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lost_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["business_line_id"], ["business_lines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["product_catalog.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_plan_id"], ["product_plans.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("opportunity_code", name="uq_opportunities_code"),
        sa.UniqueConstraint("converted_deal_id", name="uq_opportunities_converted_deal_id"),
        sa.UniqueConstraint("converted_engagement_id", name="uq_opportunities_converted_engagement_id"),
        sa.UniqueConstraint("converted_subscription_id", name="uq_opportunities_converted_subscription_id"),
    )
    for column in (
        "customer_id", "business_line_id", "product_id", "product_plan_id", "opportunity_code",
        "stage", "status", "owner_employee_id", "source", "expected_close_date", "next_follow_up_at", "pause_until",
    ):
        op.create_index(f"ix_opportunities_{column}", "opportunities", [column], unique=False)

    with op.batch_alter_table("customer_engagements") as batch_op:
        batch_op.add_column(sa.Column("product_plan_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("selected_platforms", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("service_scope_json", sa.Text(), nullable=True))
        batch_op.create_foreign_key("fk_customer_engagements_product_plan_id", "product_plans", ["product_plan_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index("ix_customer_engagements_product_plan_id", ["product_plan_id"], unique=False)

    with op.batch_alter_table("subscriptions") as batch_op:
        batch_op.add_column(sa.Column("opportunity_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("engagement_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("business_line_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("product_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("product_plan_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("list_price_snapshot", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("pricing_source", sa.String(length=24), nullable=True))
        batch_op.add_column(sa.Column("selected_platforms", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("service_scope_json", sa.Text(), nullable=True))
        batch_op.create_foreign_key("fk_subscriptions_opportunity_id", "opportunities", ["opportunity_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_subscriptions_engagement_id", "customer_engagements", ["engagement_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_subscriptions_business_line_id", "business_lines", ["business_line_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_subscriptions_product_id", "product_catalog", ["product_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_subscriptions_product_plan_id", "product_plans", ["product_plan_id"], ["id"], ondelete="SET NULL")
        for column in ("opportunity_id", "engagement_id", "business_line_id", "product_id", "product_plan_id"):
            batch_op.create_index(f"ix_subscriptions_{column}", [column], unique=False)

    with op.batch_alter_table("deals") as batch_op:
        batch_op.add_column(sa.Column("opportunity_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_deals_opportunity_id", "opportunities", ["opportunity_id"], ["id"], ondelete="SET NULL")
        batch_op.create_unique_constraint("uq_deals_opportunity_id", ["opportunity_id"])
        batch_op.create_index("ix_deals_opportunity_id", ["opportunity_id"], unique=False)

    with op.batch_alter_table("follow_ups") as batch_op:
        batch_op.add_column(sa.Column("opportunity_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_follow_ups_opportunity_id", "opportunities", ["opportunity_id"], ["id"], ondelete="CASCADE")
        batch_op.create_index("ix_follow_ups_opportunity_id", ["opportunity_id"], unique=False)

    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column("opportunity_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_tasks_opportunity_id", "opportunities", ["opportunity_id"], ["id"], ondelete="SET NULL")
        batch_op.create_unique_constraint("uq_tasks_opportunity_id", ["opportunity_id"])
        batch_op.create_index("ix_tasks_opportunity_id", ["opportunity_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_index("ix_tasks_opportunity_id")
        batch_op.drop_constraint("uq_tasks_opportunity_id", type_="unique")
        batch_op.drop_constraint("fk_tasks_opportunity_id", type_="foreignkey")
        batch_op.drop_column("opportunity_id")

    with op.batch_alter_table("follow_ups") as batch_op:
        batch_op.drop_index("ix_follow_ups_opportunity_id")
        batch_op.drop_constraint("fk_follow_ups_opportunity_id", type_="foreignkey")
        batch_op.drop_column("opportunity_id")

    with op.batch_alter_table("deals") as batch_op:
        batch_op.drop_index("ix_deals_opportunity_id")
        batch_op.drop_constraint("uq_deals_opportunity_id", type_="unique")
        batch_op.drop_constraint("fk_deals_opportunity_id", type_="foreignkey")
        batch_op.drop_column("opportunity_id")

    with op.batch_alter_table("subscriptions") as batch_op:
        for column in ("product_plan_id", "product_id", "business_line_id", "engagement_id", "opportunity_id"):
            batch_op.drop_index(f"ix_subscriptions_{column}")
        for constraint in (
            "fk_subscriptions_product_plan_id", "fk_subscriptions_product_id", "fk_subscriptions_business_line_id",
            "fk_subscriptions_engagement_id", "fk_subscriptions_opportunity_id",
        ):
            batch_op.drop_constraint(constraint, type_="foreignkey")
        for column in (
            "service_scope_json", "selected_platforms", "pricing_source", "list_price_snapshot",
            "product_plan_id", "product_id", "business_line_id", "engagement_id", "opportunity_id",
        ):
            batch_op.drop_column(column)

    with op.batch_alter_table("customer_engagements") as batch_op:
        batch_op.drop_index("ix_customer_engagements_product_plan_id")
        batch_op.drop_constraint("fk_customer_engagements_product_plan_id", type_="foreignkey")
        batch_op.drop_column("service_scope_json")
        batch_op.drop_column("selected_platforms")
        batch_op.drop_column("product_plan_id")

    for column in (
        "pause_until", "next_follow_up_at", "expected_close_date", "source", "owner_employee_id", "status", "stage",
        "opportunity_code", "product_plan_id", "product_id", "business_line_id", "customer_id",
    ):
        op.drop_index(f"ix_opportunities_{column}", table_name="opportunities")
    op.drop_table("opportunities")

    for column in ("is_active", "scope_type", "pricing_status", "code", "product_id"):
        op.drop_index(f"ix_product_plans_{column}", table_name="product_plans")
    op.drop_table("product_plans")
