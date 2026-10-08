from core.database import Base
from sqlalchemy import Column, DateTime, Integer, String, Text, func


class MerchantImportBatch(Base):
    """An import receipt; previews never create merchant business records."""

    __tablename__ = "merchant_import_batches"

    id = Column(String(36), primary_key=True)
    filename = Column(String(255), nullable=False)
    file_sha256 = Column(String(64), nullable=False, index=True)
    active_file_key = Column(String(96), nullable=True, unique=True)
    template_version = Column(String(40), nullable=False, default="fixed-five-v1")
    created_by_id = Column(Integer, nullable=False, index=True)
    created_by_name = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False, default="preview", index=True)
    row_count = Column(Integer, nullable=False)
    rows_json = Column(Text, nullable=False)
    result_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    committed_at = Column(DateTime(timezone=True), nullable=True)
    reverted_at = Column(DateTime(timezone=True), nullable=True)
