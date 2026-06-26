from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.types import TypeDecorator
from app.db.database import Base


class _JSONB(TypeDecorator):  # pragma: no cover
    """JSONB on PostgreSQL, plain JSON on every other dialect (e.g. SQLite for tests)."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)

    # Flexible categorization
    type = Column(String, nullable=True, index=True)  # Product type (3rd level)
    category = Column(String, nullable=True, index=True)  # Top-level category
    subcategory = Column(String, nullable=True, index=True)  # 2nd level category
    tags = Column(_JSONB, nullable=True)
    brand = Column(String, nullable=True)
    price = Column(Integer, nullable=False)  # in cents/paise
    description = Column(String, nullable=True)
    in_stock = Column(Boolean, default=True)
    rating = Column(Float, default=0.0)
    attributes = Column(JSON, nullable=True)  # type-specific fields
    created_at = Column(DateTime(timezone=True), server_default=func.now())
