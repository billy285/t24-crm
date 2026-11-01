"""Additive owner-only Meta pilot records; no finance or shared grants."""
from core.database import Base
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text


class MetaOperationsCredential(Base):
    __tablename__ = "meta_operations_credentials"
    __table_args__ = (UniqueConstraint("owner_id", "connection_id", name="uq_meta_ops_credential_owner_connection"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, nullable=False, index=True)
    connection_id = Column(Integer, ForeignKey("meta_business_connections.id", ondelete="RESTRICT"), nullable=False)
    token_encrypted = Column(Text, nullable=True)
    granted_scopes = Column(JSON, nullable=False, default=list, server_default="[]")
    active = Column(Boolean, nullable=False, default=True, server_default="1")
    needs_reconnect = Column(Boolean, nullable=False, default=False, server_default="0")
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    last_error = Column(String(40), nullable=True)
    connected_at = Column(DateTime(timezone=True), nullable=False)


class MetaOperationsOAuthState(Base):
    __tablename__ = "meta_operations_oauth_states"
    __table_args__ = (UniqueConstraint("owner_id", "request_id", name="uq_meta_ops_oauth_request"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, nullable=False)
    request_id = Column(String(36), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    state_hash = Column(String(64), nullable=False, unique=True)
    cookie_hash = Column(String(64), nullable=False)
    flow_encrypted = Column(Text, nullable=False)
    connection_id = Column(Integer, nullable=False)
    connection_revision = Column(Integer, nullable=False)
    expected_credential_revision = Column(Integer, nullable=True)
    targets_snapshot = Column(JSON, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    consumed = Column(Boolean, nullable=False, default=False, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False)


class MetaOperationsBinding(Base):
    """Independent owner-approved operating grant; the old row is provenance."""
    __tablename__ = "meta_operations_bindings"
    __table_args__ = (CheckConstraint("id = source_binding_id", name="ck_meta_ops_binding_source_identity"),
        CheckConstraint("platform IN ('facebook','instagram')", name="ck_meta_ops_binding_platform"),
        Index("uq_meta_ops_active_customer_platform", "customer_id", "platform", unique=True,
              sqlite_where=text("active = 1"), postgresql_where=text("active")),
        Index("uq_meta_ops_active_global_asset", "platform", "external_id", unique=True,
              sqlite_where=text("active = 1"), postgresql_where=text("active")))
    id = Column(Integer, ForeignKey("meta_business_bindings.id", ondelete="RESTRICT"), primary_key=True, autoincrement=False)
    source_binding_id = Column(Integer, ForeignKey("meta_business_bindings.id", ondelete="RESTRICT"), nullable=False)
    owner_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, nullable=False, index=True)
    customer_name = Column(String(255), nullable=False)
    platform = Column(String(16), nullable=False)
    external_id = Column(String(80), nullable=False)
    page_id = Column(String(80), nullable=False)
    asset_name = Column(String(255), nullable=False)
    asset_username = Column(String(255), nullable=True)
    connection_id = Column(Integer, ForeignKey("meta_business_connections.id", ondelete="RESTRICT"), nullable=False)
    credential_id = Column(Integer, ForeignKey("meta_operations_credentials.id", ondelete="RESTRICT"), nullable=False)
    connection_revision = Column(Integer, nullable=False)
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    active = Column(Boolean, nullable=False, default=True, server_default="1")
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MetaOperationsMedia(Base):
    __tablename__ = "meta_operations_media"
    id = Column(String(32), primary_key=True)
    owner_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, nullable=False, index=True)
    source_sha256 = Column(String(64), nullable=False)
    sha256 = Column(String(64), nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    byte_size = Column(Integer, nullable=False)
    file_stat = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class MetaOperationsTarget(Base):
    """Opaque, expiring references to comments/posts read from the provider."""
    __tablename__ = "meta_operations_targets"
    __table_args__ = (CheckConstraint("kind IN ('post','comment')", name="ck_meta_ops_target_kind"),)
    id = Column(String(32), primary_key=True)
    owner_id = Column(Integer, nullable=False, index=True)
    binding_id = Column(Integer, ForeignKey("meta_business_bindings.id", ondelete="RESTRICT"), nullable=False, index=True)
    binding_revision = Column(Integer, nullable=False)
    kind = Column(String(16), nullable=False)
    external_id = Column(String(200), nullable=False)
    parent_external_id = Column(String(200), nullable=True)
    parent_ref = Column(String(32), nullable=True)
    snapshot = Column(JSON, nullable=False)
    version = Column(String(64), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class MetaOperationsDraft(Base):
    __tablename__ = "meta_operations_drafts"
    __table_args__ = (CheckConstraint("kind IN ('post','reply')", name="ck_meta_ops_draft_kind"),
                     CheckConstraint("status IN ('draft','approved')", name="ck_meta_ops_draft_status"))
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, nullable=False, index=True)
    binding_id = Column(Integer, ForeignKey("meta_business_bindings.id", ondelete="RESTRICT"), nullable=False, index=True)
    kind = Column(String(16), nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    media_id = Column(String(32), ForeignKey("meta_operations_media.id", ondelete="RESTRICT"), nullable=True)
    target_ref = Column(String(32), ForeignKey("meta_operations_targets.id", ondelete="RESTRICT"), nullable=True)
    expected_target_version = Column(String(64), nullable=True)
    status = Column(String(16), nullable=False, default="draft", server_default="draft")
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    preview_hash = Column(String(64), nullable=True)
    approved_snapshot = Column(JSON, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MetaOperationsAction(Base):
    __tablename__ = "meta_operations_actions"
    __table_args__ = (UniqueConstraint("owner_id", "request_id", name="uq_meta_ops_action_request"),
                     UniqueConstraint("draft_id", "draft_revision", name="uq_meta_ops_draft_dispatch"))
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, nullable=False, index=True)
    binding_id = Column(Integer, ForeignKey("meta_business_bindings.id", ondelete="RESTRICT"), nullable=False, index=True)
    binding_revision = Column(Integer, nullable=False)
    connection_revision = Column(Integer, nullable=False)
    draft_id = Column(Integer, ForeignKey("meta_operations_drafts.id", ondelete="RESTRICT"), nullable=False)
    draft_revision = Column(Integer, nullable=False)
    kind = Column(String(16), nullable=False)
    request_id = Column(String(36), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    preview_hash = Column(String(64), nullable=False)
    submitted_snapshot = Column(JSON, nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String(16), nullable=False, default="pending", server_default="pending")
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    dispatch_stage = Column(String(32), nullable=False, default="reserved", server_default="reserved")
    dispatch_started_at = Column(DateTime(timezone=True), nullable=True)
    progress = Column(JSON, nullable=True)
    provider_id = Column(String(200), nullable=True)
    provider_url = Column(Text, nullable=True)
    delivery_token = Column(String(43), nullable=True, unique=True)
    delivery_expires_at = Column(DateTime(timezone=True), nullable=True)
    message = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MetaOperationsSchedule(Base):
    __tablename__ = "meta_operations_schedules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, nullable=False, index=True)
    binding_id = Column(Integer, ForeignKey("meta_business_bindings.id", ondelete="RESTRICT"), nullable=False, index=True)
    draft_id = Column(Integer, ForeignKey("meta_operations_drafts.id", ondelete="RESTRICT"), nullable=False)
    draft_revision = Column(Integer, nullable=False)
    preview_hash = Column(String(64), nullable=False)
    submitted_snapshot = Column(JSON, nullable=False)
    planned_at = Column(DateTime(timezone=True), nullable=False, index=True)
    timezone = Column(String(80), nullable=False)
    request_id = Column(String(36), nullable=False, unique=True)
    status = Column(String(16), nullable=False, default="prepared", server_default="prepared", index=True)
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    action_id = Column(Integer, ForeignKey("meta_operations_actions.id", ondelete="RESTRICT"), nullable=True)
    message = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MetaOperationsRequest(Base):
    __tablename__ = "meta_operations_requests"
    __table_args__ = (UniqueConstraint("owner_id", "request_id", name="uq_meta_ops_request"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, nullable=False)
    request_id = Column(String(36), nullable=False)
    kind = Column(String(16), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    result_id = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
