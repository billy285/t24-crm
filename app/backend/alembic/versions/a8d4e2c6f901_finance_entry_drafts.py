"""Add empty finance registration drafts and their audit trail only."""
from alembic import op
import sqlalchemy as sa

revision = "a8d4e2c6f901"
down_revision = "f3c7d1a9b456"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("finance_entry_drafts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("customer_name", sa.String(255), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("created_by_name", sa.String(255), nullable=False),
        sa.Column("client_request_id", sa.String(64), nullable=False),
        sa.Column("creation_fingerprint", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("return_reason", sa.Text()),
        sa.Column("posted_entity", sa.String(32)),
        sa.Column("posted_id", sa.Integer()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("voided_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("created_by_id", "client_request_id", name="uq_finance_entry_draft_create_request"),
        sa.UniqueConstraint("posted_entity", "posted_id", name="uq_finance_entry_draft_ledger"),
        sa.CheckConstraint("revision >= 1", name="ck_finance_entry_draft_revision"),
        sa.CheckConstraint("status IN ('draft','submitted','returned','posted','voided')", name="ck_finance_entry_draft_status"),
        sa.CheckConstraint("kind IN ('manual_receipt','customer_expense','company_expense')", name="ck_finance_entry_draft_kind"))
    for field in ("customer_id", "created_by_id", "status"):
        op.create_index("ix_finance_entry_drafts_" + field, "finance_entry_drafts", [field])
    op.create_table("finance_entry_draft_audits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("draft_id", sa.Integer(), sa.ForeignKey("finance_entry_drafts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("actor_name", sa.String(255), nullable=False),
        sa.Column("before_status", sa.String(16)),
        sa.Column("after_status", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(64)),
        sa.Column("request_fingerprint", sa.String(64)),
        sa.Column("reason", sa.Text()),
        sa.Column("payload_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("draft_id", "revision", name="uq_finance_entry_draft_audit_revision"),
        sa.UniqueConstraint("draft_id", "request_id", name="uq_finance_entry_draft_audit_request"))
    op.create_index("ix_finance_entry_draft_audits_draft_id", "finance_entry_draft_audits", ["draft_id"])

    op.create_table("finance_entry_attachments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("draft_id", sa.Integer(), sa.ForeignKey("finance_entry_drafts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("uploaded_by_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(180), nullable=False),
        sa.Column("media_type", sa.String(80), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.Column("removed_by_id", sa.Integer()))
    op.create_index("ix_finance_entry_attachments_draft_id", "finance_entry_attachments", ["draft_id"])


def downgrade():
    raise RuntimeError("Preserve finance registration evidence and audit; use a forward migration")
