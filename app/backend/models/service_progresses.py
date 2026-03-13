from core.database import Base
from sqlalchemy import Boolean, Column, Integer, String


class Service_progresses(Base):
    __tablename__ = "service_progresses"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    customer_id = Column(Integer, nullable=False)
    customer_name = Column(String, nullable=True)
    service_type = Column(String, nullable=True)
    service_stage = Column(String, nullable=False)
    progress_percent = Column(Integer, nullable=True)
    sales_person = Column(String, nullable=True)
    ops_person = Column(String, nullable=True)
    design_person = Column(String, nullable=True)
    package_name = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    country = Column(String, nullable=True)
    state = Column(String, nullable=True)
    city = Column(String, nullable=True)
    service_start_date = Column(String, nullable=True)
    service_end_date = Column(String, nullable=True)
    last_update_time = Column(String, nullable=True)
    last_update_person = Column(String, nullable=True)
    last_work_summary = Column(String, nullable=True)
    issue_status = Column(String, nullable=True)
    issue_description = Column(String, nullable=True)
    issue_found_date = Column(String, nullable=True)
    issue_owner = Column(String, nullable=True)
    issue_resolved = Column(Boolean, nullable=True)
    issue_resolved_date = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    user_id = Column(String, nullable=False)
    created_at = Column(String, nullable=True)