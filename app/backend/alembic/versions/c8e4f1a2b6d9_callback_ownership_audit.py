"""add callback ownership and completion audit fields

Revision ID: c8e4f1a2b6d9
Revises: b7f3a9c1d2e4
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8e4f1a2b6d9"
down_revision: Union[str, Sequence[str], None] = "b7f3a9c1d2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("customer_callbacks"):
        # Fresh installations create ORM tables after migrations. The model
        # already contains these fields, so there is nothing to alter yet.
        return

    existing = {column["name"] for column in inspector.get_columns("customer_callbacks")}
    columns = (
        sa.Column("created_by_employee_id", sa.Integer(), nullable=True),
        sa.Column("created_by_employee_name", sa.String(), nullable=True),
        sa.Column("completed_by_employee_id", sa.Integer(), nullable=True),
        sa.Column("completed_by_employee_name", sa.String(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in columns:
        if column.name not in existing:
            op.add_column("customer_callbacks", column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("customer_callbacks"):
        return

    existing = {column["name"] for column in inspector.get_columns("customer_callbacks")}
    for column_name in (
        "completed_at",
        "completed_by_employee_name",
        "completed_by_employee_id",
        "created_by_employee_name",
        "created_by_employee_id",
    ):
        if column_name in existing:
            op.drop_column("customer_callbacks", column_name)
