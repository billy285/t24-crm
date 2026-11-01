"""Add isolated, initially empty Meta owner pilot workflow records."""
from alembic import op
import sqlalchemy as sa

revision = "cefa9b12a358"
down_revision = "bde8da01f247"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('meta_operations_credentials',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('connection_id', sa.Integer(), sa.ForeignKey('meta_business_connections.id', ondelete="RESTRICT"), nullable=False),
        sa.Column('token_encrypted', sa.Text(), nullable=True),
        sa.Column('granted_scopes', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('needs_reconnect', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('last_error', sa.String(40), nullable=True),
        sa.Column('connected_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'connection_id', name='uq_meta_ops_credential_owner_connection'))
    op.create_index('ix_meta_operations_credentials_owner_id', 'meta_operations_credentials', ['owner_id'])
    op.create_table('meta_operations_oauth_states',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.String(36), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('state_hash', sa.String(64), nullable=False),
        sa.Column('cookie_hash', sa.String(64), nullable=False),
        sa.Column('flow_encrypted', sa.Text(), nullable=False),
        sa.Column('connection_id', sa.Integer(), nullable=False),
        sa.Column('connection_revision', sa.Integer(), nullable=False),
        sa.Column('expected_credential_revision', sa.Integer(), nullable=True),
        sa.Column('targets_snapshot', sa.JSON(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('state_hash'),
        sa.UniqueConstraint('owner_id', 'request_id', name='uq_meta_ops_oauth_request'))
    op.create_index('ix_meta_operations_oauth_states_expires_at', 'meta_operations_oauth_states', ['expires_at'])
    op.create_table('meta_operations_bindings',
        sa.Column('id', sa.Integer(), sa.ForeignKey('meta_business_bindings.id', ondelete="RESTRICT"), primary_key=True, autoincrement=False, nullable=False),
        sa.Column('source_binding_id', sa.Integer(), sa.ForeignKey('meta_business_bindings.id', ondelete="RESTRICT"), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('customer_name', sa.String(255), nullable=False),
        sa.Column('platform', sa.String(16), nullable=False),
        sa.Column('external_id', sa.String(80), nullable=False),
        sa.Column('page_id', sa.String(80), nullable=False),
        sa.Column('asset_name', sa.String(255), nullable=False),
        sa.Column('asset_username', sa.String(255), nullable=True),
        sa.Column('connection_id', sa.Integer(), sa.ForeignKey('meta_business_connections.id', ondelete="RESTRICT"), nullable=False),
        sa.Column('credential_id', sa.Integer(), sa.ForeignKey('meta_operations_credentials.id', ondelete="RESTRICT"), nullable=False),
        sa.Column('connection_revision', sa.Integer(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("platform IN ('facebook','instagram')", name='ck_meta_ops_binding_platform'),
        sa.CheckConstraint('id = source_binding_id', name='ck_meta_ops_binding_source_identity'))
    op.create_index('ix_meta_operations_bindings_customer_id', 'meta_operations_bindings', ['customer_id'])
    op.create_index('ix_meta_operations_bindings_owner_id', 'meta_operations_bindings', ['owner_id'])
    op.create_index('uq_meta_ops_active_customer_platform', 'meta_operations_bindings', ['customer_id', 'platform'], unique=True, sqlite_where=sa.text('active = 1'), postgresql_where=sa.text('active'))
    op.create_index('uq_meta_ops_active_global_asset', 'meta_operations_bindings', ['platform', 'external_id'], unique=True, sqlite_where=sa.text('active = 1'), postgresql_where=sa.text('active'))
    op.create_table('meta_operations_media',
        sa.Column('id', sa.String(32), primary_key=True, nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('source_sha256', sa.String(64), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('byte_size', sa.Integer(), nullable=False),
        sa.Column('file_stat', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_meta_operations_media_customer_id', 'meta_operations_media', ['customer_id'])
    op.create_index('ix_meta_operations_media_owner_id', 'meta_operations_media', ['owner_id'])
    op.create_table('meta_operations_targets',
        sa.Column('id', sa.String(32), primary_key=True, nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('binding_id', sa.Integer(), sa.ForeignKey('meta_business_bindings.id', ondelete="RESTRICT"), nullable=False),
        sa.Column('binding_revision', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('external_id', sa.String(200), nullable=False),
        sa.Column('parent_external_id', sa.String(200), nullable=True),
        sa.Column('parent_ref', sa.String(32), nullable=True),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('version', sa.String(64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('post','comment')", name='ck_meta_ops_target_kind'))
    op.create_index('ix_meta_operations_targets_binding_id', 'meta_operations_targets', ['binding_id'])
    op.create_index('ix_meta_operations_targets_owner_id', 'meta_operations_targets', ['owner_id'])
    op.create_table('meta_operations_drafts',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('binding_id', sa.Integer(), sa.ForeignKey('meta_business_bindings.id', ondelete="RESTRICT"), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('media_id', sa.String(32), sa.ForeignKey('meta_operations_media.id', ondelete="RESTRICT"), nullable=True),
        sa.Column('target_ref', sa.String(32), sa.ForeignKey('meta_operations_targets.id', ondelete="RESTRICT"), nullable=True),
        sa.Column('expected_target_version', sa.String(64), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='draft'),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('preview_hash', sa.String(64), nullable=True),
        sa.Column('approved_snapshot', sa.JSON(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('post','reply')", name='ck_meta_ops_draft_kind'),
        sa.CheckConstraint("status IN ('draft','approved')", name='ck_meta_ops_draft_status'))
    op.create_index('ix_meta_operations_drafts_binding_id', 'meta_operations_drafts', ['binding_id'])
    op.create_index('ix_meta_operations_drafts_owner_id', 'meta_operations_drafts', ['owner_id'])
    op.create_table('meta_operations_actions',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('binding_id', sa.Integer(), sa.ForeignKey('meta_business_bindings.id', ondelete="RESTRICT"), nullable=False),
        sa.Column('binding_revision', sa.Integer(), nullable=False),
        sa.Column('connection_revision', sa.Integer(), nullable=False),
        sa.Column('draft_id', sa.Integer(), sa.ForeignKey('meta_operations_drafts.id', ondelete="RESTRICT"), nullable=False),
        sa.Column('draft_revision', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('request_id', sa.String(36), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('preview_hash', sa.String(64), nullable=False),
        sa.Column('submitted_snapshot', sa.JSON(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('dispatch_stage', sa.String(32), nullable=False, server_default='reserved'),
        sa.Column('dispatch_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('progress', sa.JSON(), nullable=True),
        sa.Column('provider_id', sa.String(200), nullable=True),
        sa.Column('provider_url', sa.Text(), nullable=True),
        sa.Column('delivery_token', sa.String(43), nullable=True),
        sa.Column('delivery_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('message', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('delivery_token'),
        sa.UniqueConstraint('owner_id', 'request_id', name='uq_meta_ops_action_request'),
        sa.UniqueConstraint('draft_id', 'draft_revision', name='uq_meta_ops_draft_dispatch'))
    op.create_index('ix_meta_operations_actions_binding_id', 'meta_operations_actions', ['binding_id'])
    op.create_index('ix_meta_operations_actions_owner_id', 'meta_operations_actions', ['owner_id'])
    op.create_table('meta_operations_schedules',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('binding_id', sa.Integer(), sa.ForeignKey('meta_business_bindings.id', ondelete="RESTRICT"), nullable=False),
        sa.Column('draft_id', sa.Integer(), sa.ForeignKey('meta_operations_drafts.id', ondelete="RESTRICT"), nullable=False),
        sa.Column('draft_revision', sa.Integer(), nullable=False),
        sa.Column('preview_hash', sa.String(64), nullable=False),
        sa.Column('submitted_snapshot', sa.JSON(), nullable=False),
        sa.Column('planned_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('timezone', sa.String(80), nullable=False),
        sa.Column('request_id', sa.String(36), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='prepared'),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('action_id', sa.Integer(), sa.ForeignKey('meta_operations_actions.id', ondelete="RESTRICT"), nullable=True),
        sa.Column('message', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('request_id'))
    op.create_index('ix_meta_operations_schedules_binding_id', 'meta_operations_schedules', ['binding_id'])
    op.create_index('ix_meta_operations_schedules_owner_id', 'meta_operations_schedules', ['owner_id'])
    op.create_index('ix_meta_operations_schedules_planned_at', 'meta_operations_schedules', ['planned_at'])
    op.create_index('ix_meta_operations_schedules_status', 'meta_operations_schedules', ['status'])
    op.create_table('meta_operations_requests',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.String(36), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('result_id', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'request_id', name='uq_meta_ops_request'))


def downgrade():
    raise RuntimeError("Preserve Meta publication and approval history; use a reviewed forward migration")
