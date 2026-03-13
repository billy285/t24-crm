from core.database import Base
from sqlalchemy import Column, Integer, String


class Service_tasks(Base):
    __tablename__ = "service_tasks"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    service_progress_id = Column(Integer, nullable=True)
    customer_id = Column(Integer, nullable=False)
    task_name = Column(String, nullable=False)
    task_type = Column(String, nullable=True)
    assignee_name = Column(String, nullable=True)
    priority = Column(String, nullable=True)
    status = Column(String, nullable=False)
    due_date = Column(String, nullable=True)
    completed_date = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    user_id = Column(String, nullable=False)
    created_at = Column(String, nullable=True)