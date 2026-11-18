import time
import threading
from typing import Optional, List
from sqlalchemy import or_, cast, String
from app.db.database import SessionLocal
from app.models.product import Product
from app.core.logger import get_logger, get_request_id
from rapidfuzz import process, fuzz

logger = get_logger("app.tools.product_tools")

_BRAND_CACHE: dict = {"brands": [], "ts": 0.0}
_BRAND_LOCK = threading.Lock()
_BRAND_TTL = 300  # seconds


def _get_known_brands() -> list[str]:
    now = time.time()
    with _BRAND_LOCK:
        if now - _BRAND_CACHE["ts"] < _BRAND_TTL and _BRAND_CACHE["brands"]:
            return _BRAND_CACHE["brands"]
        db = SessionLocal()
        try:
            rows = db.query(Product.brand).filter(Product.brand.isnot(None)).distinct().all()
            brands = [r[0] for r in rows if r[0] and len(r[0]) > 2]
            _BRAND_CACHE["brands"] = brands
            _BRAND_CACHE["ts"] = now
            return brands
        finally:
            db.close()


def _resolve_brand(brand: str) -> str:
    """Snap a user-typed brand to the closest known brand (typo correction).
    Exact case-insensitive match is tried first — fuzzy only runs when no exact
    match exists (i.e. genuine typo or unseeded brand). Score cutoff 80 safely
    catches 1-2 char edits while blocking correctly-spelled brands we don't carry."""
    known = _get_known_brands()
    if not known:
        return brand
    brand_lower = brand.lower()
    for k in known:
        if k.lower() == brand_lower:
            return k
    result = process.extractOne(brand, known, scorer=fuzz.WRatio, score_cutoff=80)
    return result[0] if result else brand


def search_products(
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    product_type: Optional[str] = None,
    brand: Optional[str] = None,
    max_price: Optional[int] = None,
    min_price: Optional[int] = None,
    min_rating: Optional[float] = None,
    keywords: Optional[List[str]] = None,
    limit: int = 20,
) -> List[dict]:
    """
    Search products with flexible filtering.

    Args:
        category: Product category (e.g., "Toys & Games", "Sports & Outdoors")
        subcategory: Product subcategory (e.g., "Learning & Education")
        product_type: Product type (e.g., "smartphone", "laptop")
        brand: Brand name
        max_price: Maximum price in paise/cents
        min_price: Minimum price in paise/cents
        min_rating: Minimum product rating (e.g. 4.0 for "best rated")
        keywords: List of keywords to search in name/description/attributes
        limit: Maximum results to return
    """
    # Subcategories that exist in the DB but are never served — block them from all results,
    # including relaxed searches. Prevents "iphone" / "redmi charger" from surfacing phones.
    EXCLUDED_SUBCATEGORIES = {"smartphone", "laptop", "tablet"}

    db = SessionLocal()
    try:
        query = db.query(Product).filter(~Product.subcategory.in_(EXCLUDED_SUBCATEGORIES))

        # Filter by category
        if category:
            query = query.filter(Product.category.ilike(f"%{category}%"))

        # Catalog imports use both `subcategory` and `type` for canonical product
        # labels. Match either field so a request like "headphones" remains
        # focused on headphones instead of triggering a broad fallback search.
        if subcategory:
            query = query.filter(
                or_(
                    Product.subcategory.ilike(subcategory),
                    Product.type.ilike(subcategory),
                )
            )
        # Filter by type (product-level classifier)
        if product_type:
            query = query.filter(Product.type.ilike(f"%{product_type}%"))
        # Filter by brand
        # Filter by brand — fuzzy-correct typos, then use first meaningful word
        if brand:
            resolved = _resolve_brand(brand)
            if resolved != brand:
                logger.info(f"request_id={get_request_id()} | brand_fuzzy | {brand!r} → {resolved!r}")
            brand_words = [w for w in resolved.replace("&", "").split() if len(w) > 3]
            search_brand = brand_words[0] if brand_words else resolved
            query = query.filter(Product.brand.ilike(f"%{search_brand}%"))

        # Filter by price range
        if max_price is not None:
            query = query.filter(Product.price <= max_price)
        if min_price is not None:
            query = query.filter(Product.price >= min_price)
        if min_rating is not None:
            query = query.filter(Product.rating >= min_rating)

        # Keyword search in name, brand, and tags
        if keywords:
            for keyword in keywords:
                keyword_filter = or_(
                    Product.name.ilike(f"%{keyword}%"),
                    Product.brand.ilike(f"%{keyword}%"),
                    cast(Product.tags, String).ilike(f"%{keyword}%"),
                )
                query = query.filter(keyword_filter)

        # Best-rated first, so the ranker sees the strongest candidates and runs are repeatable
        products = query.order_by(Product.rating.desc().nulls_last(), Product.product_id).limit(limit).all()

        # Convert to dict format
        results = []
        for p in products:
            results.append(
                {
                    "product_id": p.product_id,
                    "name": p.name,
                    "category": p.category,
                    "subcategory": p.subcategory,
                    "type": p.type,
                    "brand": p.brand,
                    "price": p.price,
                    "rating": float(p.rating) if p.rating else None,
                    "description": p.description,
                    "attributes": p.attributes,
                }
            )

        return results

    finally:
        db.close()

