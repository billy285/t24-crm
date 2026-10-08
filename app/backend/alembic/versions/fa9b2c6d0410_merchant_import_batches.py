"""Add import receipts only; no historical merchant, customer or finance rewrite."""
from alembic import op
import sqlalchemy as sa
revision = "fa9b2c6d0410"
down_revision = "e9c7a3f2b106"
branch_labels = None
depends_on = None

def upgrade():
    if "merchant_import_batches" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table("merchant_import_batches",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("filename", sa.String(255), nullable=False),
            sa.Column("file_sha256", sa.String(64), nullable=False),
            sa.Column("active_file_key", sa.String(96), nullable=True, unique=True),
            sa.Column("template_version", sa.String(40), nullable=False),
            sa.Column("created_by_id", sa.Integer(), nullable=False),
            sa.Column("created_by_name", sa.String(200)),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False),
            sa.Column("rows_json", sa.Text(), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("committed_at", sa.DateTime(timezone=True)),
            sa.Column("reverted_at", sa.DateTime(timezone=True)),
        )
    indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("merchant_import_batches")}
    for column in ("file_sha256", "created_by_id", "status"):
        name = f"ix_merchant_import_batches_{column}"
        if name not in indexes:
            op.create_index(name, "merchant_import_batches", [column])

def downgrade():
    raise RuntimeError("Import receipts are intentionally irreversible; use batch undo for eligible business records, preserve the audit receipts.")
