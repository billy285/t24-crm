"""Align safe lookup indexes on databases that predate the schema bridge.

Revision ID: f5d8a2c7b901
Revises: f3a7c9d2e611
Create Date: 2026-08-16

Existing production databases were already stamped at the old head when the
fresh-schema bridge was inserted earlier in the chain, so they correctly did
not replay that bridge. Add only the indexes that the old runtime bootstrap
never created. This migration performs no table rebuild and no business-data
update.
"""

from alembic import op
import sqlalchemy as sa


revision = "f5d8a2c7b901"
down_revision = "f3a7c9d2e611"
branch_labels = None
depends_on = None


INDEXES = (
    ("ad_fund_settlements", "id"),
    ("customer_lifecycle_cycles", "id"),
    ("customer_lifecycle_events", "id"),
    ("customers", "sales_lead_id"),
    ("finance_refunds", "id"),
    ("opportunities", "id"),
)


def _ensure_index(table: str, column: str) -> None:
    index_name = f"ix_{table}_{column}"
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        raise RuntimeError(f"Required table {table!r} is missing before Phase 0 index alignment")

    existing = {index["name"]: index for index in inspector.get_indexes(table)}
    if index_name in existing:
        index = existing[index_name]
        actual_columns = tuple(index.get("column_names") or ())
        actual_unique = bool(index.get("unique"))
        if actual_columns != (column,) or actual_unique:
            raise RuntimeError(
                f"Existing index {index_name!r} has columns {actual_columns!r}, "
                f"unique={actual_unique}; expected ({column!r},), unique=False"
            )
        return

    op.create_index(index_name, table, [column], unique=False)


def upgrade() -> None:
    for table, column in INDEXES:
        _ensure_index(table, column)


def downgrade() -> None:
    raise RuntimeError(
        "f5d8a2c7b901 is intentionally irreversible in production. "
        "Roll back the application with the verified pre-release backup; "
        "do not run alembic downgrade."
    )
