from core.database import Base
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func


class SalesLabel(Base):
    __tablename__ = "sales_labels"
    __table_args__ = (
        UniqueConstraint("kind", "normalized_name", name="uq_sales_labels_kind_name"),
        CheckConstraint("kind IN ('source', 'provider', 'operation')", name="ck_sales_labels_kind"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String(60), nullable=False)
    normalized_name = Column(String(180), nullable=False)
    kind = Column(String(16), nullable=False)
    industry = Column(String(16), nullable=False, default="all", server_default="all")
    archived = Column(Boolean, nullable=False, default=False, server_default="0")


class SalesLabelAssignment(Base):
    __tablename__ = "sales_label_assignments"
    __table_args__ = (
        CheckConstraint("(merchant_id IS NULL) <> (lead_id IS NULL)", name="ck_sales_label_assignment_target"),
        UniqueConstraint("merchant_id", "label_id", name="uq_sales_label_merchant"),
        UniqueConstraint("lead_id", "label_id", name="uq_sales_label_lead"),
        Index("ix_sales_label_target", "label_id", "merchant_id", "lead_id"),
    )

    id = Column(Integer, primary_key=True)
    label_id = Column(ForeignKey("sales_labels.id", ondelete="CASCADE"), nullable=False)
    merchant_id = Column(ForeignKey("merchant_pool.id", ondelete="CASCADE"))
    lead_id = Column(ForeignKey("sales_leads.id", ondelete="CASCADE"))
    confirmed = Column(Boolean, nullable=False, default=False, server_default="0")
    confirmed_by = Column(Integer)
    confirmed_at = Column(DateTime(timezone=True))
    import_batch_id = Column(String(36))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
