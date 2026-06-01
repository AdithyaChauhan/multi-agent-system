from typing import Optional, List
from sqlalchemy import or_, cast, String
from app.db.database import SessionLocal
from app.models.product import Product
from app.core.logger import get_logger, get_request_id

logger = get_logger("app.tools.product_tools")


def search_products(
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    product_type: Optional[str] = None,
    brand: Optional[str] = None,
    max_price: Optional[int] = None,
    min_price: Optional[int] = None,
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

        # Filter by subcategory
        if subcategory:
            query = query.filter(Product.subcategory.ilike(f"%{subcategory}%"))
        # Filter by type (product-level classifier)
        if product_type:
            query = query.filter(Product.type.ilike(f"%{product_type}%"))
        # Filter by brand
        # Filter by brand — use first meaningful word to handle truncated brand names
        if brand:
            brand_words = [w for w in brand.replace("&", "").split() if len(w) > 3]
            search_brand = brand_words[0] if brand_words else brand
            query = query.filter(Product.brand.ilike(f"%{search_brand}%"))

        # Filter by price range
        if max_price is not None:
            query = query.filter(Product.price <= max_price)
        if min_price is not None:
            query = query.filter(Product.price >= min_price)

        # Keyword search in name, brand, and tags
        if keywords:
            for keyword in keywords:
                keyword_filter = or_(
                    Product.name.ilike(f"%{keyword}%"),
                    Product.brand.ilike(f"%{keyword}%"),
                    cast(Product.tags, String).ilike(f"%{keyword}%"),
                )
                query = query.filter(keyword_filter)

        # Execute query
        products = query.limit(limit).all()

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


def get_product_by_id(product_id: str) -> Optional[dict]:
    """
    Fetch one product by product_id.
    Returns the product as a dict or None if not found.
    """
    db = SessionLocal()

    try:
        product = db.query(Product).filter(Product.product_id == product_id).first()

        if not product:
            logger.info(f"request_id={get_request_id()} | " f"Product not found | product_id={product_id}")
            return None

        logger.info(f"request_id={get_request_id()} | " f"Product fetched | product_id={product_id}")
        return _product_to_dict(product)

    finally:
        db.close()


def get_all_categories() -> dict:
    """
    Returns available product types and their filterable attributes.
    Used when the user is vague — agent knows what to ask for.
    """
    return {
        "clothes": {
            "filterable_attributes": ["gender", "section", "size"],
            "gender_options": ["male", "female", "unisex"],
            "section_options": ["top", "bottom"],
            "size_options": ["S", "M", "L", "XL", "XXL"],
        },
        "laptop": {
            "filterable_attributes": ["storage_gb", "ram_gb"],
            "storage_options": [256, 512, 1024],
            "ram_options": [8, 16, 32],
        },
        "headphones": {
            "filterable_attributes": ["form_factor", "wireless"],
            "form_factor_options": ["over-ear", "earbuds", "in-ear"],
            "wireless_options": [True, False],
        },
    }


def fetch_reviews(product_id: str) -> list[dict]:
    """
    Fetch all reviews for a given product_id.
    Returns list of review dicts.
    """
    from app.models.review import Review

    db = SessionLocal()

    try:
        reviews = db.query(Review).filter(Review.product_id == product_id).all()

        logger.info(
            f"request_id={get_request_id()} | " f"Reviews fetched | product_id={product_id} | count={len(reviews)}"
        )

        return [
            {
                "review_id": r.review_id,
                "product_id": r.product_id,
                "rating": r.rating,
                "review_text": r.review_text,
                "reviewer": r.reviewer,
            }
            for r in reviews
        ]

    finally:
        db.close()


def fetch_specs(product_id: str) -> list[dict]:
    """
    Fetch all specs for a given product_id.
    Returns list of spec dicts.
    """
    from app.models.spec import Spec

    db = SessionLocal()

    try:
        specs = db.query(Spec).filter(Spec.product_id == product_id).all()

        logger.info(f"request_id={get_request_id()} | " f"Specs fetched | product_id={product_id} | count={len(specs)}")

        return [
            {
                "spec_id": s.spec_id,
                "product_id": s.product_id,
                "spec_key": s.spec_key,
                "spec_value": s.spec_value,
            }
            for s in specs
        ]

    finally:
        db.close()


def _product_to_dict(product: Product) -> dict:
    """Internal helper — converts SQLAlchemy Product object to plain dict."""
    return {
        "product_id": product.product_id,
        "name": product.name,
        "type": product.type,
        "brand": product.brand,
        "price": product.price,
        "description": product.description,
        "in_stock": product.in_stock,
        "rating": product.rating,
        "attributes": product.attributes,
    }
