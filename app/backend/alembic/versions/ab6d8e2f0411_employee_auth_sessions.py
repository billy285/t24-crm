"""Add revocable employee sessions without changing employee or business data."""
from alembic import op
import sqlalchemy as sa

revision = "ab6d8e2f0411"
down_revision = "fa9b2c6d0410"
branch_labels = None
depends_on = None


def upgrade():
    if "employee_auth_sessions" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "employee_auth_sessions",
            sa.Column("id", sa.String(64), primary_key=True, nullable=False),
            sa.Column("employee_id", sa.Integer(), nullable=False),
            sa.Column("credential_fingerprint", sa.String(64), nullable=False),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("expires_at", sa.Integer(), nullable=False),
            sa.Column("revoked_at", sa.Integer(), nullable=True),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("employee_auth_sessions")}
    for column in ("employee_id", "expires_at"):
        name = f"ix_employee_auth_sessions_{column}"
        if name not in indexes:
            op.create_index(name, "employee_auth_sessions", [column])


def downgrade():
    raise RuntimeError("Employee session migration is intentionally irreversible; do not discard revocations or restore legacy stateless authentication during rollback")
