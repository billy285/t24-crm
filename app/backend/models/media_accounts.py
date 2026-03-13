from core.database import Base
from sqlalchemy import Column, DateTime, Integer, String


class Media_accounts(Base):
    __tablename__ = "media_accounts"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    user_id = Column(String, nullable=False)
    customer_id = Column(Integer, nullable=False)
    platform_name = Column(String, nullable=False)
    account_name = Column(String, nullable=True)
    login_email = Column(String, nullable=True)
    login_password = Column(String, nullable=True)
    bound_phone = Column(String, nullable=True)
    profile_url = Column(String, nullable=True)
    account_status = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)