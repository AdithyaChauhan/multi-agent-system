"""Product search over the typed catalog (ADR 0005): type, attributes, brand, price and rating.

Only served types are searched, so phones, laptops and tablets never appear. Type, brand, price,
rating and keywords filter in SQL; attribute filters run in Python on the matching rows (at most a
few hundred per type), which keeps the same code working on Postgres and on SQLite in tests.
"""

from typing import List, Optional

from sqlalchemy import or_

from app.catalog.features import attributes_match
from app.catalog.runtime import get_catalog
from app.core.logger import get_logger, get_request_id
from app.db.database import SessionLocal
from app.models.product import Brand, Product, ProductType

logger = get_logger("app.tools.product_tools")


def product_dict(p: Product, type_name: Optional[str], brand_name: Optional[str]) -> dict:
    """One search result, as every node after search sees it (and the chat UI's product cards)."""
    return {
        "product_id": p.product_id,
        "name": p.name,
        "title": p.title or p.name,
        "type": type_name,
        "brand": brand_name or p.brand,
        "price": p.price,
        "rating": float(p.rating) if p.rating else None,
        "description": p.description,
        "attributes": p.attributes or {},
        "image": p.img_link,
        "link": p.product_link,
    }


def search_products(
    product_type: Optional[str] = None,
    attributes: Optional[dict] = None,
    brand: Optional[str] = None,
    max_price: Optional[int] = None,
    min_price: Optional[int] = None,
    min_rating: Optional[float] = None,
    keywords: Optional[List[str]] = None,
    limit: int = 20,
) -> List[dict]:
    """Best-rated products matching every given filter.

    Args:
        product_type: a product_types.name ("tv"); None searches every served type
        attributes: {attribute: value} filters from the type's schema ({"screen_inches": 43})
        brand: as the shopper wrote it; resolved through brand aliases and typo matching
        max_price, min_price: rupees
        min_rating: out of 5
        keywords: words that must all appear in the product name or title
        limit: maximum results
    """
    brand_id = None
    if brand:
        resolved = get_catalog().resolve_brand(brand)
        if resolved is None:
            return []  # a brand we don't carry: nothing matches
        brand_id, canonical = resolved
        if canonical.lower() != brand.lower():
            logger.info(f"request_id={get_request_id()} | brand_resolved | {brand!r} → {canonical!r}")

    db = SessionLocal()
    try:
        query = db.query(Product, ProductType.name, Brand.name).join(ProductType, Product.type_id == ProductType.id)
        query = query.outerjoin(Brand, Product.brand_id == Brand.id)
        query = query.filter(ProductType.served.is_(True))
        if product_type:
            query = query.filter(ProductType.name == product_type)
        if brand_id is not None:
            query = query.filter(Product.brand_id == brand_id)
        if max_price is not None:
            query = query.filter(Product.price <= max_price)
        if min_price is not None:
            query = query.filter(Product.price >= min_price)
        if min_rating is not None:
            query = query.filter(Product.rating >= min_rating)
        for keyword in keywords or []:
            query = query.filter(or_(Product.name.ilike(f"%{keyword}%"), Product.title.ilike(f"%{keyword}%")))

        # Best-rated first, so the ranker sees the strongest candidates and runs are repeatable
        query = query.order_by(Product.rating.desc().nulls_last(), Product.product_id)
        rows = query.all() if attributes else query.limit(limit).all()
        results = []
        for p, type_name, brand_name in rows:
            if attributes and not attributes_match(p.attributes, attributes):
                continue
            results.append(product_dict(p, type_name, brand_name))
            if len(results) >= limit:
                break
        return results
    finally:
        db.close()
