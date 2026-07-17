from core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, func


class MerchantPool(Base):
    """Raw prospect merchants, isolated before they become sales leads."""

    __tablename__ = "merchant_pool"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    business_name = Column(String, nullable=False, index=True)
    contact_name = Column(String, nullable=True)
    phone = Column(String, nullable=True, index=True)
    industry = Column(String, nullable=True, index=True)
    country = Column(String, nullable=True)
    state = Column(String, nullable=True)
    city = Column(String, nullable=True, index=True)
    address = Column(String, nullable=True)
    website = Column(String, nullable=True, index=True)
    rating = Column(Float, nullable=True, index=True)
    google_business_url = Column(String, nullable=True)
    google_rating = Column(Float, nullable=True)
    google_review_count = Column(Integer, nullable=True)
    yelp_url = Column(String, nullable=True)
    yelp_rating = Column(Float, nullable=True)
    yelp_review_count = Column(Integer, nullable=True)
    social_profiles = Column(Text, nullable=True)
    recent_negative_reviews = Column(Text, nullable=True)
    content_update_summary = Column(Text, nullable=True)
    content_last_updated_at = Column(DateTime(timezone=True), nullable=True)
    data_source = Column(String, nullable=False, default="manual", index=True)
    source_record_id = Column(String, nullable=True)
    collected_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    business_status = Column(String, nullable=True)
    pool_status = Column(String, nullable=False, default="pending", index=True)
    isolation_reason = Column(String, nullable=True)
    duplicate_of_id = Column(Integer, nullable=True)
    existing_customer_id = Column(Integer, nullable=True)
    converted_lead_id = Column(Integer, nullable=True)
    raw_payload = Column(Text, nullable=True)
    created_by_id = Column(Integer, nullable=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
