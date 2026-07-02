from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text


class Customer_menu_items(Base):
    __tablename__ = "customer_menu_items"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    user_id = Column(String, nullable=True)
    customer_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    item_type = Column(String, nullable=True)
    category = Column(String, nullable=True)
    price = Column(String, nullable=True)
    selling_points = Column(Text, nullable=True)
    suitable_platforms = Column(Text, nullable=True)
    is_featured = Column(Boolean, nullable=True)
    status = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
