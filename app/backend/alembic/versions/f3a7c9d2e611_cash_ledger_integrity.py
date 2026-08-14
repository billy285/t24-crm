"""Harden company cash ledger integrity and immutable account snapshots.

Revision ID: f3a7c9d2e611
Revises: e2c6b8d4a105
Create Date: 2026-08-14
"""

from alembic import op
import sqlalchemy as sa


revision = "f3a7c9d2e611"
down_revision = "e2c6b8d4a105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guard idempotent account creation at the database boundary. Inputs are
    # trimmed before persistence and the expression index also handles case-only
    # retries that race across requests/processes.
    op.execute(sa.text(
        """
        CREATE UNIQUE INDEX uq_cash_accounts_active_name_currency
        ON cash_accounts (lower(trim(name)), currency)
        WHERE is_active = 1
        """
    ))

    with op.batch_alter_table("cash_periods") as batch_op:
        batch_op.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))

    with op.batch_alter_table("cash_account_balances") as batch_op:
        batch_op.add_column(sa.Column("account_name", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("account_type", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("masked_identifier", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("confirmed_zero", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.execute(sa.text(
        """
        UPDATE cash_account_balances
        SET account_name = (
                SELECT cash_accounts.name FROM cash_accounts
                WHERE cash_accounts.id = cash_account_balances.account_id
            ),
            account_type = (
                SELECT cash_accounts.account_type FROM cash_accounts
                WHERE cash_accounts.id = cash_account_balances.account_id
            ),
            masked_identifier = (
                SELECT cash_accounts.masked_identifier FROM cash_accounts
                WHERE cash_accounts.id = cash_account_balances.account_id
            )
        """
    ))


def downgrade() -> None:
    with op.batch_alter_table("cash_account_balances") as batch_op:
        batch_op.drop_column("confirmed_zero")
        batch_op.drop_column("masked_identifier")
        batch_op.drop_column("account_type")
        batch_op.drop_column("account_name")

    with op.batch_alter_table("cash_periods") as batch_op:
        batch_op.drop_column("version")

    op.drop_index("uq_cash_accounts_active_name_currency", table_name="cash_accounts")
