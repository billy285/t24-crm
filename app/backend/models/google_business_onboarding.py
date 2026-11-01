"""Owner-only discovery, frozen binding plans and durable local receipts."""
from core.database import Base
from sqlalchemy import Column, Integer, String, DateTime, JSON, Boolean, UniqueConstraint


class GoogleOnboardingCatalog(Base):
    __tablename__ = "google_business_onboarding_catalogs"
    id = Column(String(32), primary_key=True)
    owner_id = Column(Integer, nullable=False)
    connection_id = Column(Integer, nullable=False)
    customer_id = Column(Integer)
    revision = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False)
    connection_marker = Column(JSON, nullable=False)
    locations = Column(JSON, nullable=False)
    truncated = Column(Boolean, nullable=False)
    lease_token = Column(String(32))
    lease_at = Column(DateTime(timezone=True))
    observed_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))
    error_code = Column(String(40))
    message = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class GoogleOnboardingBatch(Base):
    __tablename__ = "google_business_onboarding_batches"
    id = Column(String(32), primary_key=True)
    owner_id = Column(Integer, nullable=False)
    catalog_id = Column(String(32))
    customer_id = Column(Integer)
    kind = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False)
    revision = Column(Integer, nullable=False)
    preview_hash = Column(String(64), nullable=False)
    snapshot = Column(JSON, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    message = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class GoogleOnboardingItem(Base):
    __tablename__ = "google_business_onboarding_items"
    __table_args__ = (UniqueConstraint("batch_id", "position", name="uq_google_onboarding_position"),
                     UniqueConstraint("owner_id", "request_id", name="uq_google_onboarding_item_request"))
    id = Column(String(32), primary_key=True)
    batch_id = Column(String(32), nullable=False, index=True)
    owner_id = Column(Integer, nullable=False)
    position = Column(Integer, nullable=False)
    customer_id = Column(Integer, nullable=False)
    location_name = Column(String(200), nullable=False)
    request_id = Column(String(36), nullable=False)
    status = Column(String(16), nullable=False)
    snapshot = Column(JSON, nullable=False)
    warnings = Column(JSON, nullable=False)
    binding_id = Column(Integer)
    lease_token = Column(String(32))
    lease_at = Column(DateTime(timezone=True))
    error_code = Column(String(40))
    message = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class GoogleOnboardingRequest(Base):
    __tablename__ = "google_business_onboarding_requests"
    __table_args__ = (UniqueConstraint("owner_id", "request_id", name="uq_google_onboarding_request"),)
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, nullable=False)
    request_id = Column(String(36), nullable=False)
    kind = Column(String(16), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    resource_id = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
