from core.database import Base
from sqlalchemy import Column, DateTime, Integer, String


class Tasks(Base):
    __tablename__ = "tasks"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    title = Column(String, nullable=False)
    customer_id = Column(Integer, nullable=True)
    customer_name = Column(String, nullable=True)
    assignee_id = Column(Integer, nullable=True)
    assignee_name = Column(String, nullable=True)
    collaborator_names = Column(String, nullable=True)
    task_type = Column(String, nullable=True)
    priority = Column(String, nullable=True)
    status = Column(String, nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
    notes = Column(String, nullable=True)
    attachment_link = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)