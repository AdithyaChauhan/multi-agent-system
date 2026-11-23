"""Hybrid product search (ADR 0006, 0014): three ranked candidate lists, fused by reciprocal rank.

- vector: cosine similarity between the query and each product's embedding (pgvector);
- text: Postgres full text over title, name and brand, matching any of the query's words;
- type: products of the type the shopper's word resolved to, best-rated first.

The model's type is one vote, not a gate, so a renamed or mis-picked type can't hide the right
products. Hard constraints (served types, brand, price, rating, keywords) are WHERE clauses on every
list. Attribute filters come from one type's schema, so they apply to products of that type only.
"""

from functools import lru_cache
from typing import List, Optional

from sqlalchemy import text

from app.catalog.features import attributes_match
from app.catalog.runtime import get_catalog
from app.core.config import EMBEDDING_MODEL, HYBRID_RRF_K, HYBRID_WEIGHTS
from app.core.logger import get_logger
from app.db.database import SessionLocal, engine
from app.search.embeddings import embed_query, to_pgvector

logger = get_logger("app.search.hybrid")

CANDIDATES = 50  # per list
_ready = False


def rrf(lists: dict, weights: dict, k: int) -> list:
    """Weighted reciprocal rank fusion: score(p) = sum over lists of weight / (k + rank of p).
    Ties break on the id, so results are repeatable."""
    scores: dict = {}
    for name, ids in lists.items():
        weight = weights.get(name, 1.0)
        for rank, pid in enumerate(ids, 1):
            scores[pid] = scores.get(pid, 0.0) + weight / (k + rank)
    return sorted(scores, key=lambda pid: (-scores[pid], pid))


def hybrid_available() -> bool:
    """Postgres with this model's embeddings loaded. Checked until true, then remembered."""
    global _ready
    if _ready:
        return True
    if engine.dialect.name != "postgresql":
        return False
    db = SessionLocal()
    try:
        _ready = bool(
            db.execute(text("SELECT products FROM embedding_meta WHERE model = :m"), {"m": EMBEDDING_MODEL}).scalar()
        )
    except Exception as exc:  # not migrated yet
        logger.warning(f"hybrid search unavailable: {type(exc).__name__}")
        db.rollback()
    finally:
        db.close()
    return _ready


@lru_cache(maxsize=512)
def _query_vector(query: str) -> str:
    return to_pgvector(embed_query(query))


def _where(brand_id, max_price, min_price, min_rating, keywords) -> tuple:
    clauses, params = ["t.served"], {}
    if brand_id is not None:
        clauses.append("p.brand_id = :brand_id")
        params["brand_id"] = brand_id
    if max_price is not None:
        clauses.append("p.price <= :max_price")
        params["max_price"] = max_price
    if min_price is not None:
        clauses.append("p.price >= :min_price")
        params["min_price"] = min_price
    if min_rating is not None:
        clauses.append("p.rating >= :min_rating")
        params["min_rating"] = min_rating
    for i, keyword in enumerate(keywords or []):
        clauses.append(f"(p.name ILIKE :kw{i} OR p.title ILIKE :kw{i})")
        params[f"kw{i}"] = f"%{keyword}%"
    return " AND ".join(clauses), params


FROM = "FROM products p JOIN product_types t ON t.id = p.type_id"


def hybrid_search(
    query: str = "",
    product_type: Optional[str] = None,
    attributes: Optional[dict] = None,
    brand: Optional[str] = None,
    max_price: Optional[int] = None,
    min_price: Optional[int] = None,
    min_rating: Optional[float] = None,
    keywords: Optional[List[str]] = None,
    limit: int = 20,
) -> List[dict]:
    """Same arguments and result shape as product_tools.search_products, plus the query text."""
    from app.tools.product_tools import product_dict

    brand_id = None
    if brand:
        resolved = get_catalog().resolve_brand(brand)
        if resolved is None:
            return []  # a brand we don't carry: nothing matches
        brand_id = resolved[0]
    where, params = _where(brand_id, max_price, min_price, min_rating, keywords)
    lists: dict = {}
    db = SessionLocal()
    try:
        db.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))  # filters can't starve the index
        if query.strip():
            vec = {**params, "qvec": _query_vector(query.strip()), "n": CANDIDATES}
            lists["vector"] = (
                db.execute(
                    text(
                        f"SELECT p.id {FROM} WHERE {where} AND p.embedding IS NOT NULL "
                        "ORDER BY p.embedding <=> CAST(:qvec AS vector), p.id LIMIT :n"
                    ),
                    vec,
                )
                .scalars()
                .all()
            )
            lists["text"] = (
                db.execute(
                    text(
                        "WITH q AS (SELECT NULLIF(replace(plainto_tsquery('english', :q)::text, ' & ', ' | '), '')"
                        f"::tsquery AS tq) SELECT p.id FROM q CROSS JOIN products p JOIN product_types t "
                        f"ON t.id = p.type_id WHERE {where} AND p.search_tsv @@ q.tq "
                        "ORDER BY ts_rank_cd(p.search_tsv, q.tq) DESC, p.rating DESC NULLS LAST, p.id LIMIT :n"
                    ),
                    {**params, "q": query, "n": CANDIDATES},
                )
                .scalars()
                .all()
            )
        if product_type:
            rows = db.execute(
                text(
                    f"SELECT p.id, p.attributes {FROM} WHERE {where} AND t.name = :ptype "
                    "ORDER BY p.rating DESC NULLS LAST, p.product_id"
                ),
                {**params, "ptype": product_type},
            ).all()
            lists["type"] = [pid for pid, attrs in rows if not attributes or attributes_match(attrs, attributes)][
                :CANDIDATES
            ]
        order = rrf(lists, HYBRID_WEIGHTS, HYBRID_RRF_K)
        if not order:
            return []
        rows = db.execute(
            text(
                "SELECT p.id, t.name AS type_name, b.name AS brand_name FROM products p "
                "JOIN product_types t ON t.id = p.type_id LEFT JOIN brands b ON b.id = p.brand_id "
                "WHERE p.id = ANY(:ids)"
            ),
            {"ids": list(order)},
        ).all()
        names = {pid: (type_name, brand_name) for pid, type_name, brand_name in rows}
        from app.models.product import Product

        products = {p.id: p for p in db.query(Product).filter(Product.id.in_(list(order))).all()}
        results = []
        for pid in order:
            p = products.get(pid)
            type_name, brand_name = names.get(pid, (None, None))
            if p is None:
                continue
            # Attribute filters belong to the requested type's schema: other types can't be checked.
            if attributes and type_name == product_type and not attributes_match(p.attributes, attributes):
                continue
            results.append(product_dict(p, type_name, brand_name))
            if len(results) >= limit:
                break
        return results
    finally:
        db.rollback()
        db.close()


def catalog_match(phrase: str) -> Optional[dict]:
    """The served product closest in meaning to the phrase: what the catalog would call it (its kind,
    else its type) and the cosine similarity. Used before telling a shopper "we don't carry X"."""
    if not phrase or not phrase.strip() or not hybrid_available():
        return None
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                f"SELECT t.name, p.attributes ->> 'kind', 1 - (p.embedding <=> CAST(:qvec AS vector)) {FROM} "
                "WHERE t.served AND p.embedding IS NOT NULL ORDER BY p.embedding <=> CAST(:qvec AS vector) LIMIT 1"
            ),
            {"qvec": _query_vector(phrase.strip())},
        ).first()
    finally:
        db.close()
    if row is None:
        return None
    type_name, kind, similarity = row
    word = kind if kind and kind != "other" else type_name
    return {"type": type_name, "word": word, "similarity": round(float(similarity), 4)}
