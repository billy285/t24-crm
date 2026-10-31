"""Add opt-in publication specs without rewriting any task or audit row."""
from alembic import op
import sqlalchemy as sa

revision = "eaf5a7b8c914"
down_revision = "d9e4f6a7b803"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("media_operation_publication_specs",
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("media_operation_tasks.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("spec", sa.JSON(), nullable=False))


def downgrade():
    raise RuntimeError("Preserve reviewed publication and delivery history; forward migration only")
