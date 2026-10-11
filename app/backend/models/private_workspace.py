"""Private workspace tables belong only to the separate private database."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import BigInteger, Column, DateTime, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase


def utcnow():
    return datetime.now(timezone.utc)


class PrivateWorkspaceBase(DeclarativeBase):
    # Deliberately unrelated to core.database.Base and the CRM migrations.
    pass


class PrivateConnection(PrivateWorkspaceBase):
    __tablename__ = "private_connections"
    __table_args__ = (UniqueConstraint("owner_id", "source_id", name="uq_private_owner_source"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id = Column(String(64), nullable=False, index=True)
    source_id = Column(String(32), nullable=False)
    status = Column(String(24), nullable=False, default="disconnected")
    encrypted_credentials = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=False, default=dict)
    last_sync = Column(DateTime(timezone=True), nullable=True)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(String(240), nullable=True)
    oauth_state_hash = Column(String(64), nullable=True, unique=True)
    oauth_expires_at = Column(DateTime(timezone=True), nullable=True)
    oauth_used_at = Column(DateTime(timezone=True), nullable=True)
    generation = Column(Integer, nullable=False, default=0)
    sync_lease_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class PrivateItem(PrivateWorkspaceBase):
    __tablename__ = "private_items"
    __table_args__ = (UniqueConstraint("owner_id", "source_id", "external_id", name="uq_private_item_source_key"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id = Column(String(64), nullable=False, index=True)
    source_id = Column(String(32), nullable=False)
    external_id = Column(String(512), nullable=False)
    kind = Column(String(48), nullable=False)
    title = Column(String(240), nullable=False)
    summary = Column(Text, nullable=False, default="")
    local_title = Column(String(240), nullable=True)
    local_summary = Column(Text, nullable=True)
    status = Column(String(64), nullable=False)
    priority = Column(String(16), nullable=False, default="normal")
    amount_minor = Column(BigInteger, nullable=True)
    currency = Column(String(8), nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=True)
    due_at = Column(DateTime(timezone=True), nullable=True)
    source_url = Column(Text, nullable=True)
    evidence = Column(JSON, nullable=False, default=dict)
    action_status = Column(String(16), nullable=False, default="open")
    snoozed_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class PrivatePreferences(PrivateWorkspaceBase):
    __tablename__ = "private_preferences"
    owner_id = Column(String(64), primary_key=True)
    preferences_json = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class PrivateSyncRun(PrivateWorkspaceBase):
    __tablename__ = "private_sync_runs"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id = Column(String(64), nullable=False, index=True)
    source_id = Column(String(32), nullable=False)
    status = Column(String(24), nullable=False, default="running")
    started_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_count = Column(Integer, nullable=False, default=0)
    updated_count = Column(Integer, nullable=False, default=0)
    error = Column(String(240), nullable=True)


class PrivateMailTranslation(PrivateWorkspaceBase):
    __tablename__ = "private_mail_translations"
    # Mail text is encrypted; this index contains identifiers and hashes only.
    cache_key = Column(String(64), primary_key=True)
    owner_id = Column(String(64), nullable=False, index=True)
    connection_id = Column(String(36), nullable=False)
    generation = Column(Integer, nullable=False)
    item_id = Column(String(36), nullable=False, index=True)
    source_hash = Column(String(64), nullable=False)
    mode = Column(String(12), nullable=False)
    state = Column(String(16), nullable=False, default="pending")
    lease_token = Column(String(64), nullable=True)
    lease_until = Column(DateTime(timezone=True), nullable=True)
    encrypted_content = Column(Text, nullable=True)
    error_code = Column(String(40), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class PrivateTranslationUsage(PrivateWorkspaceBase):
    __tablename__ = "private_translation_usage"
    owner_id = Column(String(64), primary_key=True)
    month = Column(String(7), primary_key=True)
    # Reservations include failed/ambiguous requests; never risk undercounting.
    characters = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
