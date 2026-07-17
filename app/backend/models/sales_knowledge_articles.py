from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func


class SalesKnowledgeArticles(Base):
    """Internal, versioned guidance for the isolated phone-sales team."""

    __tablename__ = "sales_knowledge_articles"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    category = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False, index=True)
    customer_question = Column(Text, nullable=True)
    standard_answer = Column(Text, nullable=False)
    action_steps = Column(Text, nullable=True)
    related_links = Column(Text, nullable=True)
    escalation_rule = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="draft", index=True)
    is_sensitive = Column(Boolean, nullable=False, default=False)
    sort_order = Column(Integer, nullable=False, default=0)
    created_by_id = Column(Integer, nullable=True)
    created_by_name = Column(String, nullable=True)
    published_by_id = Column(Integer, nullable=True)
    published_by_name = Column(String, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SalesKnowledgeQuestions(Base):
    """Unanswered sales questions retained for manager review and knowledge updates."""

    __tablename__ = "sales_knowledge_questions"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    question = Column(Text, nullable=False)
    context = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="open", index=True)
    submitted_by_id = Column(Integer, nullable=True, index=True)
    submitted_by_name = Column(String, nullable=True)
    resolved_article_id = Column(Integer, nullable=True, index=True)
    resolved_by_id = Column(Integer, nullable=True)
    resolved_by_name = Column(String, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
