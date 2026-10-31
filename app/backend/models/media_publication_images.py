"""Immutable private image versions and explicitly dispatched delivery leases."""
from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
# Resolve additive foreign-key targets for isolated metadata-based test/startup
# discovery as well as the production module loader.
from models.media_operations import MediaOperationTask  # noqa: F401
from models.google_business import GoogleBusinessAction  # noqa: F401


class MediaPublicationImagePolicy(Base):
    __tablename__ = "media_publication_image_policies"
    owner_id = Column(Integer, primary_key=True)
    enabled = Column(Boolean, nullable=False)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MediaPublicationImage(Base):
    __tablename__ = "media_publication_images"
    __table_args__ = (UniqueConstraint("prepared_by_id", "request_id", name="uq_media_image_request"),)
    id = Column(String(32), primary_key=True)
    customer_id = Column(Integer, nullable=False, index=True)
    material_id = Column(Integer, nullable=False, index=True)
    prepared_by_id = Column(Integer, nullable=False)
    request_id = Column(String(36), nullable=False)
    request_fingerprint = Column(String(64), nullable=False)
    source_sha256 = Column(String(64), nullable=False)
    source_fingerprint = Column(String(64), nullable=False)
    source_file_stat = Column(JSON, nullable=False)
    image_sha256 = Column(String(64), nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    byte_size = Column(Integer, nullable=False)
    rights_basis = Column(String(24), nullable=False)
    file_key = Column(String(32), nullable=False, unique=True)
    image_file_stat = Column(JSON, nullable=False)
    delivery_token = Column(String(43), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)


class MediaPublicationImageSelection(Base):
    __tablename__ = "media_publication_image_selections"
    task_id = Column(Integer, ForeignKey("media_operation_tasks.id", ondelete="RESTRICT"), primary_key=True)
    image_id = Column(String(32), ForeignKey("media_publication_images.id", ondelete="RESTRICT"), nullable=False, index=True)


class MediaPublicationImageDelivery(Base):
    __tablename__ = "media_publication_image_deliveries"
    action_id = Column(Integer, ForeignKey("google_business_actions.id", ondelete="RESTRICT"), primary_key=True)
    image_id = Column(String(32), ForeignKey("media_publication_images.id", ondelete="RESTRICT"), nullable=False, index=True)
    activated_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
