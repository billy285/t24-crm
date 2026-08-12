"""Add company roadmap and cash safety ledger.

Revision ID: e2c6b8d4a105
Revises: d5a9f7b2c604
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa


revision = "e2c6b8d4a105"
down_revision = "d5a9f7b2c604"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_strategy_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("settings_key", sa.String(length=32), nullable=False),
        sa.Column("target_start_date", sa.Date(), nullable=False),
        sa.Column("target_end_date", sa.Date(), nullable=False),
        sa.Column("five_year_profit_target_cny", sa.Numeric(18, 2), nullable=False),
        sa.Column("monthly_fixed_expense_cny", sa.Numeric(18, 2), nullable=False),
        sa.Column("cash_reserve_months", sa.Integer(), nullable=False),
        sa.Column("default_usd_cny_rate", sa.Numeric(12, 4), nullable=False),
        sa.Column("current_focus", sa.String(length=240), nullable=True),
        sa.Column("updated_by", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("settings_key", name="uq_company_strategy_settings_key"),
    )
    op.create_index("ix_company_strategy_settings_settings_key", "company_strategy_settings", ["settings_key"])

    op.create_table(
        "cash_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("account_type", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("masked_identifier", sa.String(length=80), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cash_accounts_currency", "cash_accounts", ["currency"])
    op.create_index("ix_cash_accounts_is_active", "cash_accounts", ["is_active"])

    op.create_table(
        "cash_periods",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("year_month", sa.String(length=7), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("usd_cny_rate", sa.Numeric(12, 4), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=160), nullable=True),
        sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reopened_by", sa.String(length=160), nullable=True),
        sa.Column("reopen_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("year_month", name="uq_cash_period_year_month"),
    )
    op.create_index("ix_cash_periods_year_month", "cash_periods", ["year_month"])
    op.create_index("ix_cash_periods_status", "cash_periods", ["status"])

    op.create_table(
        "cash_account_balances",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("period_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("rate_to_cny", sa.Numeric(12, 4), nullable=False),
        sa.Column("balance_cny", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["cash_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["period_id"], ["cash_periods.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period_id", "account_id", name="uq_cash_balance_period_account"),
    )
    op.create_index("ix_cash_account_balances_period_id", "cash_account_balances", ["period_id"])
    op.create_index("ix_cash_account_balances_account_id", "cash_account_balances", ["account_id"])

    op.create_table(
        "cash_restrictions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("period_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("description", sa.String(length=240), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("rate_to_cny", sa.Numeric(12, 4), nullable=False),
        sa.Column("amount_cny", sa.Numeric(18, 2), nullable=False),
        sa.Column("source_ref", sa.String(length=160), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["period_id"], ["cash_periods.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period_id", "source_ref", name="uq_cash_restriction_period_source"),
    )
    op.create_index("ix_cash_restrictions_period_id", "cash_restrictions", ["period_id"])
    op.create_index("ix_cash_restrictions_category", "cash_restrictions", ["category"])

    op.create_table(
        "cash_audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("period_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=48), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("actor_name", sa.String(length=160), nullable=True),
        sa.Column("actor_role", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("snapshot_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["period_id"], ["cash_periods.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cash_audit_logs_period_id", "cash_audit_logs", ["period_id"])
    op.create_index("ix_cash_audit_logs_action", "cash_audit_logs", ["action"])

    op.create_table(
        "strategy_recommendation_decisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("recommendation_key", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("recommended_action", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("next_review_date", sa.Date(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("decided_by_id", sa.String(length=64), nullable=True),
        sa.Column("decided_by_name", sa.String(length=160), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recommendation_key", name="uq_strategy_recommendation_key"),
    )
    op.create_index("ix_strategy_recommendation_decisions_recommendation_key", "strategy_recommendation_decisions", ["recommendation_key"])
    op.create_index("ix_strategy_recommendation_decisions_status", "strategy_recommendation_decisions", ["status"])
    op.create_index("ix_strategy_recommendation_decisions_task_id", "strategy_recommendation_decisions", ["task_id"])


def downgrade() -> None:
    op.drop_table("strategy_recommendation_decisions")
    op.drop_table("cash_audit_logs")
    op.drop_table("cash_restrictions")
    op.drop_table("cash_account_balances")
    op.drop_table("cash_periods")
    op.drop_table("cash_accounts")
    op.drop_table("company_strategy_settings")
