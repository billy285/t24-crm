from core.database import Base
from sqlalchemy import Column, DateTime, Integer, String


class Operation_logs(Base):
    __tablename__ = "operation_logs"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    user_id = Column(String, nullable=False)
    customer_id = Column(Integer, nullable=True)
    action_type = Column(String, nullable=False)
    action_detail = Column(String, nullable=True)
    operator_name = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)