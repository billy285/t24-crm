"""Private, bounded evidence for the separate finance registration queue."""

from core.database import Base
from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, String


class FinanceEntryAttachment(Base):
    __tablename__ = "finance_entry_attachments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    draft_id = Column(Integer, ForeignKey("finance_entry_drafts.id", ondelete="RESTRICT"), nullable=False, index=True)
    uploaded_by_id = Column(Integer, nullable=False)
    filename = Column(String(180), nullable=False)
    media_type = Column(String(80), nullable=False)
    byte_size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    content = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    removed_at = Column(DateTime(timezone=True), nullable=True)
    removed_by_id = Column(Integer, nullable=True)
