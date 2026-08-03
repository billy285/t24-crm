"""add management decision foundation tables

Revision ID: f1a4c7d2e903
Revises: e8b1c7d4f902
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a4c7d2e903"
down_revision: Union[str, Sequence[str], None] = "e8b1c7d4f902"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_indexes(table_name: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table_name}_{column}", table_name, [column])


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("business_lines"):
        op.create_table(
            "business_lines",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code", sa.String(length=32), nullable=False),
            sa.Column("name", sa.String(length=80), nullable=False),
            sa.Column("is_recurring", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("code", name="uq_business_lines_code"),
        )
        _create_indexes("business_lines", ("code", "is_active"))
        business_lines = sa.table(
            "business_lines",
            sa.column("code", sa.String()),
            sa.column("name", sa.String()),
            sa.column("is_recurring", sa.Boolean()),
            sa.column("is_active", sa.Boolean()),
        )
        op.bulk_insert(
            business_lines,
            [
                {"code": "managed_service", "name": "代运营", "is_recurring": True, "is_active": True},
                {"code": "restaurant_os", "name": "餐饮 OS", "is_recurring": True, "is_active": True},
                {"code": "beauty_os", "name": "美业 OS", "is_recurring": True, "is_active": True},
                {"code": "one_time_project", "name": "一次性项目", "is_recurring": False, "is_active": True},
            ],
        )

    inspector = sa.inspect(bind)
    if not inspector.has_table("product_catalog"):
        op.create_table(
            "product_catalog",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("business_line_id", sa.Integer(), sa.ForeignKey("business_lines.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("billing_kind", sa.String(length=24), nullable=False),
            sa.Column("default_currency", sa.String(length=3), nullable=False, server_default="USD"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("effective_from", sa.Date()),
            sa.Column("effective_to", sa.Date()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("code", name="uq_product_catalog_code"),
        )
        _create_indexes("product_catalog", ("business_line_id", "code", "is_active"))

    inspector = sa.inspect(bind)
    if not inspector.has_table("customer_engagements"):
        op.create_table(
            "customer_engagements",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("business_line_id", sa.Integer(), sa.ForeignKey("business_lines.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("product_catalog.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("engagement_code", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="pending_setup"),
            sa.Column("owner_employee_id", sa.Integer()),
            sa.Column("sales_employee_id", sa.Integer()),
            sa.Column("billing_cycle", sa.String(length=24)),
            sa.Column("collection_method", sa.String(length=32)),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
            sa.Column("trial_started_at", sa.DateTime(timezone=True)),
            sa.Column("paid_started_at", sa.DateTime(timezone=True)),
            sa.Column("paused_at", sa.DateTime(timezone=True)),
            sa.Column("stopped_at", sa.DateTime(timezone=True)),
            sa.Column("stop_reason_code", sa.String(length=48)),
            sa.Column("stop_note", sa.Text()),
            sa.Column("external_system", sa.String(length=32)),
            sa.Column("external_merchant_id", sa.String(length=128)),
            sa.Column("external_store_id", sa.String(length=128)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("engagement_code", name="uq_customer_engagements_code"),
            sa.UniqueConstraint(
                "external_system",
                "external_store_id",
                "product_id",
                name="uq_customer_engagement_external_store_product",
            ),
        )
        _create_indexes(
            "customer_engagements",
            (
                "customer_id",
                "business_line_id",
                "product_id",
                "engagement_code",
                "status",
                "owner_employee_id",
                "sales_employee_id",
                "billing_cycle",
                "collection_method",
                "currency",
                "paid_started_at",
                "stopped_at",
                "stop_reason_code",
                "external_system",
                "external_merchant_id",
                "external_store_id",
            ),
        )

    inspector = sa.inspect(bind)
    if not inspector.has_table("engagement_source_links"):
        op.create_table(
            "engagement_source_links",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("engagement_id", sa.Integer(), sa.ForeignKey("customer_engagements.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_type", sa.String(length=32), nullable=False),
            sa.Column("source_id", sa.Integer(), nullable=False),
            sa.Column("link_role", sa.String(length=32), nullable=False),
            sa.Column("confidence", sa.String(length=16), nullable=False, server_default="suggested"),
            sa.Column("linked_by_id", sa.String(length=64)),
            sa.Column("linked_by_name", sa.String(length=160)),
            sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("note", sa.Text()),
            sa.UniqueConstraint("source_type", "source_id", "link_role", name="uq_engagement_source_link_role"),
        )
        _create_indexes("engagement_source_links", ("engagement_id", "source_type", "source_id", "link_role", "confidence"))

    inspector = sa.inspect(bind)
    if not inspector.has_table("engagement_lifecycle_events"):
        op.create_table(
            "engagement_lifecycle_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("engagement_id", sa.Integer(), sa.ForeignKey("customer_engagements.id", ondelete="CASCADE"), nullable=False),
            sa.Column("event_type", sa.String(length=32), nullable=False),
            sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reason_code", sa.String(length=48)),
            sa.Column("source_type", sa.String(length=32)),
            sa.Column("source_id", sa.Integer()),
            sa.Column("idempotency_key", sa.String(length=160)),
            sa.Column("actor_id", sa.String(length=64)),
            sa.Column("actor_name", sa.String(length=160)),
            sa.Column("note", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("idempotency_key", name="uq_engagement_lifecycle_event_idempotency"),
        )
        _create_indexes(
            "engagement_lifecycle_events",
            ("engagement_id", "event_type", "effective_at", "reason_code", "idempotency_key"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table_name in (
        "engagement_lifecycle_events",
        "engagement_source_links",
        "customer_engagements",
        "product_catalog",
        "business_lines",
    ):
        if inspector.has_table(table_name):
            op.drop_table(table_name)
            inspector = sa.inspect(bind)
