"""add management classification review workflow

Revision ID: a6d2f9c4e701
Revises: f1a4c7d2e903
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a6d2f9c4e701"
down_revision: Union[str, Sequence[str], None] = "f1a4c7d2e903"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_PRODUCTS = (
    ("managed_service", "managed_service_legacy", "代运营历史套餐", "recurring"),
    ("restaurant_os", "restaurant_os_legacy", "餐饮 OS", "recurring"),
    ("beauty_os", "beauty_os_legacy", "美业 OS", "recurring"),
    ("one_time_project", "one_time_legacy", "一次性项目", "one_time"),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("classification_review_decisions"):
        op.create_table(
            "classification_review_decisions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("review_key", sa.String(length=160), nullable=False),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("decision", sa.String(length=24), nullable=False, server_default="pending"),
            sa.Column("note", sa.Text()),
            sa.Column("reviewed_by_id", sa.String(length=64)),
            sa.Column("reviewed_by_name", sa.String(length=160)),
            sa.Column("reviewed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("review_key", name="uq_classification_review_decisions_key"),
        )
        op.create_index("ix_classification_review_decisions_review_key", "classification_review_decisions", ["review_key"])
        op.create_index("ix_classification_review_decisions_customer_id", "classification_review_decisions", ["customer_id"])
        op.create_index("ix_classification_review_decisions_decision", "classification_review_decisions", ["decision"])
        op.create_index("ix_classification_review_decisions_reviewed_at", "classification_review_decisions", ["reviewed_at"])

    business_lines = sa.table(
        "business_lines",
        sa.column("id", sa.Integer()),
        sa.column("code", sa.String()),
    )
    products = sa.table(
        "product_catalog",
        sa.column("business_line_id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("billing_kind", sa.String()),
        sa.column("default_currency", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    existing_codes = set(bind.execute(sa.select(products.c.code)).scalars())
    line_ids = dict(bind.execute(sa.select(business_lines.c.code, business_lines.c.id)).all())
    for line_code, product_code, product_name, billing_kind in DEFAULT_PRODUCTS:
        if product_code in existing_codes or line_code not in line_ids:
            continue
        bind.execute(products.insert().values(
            business_line_id=line_ids[line_code],
            code=product_code,
            name=product_name,
            billing_kind=billing_kind,
            default_currency="USD",
            is_active=True,
        ))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("classification_review_decisions"):
        op.drop_table("classification_review_decisions")
