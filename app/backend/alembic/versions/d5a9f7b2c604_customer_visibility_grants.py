"""Add explicit customer visibility grants.

Revision ID: d5a9f7b2c604
Revises: c4e8a1f2b703
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa


revision = "d5a9f7b2c604"
down_revision = "c4e8a1f2b703"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_access_grants",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("granted_by_id", sa.String(), nullable=True),
        sa.Column("granted_by_name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", "employee_id", name="uq_customer_access_grant"),
    )
    op.create_index("ix_customer_access_grants_customer_id", "customer_access_grants", ["customer_id"], unique=False)
    op.create_index("ix_customer_access_grants_employee_id", "customer_access_grants", ["employee_id"], unique=False)

    # Preserve current work assignments when explicit visibility starts. The
    # owner can later remove any of these grants from Customer Management.
    op.execute("""
        INSERT INTO customer_access_grants (customer_id, employee_id, granted_by_name)
        SELECT DISTINCT id, sales_employee_id, 'system-migration'
        FROM customers
        WHERE sales_employee_id IS NOT NULL
        ON CONFLICT(customer_id, employee_id) DO NOTHING
    """)
    op.execute("""
        INSERT INTO customer_access_grants (customer_id, employee_id, granted_by_name)
        SELECT DISTINCT c.id, e.id, 'system-migration'
        FROM customers c
        JOIN employees e ON TRIM(c.sales_person) = TRIM(e.name)
        WHERE c.sales_person IS NOT NULL AND TRIM(c.sales_person) <> ''
        ON CONFLICT(customer_id, employee_id) DO NOTHING
    """)
    op.execute("""
        INSERT INTO customer_access_grants (customer_id, employee_id, granted_by_name)
        SELECT DISTINCT customer_id, owner_employee_id, 'system-migration'
        FROM customer_engagements
        WHERE owner_employee_id IS NOT NULL
        ON CONFLICT(customer_id, employee_id) DO NOTHING
    """)
    op.execute("""
        INSERT INTO customer_access_grants (customer_id, employee_id, granted_by_name)
        SELECT DISTINCT sp.customer_id, e.id, 'system-migration'
        FROM service_progresses sp
        JOIN employees e ON TRIM(sp.ops_person) = TRIM(e.name)
        WHERE sp.customer_id IS NOT NULL AND sp.ops_person IS NOT NULL AND TRIM(sp.ops_person) <> ''
        ON CONFLICT(customer_id, employee_id) DO NOTHING
    """)


def downgrade() -> None:
    op.drop_index("ix_customer_access_grants_employee_id", table_name="customer_access_grants")
    op.drop_index("ix_customer_access_grants_customer_id", table_name="customer_access_grants")
    op.drop_table("customer_access_grants")
