"""Private render jobs and explicit derivative adoption; no publication queue."""
from core.database import Base
from sqlalchemy import Column, DateTime, Integer, JSON, String, UniqueConstraint


class MediaAssetProfile(Base):
    __tablename__ = "media_asset_profiles"
    owner_id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, primary_key=True)
    revision = Column(Integer, nullable=False)
    settings = Column(JSON, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MediaAssetJob(Base):
    __tablename__ = "media_asset_jobs"
    __table_args__ = (UniqueConstraint("owner_id", "request_id", name="uq_media_asset_job_request"),)
    id = Column(String(32), primary_key=True)
    owner_id = Column(Integer, nullable=False)
    customer_id = Column(Integer, nullable=False, index=True)
    request_id = Column(String(36), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    revision = Column(Integer, nullable=False)
    kind = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False)
    snapshot = Column(JSON, nullable=False)
    attempt = Column(Integer, nullable=False)
    lease_token = Column(String(32))
    lease_at = Column(DateTime(timezone=True))
    output = Column(JSON)
    adoption = Column(JSON)
    error_code = Column(String(40))
    message = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MediaAssetRequest(Base):
    __tablename__ = "media_asset_requests"
    __table_args__ = (UniqueConstraint("owner_id", "request_id", name="uq_media_asset_request"),)
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, nullable=False)
    customer_id = Column(Integer, nullable=False)
    request_id = Column(String(36), nullable=False)
    kind = Column(String(16), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    result = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
