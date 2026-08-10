from core.database import Base
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)


BUSINESS_LINE_DEFINITIONS = (
    {"code": "managed_service", "name": "代运营", "is_recurring": True},
    {"code": "restaurant_os", "name": "餐饮 OS", "is_recurring": True},
    {"code": "beauty_os", "name": "美业 OS", "is_recurring": True},
    {"code": "one_time_project", "name": "一次性项目", "is_recurring": False},
)

ENGAGEMENT_STATUSES = (
    "pending_setup",
    "trial",
    "active_paid",
    "at_risk",
    "paused",
    "pending_stop",
    "stopped",
    "reactivated",
    "completed",
)

BILLING_CYCLES = ("monthly", "quarterly", "semi_annual", "annual", "one_time")
COLLECTION_METHODS = ("stripe_auto", "bank_transfer", "check", "zelle", "other")


class BusinessLine(Base):
    __tablename__ = "business_lines"
    __table_args__ = (UniqueConstraint("code", name="uq_business_lines_code"), {"extend_existing": True})

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    is_recurring = Column(Boolean, nullable=False, default=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ProductCatalog(Base):
    __tablename__ = "product_catalog"
    __table_args__ = (UniqueConstraint("code", name="uq_product_catalog_code"), {"extend_existing": True})

    id = Column(Integer, primary_key=True, autoincrement=True)
    business_line_id = Column(Integer, ForeignKey("business_lines.id", ondelete="RESTRICT"), nullable=False, index=True)
    code = Column(String(64), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    billing_kind = Column(String(24), nullable=False)
    default_currency = Column(String(3), nullable=False, default="USD")
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    effective_from = Column(Date, nullable=True)
    effective_to = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ProductPlan(Base):
    """Sellable plan/version underneath a business product.

    ProductCatalog identifies the product family (managed service, restaurant
    OS, beauty OS). ProductPlan captures the plan/version customers actually
    compare and buy. Prices may stay blank while a product is still being
    designed; subscriptions keep their own agreed price snapshot.
    """

    __tablename__ = "product_plans"
    __table_args__ = (UniqueConstraint("code", name="uq_product_plans_code"), {"extend_existing": True})

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("product_catalog.id", ondelete="RESTRICT"), nullable=False, index=True)
    code = Column(String(80), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    version_label = Column(String(80), nullable=True)
    pricing_status = Column(String(24), nullable=False, default="draft", index=True)
    standard_price = Column(Float, nullable=True)
    default_currency = Column(String(3), nullable=False, default="USD")
    default_billing_cycle = Column(String(24), nullable=True)
    platform_limit = Column(Integer, nullable=True)
    scope_type = Column(String(32), nullable=False, default="generic", index=True)
    entitlements_json = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    effective_from = Column(Date, nullable=True)
    effective_to = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CustomerEngagement(Base):
    __tablename__ = "customer_engagements"
    __table_args__ = (
        UniqueConstraint("engagement_code", name="uq_customer_engagements_code"),
        UniqueConstraint(
            "external_system",
            "external_store_id",
            "product_id",
            name="uq_customer_engagement_external_store_product",
        ),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    business_line_id = Column(Integer, ForeignKey("business_lines.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("product_catalog.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_plan_id = Column(Integer, ForeignKey("product_plans.id", ondelete="SET NULL"), nullable=True, index=True)
    engagement_code = Column(String(64), nullable=False, index=True)
    package_name = Column(String(160), nullable=True)
    status = Column(String(24), nullable=False, default="pending_setup", index=True)
    owner_employee_id = Column(Integer, nullable=True, index=True)
    sales_employee_id = Column(Integer, nullable=True, index=True)
    billing_cycle = Column(String(24), nullable=True, index=True)
    collection_method = Column(String(32), nullable=True, index=True)
    currency = Column(String(3), nullable=False, default="USD", index=True)
    selected_platforms = Column(Text, nullable=True)
    service_scope_json = Column(Text, nullable=True)
    trial_started_at = Column(DateTime(timezone=True), nullable=True)
    paid_started_at = Column(DateTime(timezone=True), nullable=True, index=True)
    paused_at = Column(DateTime(timezone=True), nullable=True)
    stopped_at = Column(DateTime(timezone=True), nullable=True, index=True)
    stop_reason_code = Column(String(48), nullable=True, index=True)
    stop_note = Column(Text, nullable=True)
    external_system = Column(String(32), nullable=True, index=True)
    external_merchant_id = Column(String(128), nullable=True, index=True)
    external_store_id = Column(String(128), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class EngagementSourceLink(Base):
    __tablename__ = "engagement_source_links"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "link_role", name="uq_engagement_source_link_role"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(Integer, ForeignKey("customer_engagements.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = Column(String(32), nullable=False, index=True)
    source_id = Column(Integer, nullable=False, index=True)
    link_role = Column(String(32), nullable=False, index=True)
    confidence = Column(String(16), nullable=False, default="suggested", index=True)
    linked_by_id = Column(String(64), nullable=True)
    linked_by_name = Column(String(160), nullable=True)
    linked_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    note = Column(Text, nullable=True)


class EngagementLifecycleEvent(Base):
    __tablename__ = "engagement_lifecycle_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_engagement_lifecycle_event_idempotency"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(Integer, ForeignKey("customer_engagements.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(32), nullable=False, index=True)
    effective_at = Column(DateTime(timezone=True), nullable=False, index=True)
    reason_code = Column(String(48), nullable=True, index=True)
    source_type = Column(String(32), nullable=True)
    source_id = Column(Integer, nullable=True)
    idempotency_key = Column(String(160), nullable=True, index=True)
    actor_id = Column(String(64), nullable=True)
    actor_name = Column(String(160), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ClassificationReviewDecision(Base):
    __tablename__ = "classification_review_decisions"
    __table_args__ = (
        UniqueConstraint("review_key", name="uq_classification_review_decisions_key"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    review_key = Column(String(160), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    decision = Column(String(24), nullable=False, default="pending", index=True)
    note = Column(Text, nullable=True)
    reviewed_by_id = Column(String(64), nullable=True)
    reviewed_by_name = Column(String(160), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
