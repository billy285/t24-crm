"""Add empty immutable image versions, task selections and delivery leases."""
from alembic import op
import sqlalchemy as sa

revision = "fbc6b8c9d025"
down_revision = "eaf5a7b8c914"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("media_publication_image_policies",
        sa.Column("owner_id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("media_publication_images",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("material_id", sa.Integer(), nullable=False),
        sa.Column("prepared_by_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_file_stat", sa.JSON(), nullable=False),
        sa.Column("image_sha256", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("rights_basis", sa.String(24), nullable=False),
        sa.Column("file_key", sa.String(32), nullable=False, unique=True),
        sa.Column("image_file_stat", sa.JSON(), nullable=False),
        sa.Column("delivery_token", sa.String(43), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("prepared_by_id", "request_id", name="uq_media_image_request"))
    op.create_index("ix_media_publication_images_customer_id", "media_publication_images", ["customer_id"])
    op.create_index("ix_media_publication_images_material_id", "media_publication_images", ["material_id"])
    op.create_table("media_publication_image_selections",
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("media_operation_tasks.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("image_id", sa.String(32), sa.ForeignKey("media_publication_images.id", ondelete="RESTRICT"), nullable=False))
    op.create_index("ix_media_publication_image_selections_image_id", "media_publication_image_selections", ["image_id"])
    op.create_table("media_publication_image_deliveries",
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("google_business_actions.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("image_id", sa.String(32), sa.ForeignKey("media_publication_images.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_media_publication_image_deliveries_image_id", "media_publication_image_deliveries", ["image_id"])


def downgrade():
    raise RuntimeError("Preserve approved images and delivery history; forward migration only")
