from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from core.database import Base


class SalesLeadStar(Base):
    __tablename__ = "sales_lead_stars"

    # Employee and legacy accounts both use the ID returned by auth.
    user_id = Column(String(255), primary_key=True)
    lead_id = Column(Integer, ForeignKey("sales_leads.id", ondelete="CASCADE"), primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SalesLeadPriority(Base):
    __tablename__ = "sales_lead_priorities"

    lead_id = Column(Integer, ForeignKey("sales_leads.id", ondelete="CASCADE"), primary_key=True)
    marked_by = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
