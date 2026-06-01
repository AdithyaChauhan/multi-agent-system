from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.db.database import Base


class Spec(Base):
    __tablename__ = "specs"

    id = Column(Integer, primary_key=True, index=True)
    spec_id = Column(String, unique=True, index=True, nullable=True)
    product_id = Column(String, ForeignKey("products.product_id"), nullable=False, index=True)
    spec_key = Column(String, nullable=False)
    spec_value = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
