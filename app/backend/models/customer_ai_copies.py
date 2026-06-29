from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text


class Customer_ai_copies(Base):
    __tablename__ = "customer_ai_copies"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    user_id = Column(String, nullable=False)
    customer_id = Column(Integer, nullable=False)
    customer_name = Column(String, nullable=True)
    platform = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    language = Column(String, nullable=True)
    tone = Column(String, nullable=True)
    title = Column(String, nullable=True)
    content = Column(Text, nullable=False)
    prompt = Column(Text, nullable=True)
    extra_requirements = Column(Text, nullable=True)
    status = Column(String, nullable=True)
    generated_by = Column(String, nullable=True)
    ai_model = Column(String, nullable=True)
    is_ai_generated = Column(Boolean, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
