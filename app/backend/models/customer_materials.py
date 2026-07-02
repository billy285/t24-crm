from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text


class Customer_materials(Base):
    __tablename__ = "customer_materials"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    user_id = Column(String, nullable=False)
    customer_id = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    material_type = Column(String, nullable=False)
    platform = Column(String, nullable=True)
    source_type = Column(String, nullable=True)
    file_name = Column(String, nullable=True)
    file_path = Column(String, nullable=True)
    file_url = Column(Text, nullable=True)
    thumbnail_url = Column(Text, nullable=True)
    content_type = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    linked_item_id = Column(Integer, nullable=True)
    linked_item_snapshot = Column(String, nullable=True)
    usage_status = Column(String, nullable=True)
    approval_status = Column(String, nullable=True)
    copyright_status = Column(String, nullable=True)
    is_favorite = Column(Boolean, nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
