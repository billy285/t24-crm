from sqlalchemy import Column, Integer, String, Boolean, UniqueConstraint
from .base import Base

class SystemOption(Base):
    __tablename__ = "system_options"
    __table_args__ = (UniqueConstraint('category', 'key', name='_category_key_uc'),)

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, index=True, nullable=False)
    key = Column(String, index=True, nullable=False)
    label = Column(String, nullable=False)
    order = Column(Integer, default=0)
    is_enabled = Column(Boolean, default=True)
