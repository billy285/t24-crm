"""Add owner-approved historical Stripe evidence; no old rows, schema or seeds."""
from alembic import op
import sqlalchemy as sa

revision = "d1a5b9e7f234"
down_revision = "c0f4a8d6e123"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('stripe_history_previews',
        sa.Column('token', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('binding_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table('stripe_history_bindings',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('account_id', sa.String(length=255), nullable=False),
        sa.Column('livemode', sa.Boolean(), nullable=False),
        sa.Column('stripe_subscription_id', sa.String(length=255), nullable=False),
        sa.Column('stripe_customer_id', sa.String(length=255), nullable=False),
        sa.Column('crm_subscription_id', sa.Integer(), sa.ForeignKey('subscriptions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('crm_snapshot', sa.JSON(), nullable=False),
        sa.Column('price_snapshot', sa.JSON(), nullable=False),
        sa.Column('income_type', sa.String(length=32), nullable=False),
        sa.Column('sync_from', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('needs_refresh', sa.Boolean(), nullable=False),
        sa.Column('pilot_evidence', sa.JSON(), nullable=False),
        sa.Column('pilot_validated', sa.Boolean(), nullable=False),
        sa.Column('verified_by_id', sa.Integer(), nullable=False),
        sa.Column('verified_by_name', sa.String(length=255), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('crm_subscription_id', name='uq_history_crm_service'),
        sa.UniqueConstraint('account_id', 'livemode', 'stripe_subscription_id', name='uq_history_provider_subscription'))
    op.create_index('ix_stripe_history_bindings_customer_id', 'stripe_history_bindings', ['customer_id'], unique=False)
    op.create_table('stripe_history_invoice_reviews',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('account_id', sa.String(length=255), nullable=False),
        sa.Column('livemode', sa.Boolean(), nullable=False),
        sa.Column('stripe_invoice_id', sa.String(length=255), nullable=False),
        sa.Column('binding_id', sa.Integer(), sa.ForeignKey('stripe_history_bindings.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('needs_refresh', sa.Boolean(), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('account_id', 'livemode', 'stripe_invoice_id', name='uq_history_provider_invoice'))
    op.create_index('ix_stripe_history_invoice_reviews_binding_id', 'stripe_history_invoice_reviews', ['binding_id'], unique=False)
    op.create_table('stripe_history_postings',
        sa.Column('review_id', sa.Integer(), sa.ForeignKey('stripe_history_invoice_reviews.id', ondelete='RESTRICT'), primary_key=True, nullable=False),
        sa.Column('account_id', sa.String(length=255), nullable=False),
        sa.Column('livemode', sa.Boolean(), nullable=False),
        sa.Column('stripe_charge_id', sa.String(length=255), nullable=False),
        sa.Column('payment_id', sa.Integer(), sa.ForeignKey('payments.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('action', sa.String(length=24), nullable=False),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.Column('verified_by_id', sa.Integer(), nullable=False),
        sa.Column('verified_by_name', sa.String(length=255), nullable=True),
        sa.Column('verification_note', sa.String(length=2000), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('account_id', 'livemode', 'stripe_charge_id', name='uq_history_cash_charge'),
        sa.UniqueConstraint('payment_id', name='uq_history_posted_payment'))
    op.create_table('stripe_history_events',
        sa.Column('event_id', sa.String(length=255), primary_key=True, nullable=False),
        sa.Column('binding_id', sa.Integer(), sa.ForeignKey('stripe_history_bindings.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('event_type', sa.String(length=80), nullable=False),
        sa.Column('resource_key', sa.String(length=255), nullable=False),
        sa.Column('signal_status', sa.String(length=32), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('payload_digest', sa.String(length=64), nullable=False),
        sa.Column('stripe_created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table('stripe_history_audits',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('binding_id', sa.Integer(), sa.ForeignKey('stripe_history_bindings.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('review_id', sa.Integer(), sa.ForeignKey('stripe_history_invoice_reviews.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('actor_id', sa.Integer(), nullable=False),
        sa.Column('actor_name', sa.String(length=255), nullable=True),
        sa.Column('action', sa.String(length=32), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table('stripe_history_policy',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('bulk_enabled', sa.Boolean(), nullable=False),
        sa.Column('validated_binding_ids', sa.JSON(), nullable=False),
        sa.Column('verified_by_id', sa.Integer(), nullable=False),
        sa.Column('verification_note', sa.String(length=2000), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))


def downgrade():
    raise RuntimeError("Preserve historical mapping and owner receipt evidence; use a forward migration")
