from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.db.database import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(String, nullable=False, index=True)
    product_name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    carrier = Column(String, nullable=True)
    tracking_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())