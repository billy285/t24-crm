"""Four empty, owner-private version/preview/receipt tables. No business seeds."""
from alembic import op
import sqlalchemy as sa
revision="i54af678a914"
down_revision="h43fe567f803"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("media_automation_setting_versions",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("owner_id",sa.Integer(),nullable=False),sa.Column("customer_id",sa.Integer(),nullable=False),sa.Column("revision",sa.Integer(),nullable=False),sa.Column("effective_from_month",sa.String(7),nullable=False),sa.Column("document",sa.JSON(),nullable=False),sa.Column("preview_id",sa.String(36),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint("owner_id","customer_id","revision",name="uq_media_setting_version"))
    op.create_index("ix_media_automation_setting_versions_owner_id","media_automation_setting_versions",["owner_id"])
    op.create_index("ix_media_automation_setting_versions_customer_id","media_automation_setting_versions",["customer_id"])
    op.create_table("media_automation_template_versions",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("owner_id",sa.Integer(),nullable=False),sa.Column("template_id",sa.String(36),nullable=False),sa.Column("revision",sa.Integer(),nullable=False),sa.Column("name",sa.String(80),nullable=False),sa.Column("document",sa.JSON(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint("owner_id","template_id","revision",name="uq_media_template_version"))
    op.create_index("ix_media_automation_template_versions_owner_id","media_automation_template_versions",["owner_id"])
    op.create_table("media_automation_settings_previews",sa.Column("id",sa.String(36),primary_key=True),sa.Column("owner_id",sa.Integer(),nullable=False),sa.Column("request_id",sa.String(36),nullable=False),sa.Column("fingerprint",sa.String(64),nullable=False),sa.Column("body",sa.JSON(),nullable=False),sa.Column("state_hash",sa.String(64),nullable=False),sa.Column("result",sa.JSON(),nullable=False),sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint("owner_id","request_id",name="uq_media_setting_preview_request"))
    op.create_index("ix_media_automation_settings_previews_owner_id","media_automation_settings_previews",["owner_id"])
    op.create_table("media_automation_settings_receipts",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("owner_id",sa.Integer(),nullable=False),sa.Column("request_id",sa.String(36),nullable=False),sa.Column("fingerprint",sa.String(64),nullable=False),sa.Column("result",sa.JSON(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint("owner_id","request_id",name="uq_media_setting_apply_request"))
    op.create_index("ix_media_automation_settings_receipts_owner_id","media_automation_settings_receipts",["owner_id"])

def downgrade():
    for name in ("media_automation_settings_receipts","media_automation_settings_previews","media_automation_template_versions","media_automation_setting_versions"):
        op.drop_index("ix_"+name+"_owner_id",table_name=name)
        if name=="media_automation_setting_versions":op.drop_index("ix_"+name+"_customer_id",table_name=name)
        op.drop_table(name)
