"""Add sales-only dossier collaboration, handoff and durable phone protection.

Revision ID: f7d1c5a9b027
Revises: e6c0b4f8a916

Additive only. No existing rows, customer grants, finance or private schemas change.
"""
from alembic import op
import sqlalchemy as sa

revision = "f7d1c5a9b027"
down_revision = "e6c0b4f8a916"
branch_labels = None
depends_on = None


def _id():
    return sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True)


def _time(name):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _indexes(table, *fields):
    for field in fields:
        op.create_index("ix_" + table + "_" + field, table, [field])


def upgrade():
    op.create_table("sales_dossier_summaries",
        sa.Column("lead_id", sa.Integer(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=False), sa.Column("updated_by_name", sa.String(255)),
        _time("updated_at"))
    op.create_table("sales_dossier_summary_audits", _id(),
        sa.Column("lead_id", sa.Integer(), nullable=False), sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False), sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False), sa.Column("actor_name", sa.String(255)),
        _time("created_at"), sa.UniqueConstraint("lead_id", "revision", name="uq_sales_dossier_summary_revision"))
    _indexes("sales_dossier_summary_audits", "lead_id")
    op.create_table("sales_dossier_grants", _id(),
        sa.Column("lead_id", sa.Integer(), nullable=False), sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("access", sa.String(16), nullable=False), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("invited_by_id", sa.Integer(), nullable=False),
        sa.Column("invited_by_name", sa.String(255)), _time("invited_at"),
        sa.Column("revoked_by_id", sa.Integer()), sa.Column("revoked_by_name", sa.String(255)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("lead_id", "employee_id", name="uq_sales_dossier_grant_employee"))
    _indexes("sales_dossier_grants", "lead_id", "employee_id")
    op.create_table("sales_dossier_grant_audits", _id(),
        sa.Column("lead_id", sa.Integer(), nullable=False), sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("action", sa.String(16), nullable=False),
        sa.Column("access", sa.String(16), nullable=False), sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("actor_name", sa.String(255)), _time("created_at"))
    _indexes("sales_dossier_grant_audits", "lead_id")
    op.create_table("sales_dossier_handoffs", _id(),
        sa.Column("lead_id", sa.Integer(), nullable=False), sa.Column("from_sales_id", sa.Integer()),
        sa.Column("from_sales_name", sa.String(255)), sa.Column("to_sales_id", sa.Integer(), nullable=False),
        sa.Column("to_sales_name", sa.String(255)), sa.Column("note", sa.Text(), nullable=False), sa.Column("reason", sa.Text()),
        sa.Column("summary", sa.JSON(), nullable=False), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False), sa.Column("created_by_name", sa.String(255)),
        _time("created_at"), sa.Column("acknowledged_by_id", sa.Integer()),
        sa.Column("acknowledged_by_name", sa.String(255)), sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("ack_note", sa.Text()))
    _indexes("sales_dossier_handoffs", "lead_id")
    op.create_table("sales_phone_suppressions",
        sa.Column("phone_key", sa.String(64), primary_key=True), sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False), sa.Column("source_lead_id", sa.Integer()),
        sa.Column("actor_id", sa.Integer()), sa.Column("actor_name", sa.String(255)), _time("updated_at"))
    op.create_table("sales_contact_protection_audits", _id(),
        sa.Column("phone_key", sa.String(64), nullable=False), sa.Column("lead_id", sa.Integer()),
        sa.Column("action", sa.String(32), nullable=False), sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Integer()), sa.Column("actor_name", sa.String(255)), _time("created_at"))
    _indexes("sales_contact_protection_audits", "phone_key", "lead_id")


def downgrade():
    raise RuntimeError("Preserve sales dossier, handoff and contact-protection audit; use a forward migration")
