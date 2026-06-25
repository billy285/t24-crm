from core.database import Base
from sqlalchemy import Column, DateTime, Integer, String, Text


class Employees(Base):
    __tablename__ = "employees"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    user_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    password = Column(String, nullable=True)
    status = Column(String, nullable=True)
    employee_code = Column(String, nullable=True)
    department = Column(String, nullable=True)
    position = Column(String, nullable=True)
    login_username = Column(String, nullable=True)
    hire_date = Column(String, nullable=True)
    supervisor = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
