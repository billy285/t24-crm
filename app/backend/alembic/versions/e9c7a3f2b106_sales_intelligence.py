"""Add isolated sales operating tables; never alter finance or legacy call evidence."""

from alembic import op
import sqlalchemy as sa

revision = "e9c7a3f2b106"
down_revision = "d8a4f2c6b901"
branch_labels = None
depends_on = None


def upgrade():
    tables = {
        "sales_operating_settings": [
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("effective_month", sa.String(7), nullable=False, unique=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_by_id", sa.Integer(), nullable=False),
            sa.Column("created_by_name", sa.String()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        ],
        "sales_lead_profiles": [
            sa.Column("lead_id", sa.Integer(), primary_key=True),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        ],
        "sales_contact_details": [
            sa.Column("activity_id", sa.Integer(), primary_key=True),
            sa.Column("lead_id", sa.Integer(), nullable=False),
            sa.Column("reached_person", sa.String(24), nullable=False),
            sa.Column("rejection_reason", sa.String(200)),
            sa.Column("need_summary", sa.Text()),
            sa.Column("next_step", sa.Text()),
            sa.Column("recorded_by_id", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        ],
        "sales_insight_events": [
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("lead_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("actor_id", sa.Integer(), nullable=False),
            sa.Column("actor_name", sa.String()),
            sa.Column("owner_id", sa.Integer()),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        ],
        "sales_monthly_targets": [
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_id", sa.Integer(), nullable=False),
            sa.Column("month", sa.String(7), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("manager_id", sa.Integer()),
            sa.Column("employee_name", sa.String()),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_by_id", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "employee_id", "month", "revision", name="uq_sales_target_revision"
            ),
        ],
        "sales_coaching_tasks": [
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_id", sa.Integer(), nullable=False),
            sa.Column("manager_id", sa.Integer(), nullable=False),
            sa.Column("lead_id", sa.Integer()),
            sa.Column("action", sa.Text(), nullable=False),
            sa.Column("due_date", sa.Date(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("completion_note", sa.Text()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
        ],
        "sales_saved_views": [
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(60), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("employee_id", "name", name="uq_sales_saved_view"),
        ],
    }
    indexes = {
        "sales_operating_settings": ["effective_month"],
        "sales_contact_details": ["lead_id"],
        "sales_insight_events": ["lead_id", "kind", "owner_id", "created_at"],
        "sales_monthly_targets": ["employee_id", "month", "manager_id"],
        "sales_coaching_tasks": ["employee_id", "manager_id", "lead_id"],
        "sales_saved_views": ["employee_id"],
    }
    for name, columns in tables.items():
        op.create_table(name, *columns)
        for col in indexes.get(name, []):
            op.create_index(
                f"ix_{name}_{col}",
                name,
                [col],
                unique=name == "sales_operating_settings",
            )


def downgrade():
    raise RuntimeError(
        "This additive revision is intentionally irreversible. Preserve sales evidence. Roll back the application image without dropping these additive tables."
    )
