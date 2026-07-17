from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func


class MerchantAiAnalyses(Base):
    """Versioned, source-bound sales analysis for a cleaned merchant record."""

    __tablename__ = "merchant_ai_analyses"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    merchant_id = Column(Integer, nullable=False, index=True)
    status = Column(String, nullable=False, default="ready")
    analysis_json = Column(Text, nullable=False)
    source_snapshot = Column(Text, nullable=False)
    ai_used = Column(Boolean, nullable=False, default=False)
    ai_model = Column(String, nullable=True)
    generated_by_id = Column(Integer, nullable=True)
    generated_by_name = Column(String, nullable=True)
    generated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
