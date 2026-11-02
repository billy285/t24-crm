"""Immutable owner planning versions. Never publishing authority or customer data."""
from core.database import Base
from sqlalchemy import Column,Integer,String,JSON,DateTime,UniqueConstraint

class MediaAutomationSettingVersion(Base):
    __tablename__="media_automation_setting_versions"
    __table_args__=(UniqueConstraint("owner_id","customer_id","revision",name="uq_media_setting_version"),)
    id=Column(Integer,primary_key=True)
    owner_id=Column(Integer,nullable=False,index=True)
    customer_id=Column(Integer,nullable=False,index=True)
    revision=Column(Integer,nullable=False)
    effective_from_month=Column(String(7),nullable=False)
    document=Column(JSON,nullable=False)
    preview_id=Column(String(36),nullable=False)
    created_at=Column(DateTime(timezone=True),nullable=False)

class MediaAutomationTemplateVersion(Base):
    __tablename__="media_automation_template_versions"
    __table_args__=(UniqueConstraint("owner_id","template_id","revision",name="uq_media_template_version"),)
    id=Column(Integer,primary_key=True)
    owner_id=Column(Integer,nullable=False,index=True)
    template_id=Column(String(36),nullable=False)
    revision=Column(Integer,nullable=False)
    name=Column(String(80),nullable=False)
    document=Column(JSON,nullable=False)
    created_at=Column(DateTime(timezone=True),nullable=False)

class MediaAutomationSettingsPreview(Base):
    __tablename__="media_automation_settings_previews"
    __table_args__=(UniqueConstraint("owner_id","request_id",name="uq_media_setting_preview_request"),)
    id=Column(String(36),primary_key=True)
    owner_id=Column(Integer,nullable=False,index=True)
    request_id=Column(String(36),nullable=False)
    fingerprint=Column(String(64),nullable=False)
    body=Column(JSON,nullable=False)
    state_hash=Column(String(64),nullable=False)
    result=Column(JSON,nullable=False)
    expires_at=Column(DateTime(timezone=True),nullable=False)
    created_at=Column(DateTime(timezone=True),nullable=False)

class MediaAutomationSettingsReceipt(Base):
    __tablename__="media_automation_settings_receipts"
    __table_args__=(UniqueConstraint("owner_id","request_id",name="uq_media_setting_apply_request"),)
    id=Column(Integer,primary_key=True)
    owner_id=Column(Integer,nullable=False,index=True)
    request_id=Column(String(36),nullable=False)
    fingerprint=Column(String(64),nullable=False)
    result=Column(JSON,nullable=False)
    created_at=Column(DateTime(timezone=True),nullable=False)
