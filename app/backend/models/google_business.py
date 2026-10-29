"""Additive CRM Google Business integration; no shared permissions or private data."""
from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func


class GoogleBusinessConnection(Base):
    __tablename__ = "google_business_connections"
    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(Integer, nullable=False, index=True)
    label = Column(String(255), nullable=False)
    token_encrypted = Column(Text, nullable=True)
    active = Column(Boolean, nullable=False, default=True, server_default="1")
    needs_reconnect = Column(Boolean, nullable=False, default=False, server_default="0")
    last_error = Column(String(100), nullable=True)
    connected_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GoogleBusinessOAuthState(Base):
    __tablename__ = "google_business_oauth_states"
    id = Column(Integer, primary_key=True, autoincrement=True)
    state_hash = Column(String(64), nullable=False, unique=True)
    cookie_hash = Column(String(64), nullable=False)
    owner_id = Column(Integer, nullable=False)
    verifier_encrypted = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    consumed = Column(Boolean, nullable=False, default=False, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GoogleBusinessBinding(Base):
    __tablename__ = "google_business_bindings"
    __table_args__ = (UniqueConstraint("customer_id", name="uq_google_business_customer"),
                     UniqueConstraint("location_name", name="uq_google_business_location"),
                     UniqueConstraint("location_id", name="uq_google_business_global_location"))
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False, index=True)
    customer_name = Column(String(255), nullable=False)
    connection_id = Column(Integer, ForeignKey("google_business_connections.id", ondelete="RESTRICT"), nullable=False)
    location_name = Column(String(200), nullable=False)
    location_id = Column(String(100), nullable=False, default=lambda ctx: ctx.get_current_parameters()["location_name"].rsplit("/", 1)[1])
    title = Column(String(255), nullable=False)
    address = Column(Text, nullable=False, default="", server_default="")
    active = Column(Boolean, nullable=False, default=True, server_default="1")
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    created_by_id = Column(Integer, nullable=False)
    request_id = Column(String(36), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GoogleBusinessGrant(Base):
    __tablename__ = "google_business_grants"
    __table_args__ = (UniqueConstraint("binding_id", "employee_id", name="uq_google_business_grant"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    binding_id = Column(Integer, ForeignKey("google_business_bindings.id", ondelete="RESTRICT"), nullable=False, index=True)
    employee_id = Column(Integer, nullable=False, index=True)
    can_reply = Column(Boolean, nullable=False, default=False, server_default="0")
    can_publish = Column(Boolean, nullable=False, default=False, server_default="0")
    granted_by_id = Column(Integer, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GoogleBusinessAction(Base):
    __tablename__ = "google_business_actions"
    __table_args__ = (UniqueConstraint("actor_id", "request_id", name="uq_google_business_action_request"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    binding_id = Column(Integer, ForeignKey("google_business_bindings.id", ondelete="RESTRICT"), nullable=False, index=True)
    customer_id = Column(Integer, nullable=False)
    kind = Column(String(32), nullable=False)
    request_id = Column(String(36), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    actor_id = Column(Integer, nullable=False)
    actor_name = Column(String(255), nullable=False)
    task_id = Column(Integer, nullable=True, index=True)
    target_name = Column(String(255), nullable=True)
    payload = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False, default="pending", server_default="pending")
    dispatch_started_at = Column(DateTime(timezone=True), nullable=True)
    provider_name = Column(String(255), nullable=True)
    provider_state = Column(String(32), nullable=True)
    provider_url = Column(Text, nullable=True)
    message = Column(String(255), nullable=False, default="", server_default="")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
