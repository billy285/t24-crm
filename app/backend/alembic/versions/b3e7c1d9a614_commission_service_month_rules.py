"""Version commission service-month rules without rewriting historical entries.

Revision ID: b3e7c1d9a614
Revises: ab6d8e2f0411
"""
from alembic import op
import sqlalchemy as sa
revision = "b3e7c1d9a614"
down_revision = "ab6d8e2f0411"
branch_labels = None
depends_on = None


def upgrade():
    duplicates = op.get_bind().execute(sa.text("SELECT employee_id FROM sales_partners WHERE employee_id IS NOT NULL AND partner_type IN ('agency','partner') GROUP BY employee_id HAVING COUNT(*) > 1")).fetchall()
    if duplicates:
        raise RuntimeError("Existing duplicate external channel login bindings require explicit owner review before migration")
    op.create_index("uq_external_partner_employee", "sales_partners", ["employee_id"], unique=True,
                    sqlite_where=sa.text("employee_id IS NOT NULL AND partner_type IN ('agency','partner')"),
                    postgresql_where=sa.text("employee_id IS NOT NULL AND partner_type IN ('agency','partner')"))
    # Defaults deliberately describe the existing rule, never opt history into v2.
    op.add_column("commission_agreements", sa.Column("calculation_version", sa.String(32), nullable=False, server_default="legacy_v1"))
    op.add_column("commission_agreements", sa.Column("renewal_policy", sa.String(24), nullable=False, server_default="activity_decay"))
    op.add_column("customer_commission_attributions", sa.Column("commission_mode", sa.String(32), nullable=False, server_default="legacy"))
    op.add_column("customer_commission_attributions", sa.Column("commission_start_date", sa.Date(), nullable=True))
    op.add_column("customer_commission_attributions", sa.Column("first_service_start", sa.Date(), nullable=True))
    op.add_column("customer_commission_attributions", sa.Column("history_basis", sa.Text(), nullable=True))


def downgrade():
    # A downgrade would discard reviewed commission origins. Roll back code only
    # after a compatible release; do not erase these financial audit fields.
    raise RuntimeError("Commission rule audit columns must be retained; use a forward migration")
