"""Store the selected outcomes and quick-note snapshots on a single call."""
import sqlalchemy as sa
from alembic import op

revision = "p18f9a3c0453"
down_revision = "n18f9a3c0452"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sales_call_activities", sa.Column("communication_record", sa.JSON(none_as_null=True), nullable=True))


def downgrade():
    with op.batch_alter_table("sales_call_activities") as batch:
        batch.drop_column("communication_record")
