from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, JSON, ForeignKey
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


class ProductType(Base):
    """A kind of product shoppers ask for, with the attributes they filter on (ADR 0005)."""

    __tablename__ = "product_types"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    category = Column(String, nullable=False)
    served = Column(Boolean, nullable=False, default=True)  # false: in the DB but not sold
    synonyms = Column(_JSONB, nullable=False, default=list)
    suggestion = Column(String, nullable=True)  # served = false: what to offer instead
    attribute_schema = Column(_JSONB, nullable=False, default=dict)


class Brand(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    aliases = Column(_JSONB, nullable=False, default=list)


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
    attributes = Column(_JSONB, nullable=True)  # type-specific fields, validated against the type's schema
    img_link = Column(String, nullable=True)  # product photo, shown on the chat's product cards
    product_link = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Typed catalog (ADR 0005), filled by scripts/enrich_catalog.py apply. The raw columns above stay.
    type_id = Column(Integer, ForeignKey("product_types.id"), nullable=True, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=True, index=True)
    title = Column(String, nullable=True)  # short, clean name
    extracted_by = Column(String, nullable=True)  # regex | llm | human
    confidence = Column(Float, nullable=True)
