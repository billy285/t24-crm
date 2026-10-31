"""Isolated Meta connection metadata. No tokens enter customer account records."""
from core.database import Base
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text


class MetaBusinessConnection(Base):
    __tablename__ = "meta_business_connections"
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, nullable=False, index=True)
    label = Column(String(255), nullable=False)
    token_encrypted = Column(Text, nullable=True)
    granted_scopes = Column(JSON, nullable=False, default=list, server_default="[]")
    active = Column(Boolean, nullable=False, default=True, server_default="1")
    needs_reconnect = Column(Boolean, nullable=False, default=False, server_default="0")
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    last_error = Column(String(40), nullable=True)
    connected_at = Column(DateTime(timezone=True), nullable=False)


class MetaBusinessOAuthState(Base):
    __tablename__ = "meta_business_oauth_states"
    __table_args__ = (UniqueConstraint("owner_id", "request_id", name="uq_meta_oauth_request"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, nullable=False)
    request_id = Column(String(36), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    state_hash = Column(String(64), nullable=False, unique=True)
    cookie_hash = Column(String(64), nullable=False)
    flow_encrypted = Column(Text, nullable=False)
    reconnect_connection_id = Column(Integer, nullable=True)
    expected_revision = Column(Integer, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    consumed = Column(Boolean, nullable=False, default=False, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False)


class MetaBusinessAsset(Base):
    """Short-lived opaque discovery references; external IDs remain server-side."""
    __tablename__ = "meta_business_assets"
    __table_args__ = (CheckConstraint("platform IN ('facebook','instagram')", name="ck_meta_asset_platform"),)
    id = Column(String(32), primary_key=True)
    connection_id = Column(Integer, ForeignKey("meta_business_connections.id", ondelete="RESTRICT"), nullable=False, index=True)
    connection_revision = Column(Integer, nullable=False)
    platform = Column(String(16), nullable=False)
    external_id = Column(String(80), nullable=False)
    page_id = Column(String(80), nullable=False)
    name = Column(String(255), nullable=False)
    username = Column(String(255), nullable=True)
    linked_page_name = Column(String(255), nullable=True)
    observations = Column(JSON, nullable=False)
    active = Column(Boolean, nullable=False, default=True, server_default="1")
    expires_at = Column(DateTime(timezone=True), nullable=False)


class MetaBusinessBinding(Base):
    __tablename__ = "meta_business_bindings"
    __table_args__ = (Index("uq_meta_active_customer_platform", "customer_id", "platform", unique=True,
                           sqlite_where=text("active = 1"), postgresql_where=text("active")),
                     Index("uq_meta_active_global_asset", "platform", "external_id", unique=True,
                           sqlite_where=text("active = 1"), postgresql_where=text("active")),
                     CheckConstraint("platform IN ('facebook','instagram')", name="ck_meta_binding_platform"))
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, nullable=False, index=True)
    customer_name = Column(String(255), nullable=False)
    connection_id = Column(Integer, ForeignKey("meta_business_connections.id", ondelete="RESTRICT"), nullable=False)
    connection_revision = Column(Integer, nullable=False)
    platform = Column(String(16), nullable=False)
    external_id = Column(String(80), nullable=False)
    page_id = Column(String(80), nullable=False)
    asset_name = Column(String(255), nullable=False)
    asset_username = Column(String(255), nullable=True)
    active = Column(Boolean, nullable=False, default=True, server_default="1")
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MetaBusinessRequest(Base):
    """Durable owner-scoped binding requests; replay never restores a grant."""
    __tablename__ = "meta_business_requests"
    __table_args__ = (UniqueConstraint("owner_id", "request_id", name="uq_meta_management_request"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, nullable=False)
    request_id = Column(String(36), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    binding_id = Column(Integer, ForeignKey("meta_business_bindings.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
