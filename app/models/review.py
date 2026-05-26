from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.db.database import Base


class Review(Base):
    __tablename__ = "reviews"

    id          = Column(Integer, primary_key=True, index=True)
    review_id   = Column(String, unique=True, index=True, nullable=True)
    product_id  = Column(String, ForeignKey("products.product_id"), nullable=False, index=True)
    rating      = Column(Float, nullable=False)
    review_text = Column(String, nullable=False)
    reviewer    = Column(String, nullable=False)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())