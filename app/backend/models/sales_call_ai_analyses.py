from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func


class SalesCallAiAnalyses(Base):
    """Versioned post-call analysis. Original AI output remains immutable after review."""

    __tablename__ = "sales_call_ai_analyses"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    call_activity_id = Column(Integer, nullable=False, index=True)
    lead_id = Column(Integer, nullable=False, index=True)
    transcript = Column(Text, nullable=False)
    transcript_source = Column(String, nullable=False, default="manual_transcript")
    original_analysis_json = Column(Text, nullable=False)
    reviewed_analysis_json = Column(Text, nullable=True)
    ai_provider = Column(String, nullable=True)
    ai_model = Column(String, nullable=True)
    needs_manager_intervention = Column(Boolean, nullable=False, default=False, index=True)
    reviewed_by_id = Column(Integer, nullable=True)
    reviewed_by_name = Column(String, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
