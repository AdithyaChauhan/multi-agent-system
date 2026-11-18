import copy
import json
from functools import lru_cache
from typing import List, Literal, Optional

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field, field_validator

from app.agents.state import AgentState
from app.tools.product_tools import search_products
from app.core.llm import call_llm
from app.core.logger import get_logger, get_request_id
from app.core.prompt_loader import load_prompt

logger = get_logger("app.agents.product_agent")


SERVED_CATEGORIES = ("Computers & Accessories", "Electronics", "Home & Kitchen", "Office Products")

# Product kinds that have rows in the DB but are not sold. Exact catalog scope: never offered.
NOT_SERVED = frozenset(
    {"smartphone", "laptop", "tablet", "clothing", "shoes", "furniture", "book", "toy", "sports equipment"}
)

# The only `type` values that refine a subcategory in the catalog (headphones, speakers).
PRODUCT_TYPES = (
    "neckband",
    "tws earbuds",
    "wired earphones",
    "over-ear headphones",
    "bluetooth speaker",
    "soundbar",
    "home theatre",
)


def _is_served(subcategory: str) -> bool:
    return subcategory.lower().rstrip("s") not in NOT_SERVED and subcategory.lower() not in NOT_SERVED


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    """{category: [subcategory, ...]} for what we sell, read once from the products table."""
    from app.db.database import SessionLocal
    from app.models.product import Product

    db = SessionLocal()
    try:
        rows = (
            db.query(Product.category, Product.subcategory)
            .filter(Product.category.in_(SERVED_CATEGORIES), Product.subcategory.isnot(None))
            .distinct()
            .all()
        )
    except Exception:  # pragma: no cover - DB not reachable at import time
        return {}
    finally:
        db.close()
    catalog: dict = {}
    for category, subcategory in rows:
        if _is_served(subcategory):
            catalog.setdefault(category, []).append(subcategory)
    return {c: sorted(s) for c, s in sorted(catalog.items())}


def build_catalog_blurb() -> str:
    """Short catalog summary shown when the shopper hasn't said what they want."""
    from app.db.database import SessionLocal
    from app.models.product import Product
    from sqlalchemy import func

    db = SessionLocal()
    try:
        rows = (
            db.query(Product.category, Product.subcategory, func.count(Product.product_id))
            .filter(Product.category.in_(SERVED_CATEGORIES), Product.subcategory.isnot(None))
            .group_by(Product.category, Product.subcategory)
            .order_by(Product.category, func.count(Product.product_id).desc())
            .all()
        )
    except Exception:  # pragma: no cover
        return ""
    finally:
        db.close()
    totals: dict = {}
    examples: dict = {}
    for category, subcategory, count in rows:
        totals[category] = totals.get(category, 0) + count
        if _is_served(subcategory) and len(examples.setdefault(category, [])) < 3:
            examples[category].append(subcategory)
    ordered = sorted(totals, key=totals.get, reverse=True)
    return "\n".join(f"• {c} ({totals[c]} products) — {', '.join(examples.get(c, []))}" for c in ordered)


CATALOG_BLURB = build_catalog_blurb()


def _subcategories() -> tuple:
    return tuple(sorted({s for subs in load_catalog().values() for s in subs}))


@lru_cache(maxsize=1)
def search_schema():
    """Pydantic schema for the extraction call.

    Subcategory values come from the DB catalog. The model sees them in the prompt rather than as a
    JSON-schema enum, because Groq rejects a whole tool call (HTTP 400) when one value is off-list;
    the validator below enforces the catalog instead and turns unknown values into null.
    """
    subs = _subcategories()
    allowed = {
        "category": SERVED_CATEGORIES,
        "subcategory": subs,
        "suggestion": subs,
        "type": PRODUCT_TYPES,
    }

    class ProductSearch(BaseModel):
        """Catalog search filters for what the shopper wants now."""

        category: Optional[Literal[SERVED_CATEGORIES]] = Field(None, description="catalog category")
        subcategory: Optional[str] = Field(None, description="one of the catalog subcategories, or null")
        type: Optional[Literal[PRODUCT_TYPES]] = Field(None, description="only for headphones and speakers")
        brand: Optional[str] = None
        max_price: Optional[int] = Field(None, description="rupees")
        min_price: Optional[int] = Field(None, description="rupees")
        min_rating: Optional[float] = Field(None, description="out of 5")
        keywords: List[str] = Field(default_factory=list, description="features not covered by other fields")
        not_carried: Optional[str] = Field(None, description="what they asked for, if we don't sell that at all")
        suggestion: Optional[str] = Field(None, description="with not_carried: closest subcategory we sell")

        @field_validator("category", "subcategory", "suggestion", "type", mode="before")
        @classmethod
        def _known_value_or_none(cls, value, info):
            if not isinstance(value, str):
                return None
            options = allowed[info.field_name]
            if not options:  # catalog unavailable: accept the model's value as written
                return value.strip() or None
            word = value.strip().lower()
            forms = {
                word,
                word + "s",
                word[:-1] if word.endswith("s") else word,
                word[:-2] if word.endswith("es") else word,
            }
            return next((a for a in options if a.lower() in forms), None)  # "TVs" → "tv"

        @field_validator("keywords", mode="before")
        @classmethod
        def _list(cls, value):
            return [k for k in value if isinstance(k, str) and k.strip()] if isinstance(value, list) else []

    return ProductSearch


def catalog_lines() -> str:
    return "\n".join(f"{c}: {' | '.join(subs)}" for c, subs in load_catalog().items())


def _category_of(subcategory: Optional[str], given: Optional[str]) -> Optional[str]:
    """The catalog decides which category a subcategory belongs to; the model can't get it wrong."""
    if not subcategory:
        return given
    owners = [c for c, subs in load_catalog().items() if subcategory in subs]
    return given if given in owners else (owners[0] if owners else given)


EMPTY_PREFERENCES = {
    "category": None,
    "subcategory": None,
    "type": None,
    "brand": None,
    "max_price": None,
    "min_price": None,
    "min_rating": None,
    "keywords": [],
}


def extract_preferences(state: AgentState) -> dict:
    """LLM node: previous filters + new message → complete filters for what the shopper wants now."""
    previous = {k: v for k, v in (state.get("preferences") or {}).items() if k in EMPTY_PREFERENCES and v}
    message = state.get("user_message", "")
    parsed = call_llm(
        "product",
        "extract_preferences",
        [
            SystemMessage(content=load_prompt("product_extraction", catalog=catalog_lines())),
            HumanMessage(content=f"Previous: {json.dumps(previous)} | Message: {message}"),
        ],
        schema=search_schema(),
    )
    out = parsed.model_dump() if parsed is not None else {}
    preferences = {k: out.get(k, v) for k, v in EMPTY_PREFERENCES.items()}
    preferences["keywords"] = out.get("keywords") or []
    preferences["category"] = _category_of(preferences["subcategory"], preferences["category"])
    not_carried = out.get("not_carried")
    logger.info(f"request_id={get_request_id()} | EXTRACTED: {json.dumps(preferences)} | not_carried={not_carried!r}")
    return {
        "preferences": preferences,
        "original_preferences": copy.deepcopy(preferences),
        "not_carried": {"item": not_carried, "suggestion": out.get("suggestion")} if not_carried else None,
        "relaxed_filters": [],
    }


def ask_for_preferences(state: AgentState) -> dict:
    logger.info(f"request_id={get_request_id()} | Asking for preferences")
    return {"final_response": f"What are you looking for? Here's what we carry:\n\n{CATALOG_BLURB}"}


def respond_unavailable(state: AgentState) -> dict:
    """Deterministic reply for a kind of product we don't sell."""
    info = state.get("not_carried") or {}
    item = info.get("item") or "that"
    suggestion = info.get("suggestion")
    reply = f"Sorry, we don't carry {item}."
    if suggestion:
        reply += f" Would you like to see our {suggestion} range instead?"
    else:
        reply += f" Here's what we do carry:\n\n{CATALOG_BLURB}"
    return {"final_response": reply}


def route_after_extraction(state: AgentState) -> Literal["search", "ask", "unavailable"]:
    if state.get("not_carried"):
        return "unavailable"
    prefs = state.get("preferences") or {}
    has_signal = any(prefs.get(k) for k in ("category", "subcategory", "type", "keywords", "brand"))
    return "search" if has_signal else "ask"


# Optional filters, dropped one at a time (cumulatively) when a search finds nothing.
# Subcategory and category are never dropped: showing a different kind of product is not a match.
RELAXATION_ORDER = ["type", "price", "brand", "keywords"]


def _run_search(filters: dict, limit: int = 10) -> list:
    return search_products(
        category=filters.get("category"),
        subcategory=filters.get("subcategory"),
        product_type=filters.get("type"),
        brand=filters.get("brand"),
        max_price=filters.get("max_price"),
        min_price=filters.get("min_price"),
        min_rating=filters.get("min_rating"),
        keywords=filters.get("keywords") or [],
        limit=limit,
    )


def find_products(state: AgentState) -> dict:
    """Deterministic search with one fallback loop: relax optional filters until something matches.

    Works on a copy, so the shopper's own preferences (kept for the next turn) are never relaxed.
    """
    filters = dict(state.get("preferences") or {})
    relaxed: list = []
    results = _run_search(filters)
    for name in RELAXATION_ORDER:
        if results:
            break
        if name == "price" and filters.get("max_price"):
            filters["max_price"] = int(filters["max_price"] * 1.25)
            relaxed.append("price")
        elif name != "price" and filters.get(name):
            filters[name] = [] if name == "keywords" else None
            relaxed.append(name)
        else:
            continue
        results = _run_search(filters)
    logger.info(f"request_id={get_request_id()} | search | found={len(results)} | relaxed={relaxed}")
    return {"search_results": results, "relaxed_filters": relaxed}


class Ranking(BaseModel):
    """1-based indices of the listed products."""

    same_kind: List[int] = Field(default_factory=list, description="the kind of product asked for, any brand/spec")
    exact: List[int] = Field(default_factory=list, description="of those, also matching brand, features and specs")


def rank_products(state: AgentState) -> dict:
    """LLM node: drop candidates that aren't what the shopper asked for, then order the rest."""
    candidates = (state.get("search_results") or [])[:10]
    if not candidates:
        return {"ranked_products": []}
    listing = "\n".join(
        f"{i}. {p['name'][:60]} | ₹{p['price']} | {p['rating']}★ | {p.get('brand') or 'N/A'}"
        for i, p in enumerate(candidates, 1)
    )
    ranking = call_llm(
        "product",
        "rank_products",
        [
            SystemMessage(content=load_prompt("product_ranking")),
            HumanMessage(content=f'User request: "{state.get("user_message", "")}"\n\nProducts:\n{listing}'),
        ],
        schema=Ranking,
    )
    if ranking is None:  # no usable answer: keep the search order, flagged as inexact
        ranking = Ranking(same_kind=list(range(1, min(5, len(candidates)) + 1)))

    prefs = state.get("preferences") or {}
    exact = [i for i in ranking.exact if i in ranking.same_kind or not ranking.same_kind]
    picked, seen = [], set()
    for tier, indices in ((0, exact), (1, ranking.same_kind)):
        for i in indices:
            if 1 <= i <= len(candidates) and i not in seen:
                seen.add(i)
                picked.append({**candidates[i - 1], "llm_tier": tier, "score": score(candidates[i - 1], prefs)})
    picked.sort(key=lambda p: (p["llm_tier"], -p["score"]))
    return {"ranked_products": picked[:5]}


def score(product: dict, prefs: dict) -> float:
    """Three factors: rating, how well the price uses the budget, and match on brand/type/keywords."""
    rating = (product.get("rating") or 0) / 5
    budget = prefs.get("max_price")
    if budget:
        ratio = (product.get("price") or 0) / budget
        price_fit = 0.0 if ratio > 1 else (1.0 if ratio >= 0.5 else 0.5)
    else:
        price_fit = 0.5
    text = f"{product.get('name', '')} {product.get('brand', '')} {product.get('type', '')}".lower()
    wanted = [w.lower() for w in [prefs.get("brand"), prefs.get("type"), *(prefs.get("keywords") or [])] if w]
    match = sum(w in text for w in wanted) / len(wanted) if wanted else 0.5
    return round(0.5 * rating + 0.25 * price_fit + 0.25 * match, 3)


def route_after_rank(state: AgentState) -> Literal["recommend", "no_results"]:
    return "recommend" if state.get("ranked_products") else "no_results"


def _label(prefs: dict) -> str:
    return prefs.get("subcategory") or (prefs.get("keywords") or [None])[0] or prefs.get("category") or "products"


def _brand_note(prefs: dict, shown: list) -> str:
    """Say plainly when the brand asked for isn't in the results."""
    brand = prefs.get("brand")
    if not brand or any(brand.lower() in (p.get("brand") or "").lower() for p in shown):
        return ""
    label = _label(prefs)
    if search_products(brand=brand, subcategory=prefs.get("subcategory"), limit=1):
        return (
            f"I couldn't find {brand} {label} within your filters, so here are the closest options from other brands:\n"
        )
    return f"We don't carry {brand} {label}, so here are the closest options from other brands:\n"


RELAXED_WORDS = {
    "type": "the type",
    "price": "the price limit (+25%)",
    "brand": "the brand",
    "keywords": "some features",
}


def format_recommendations(state: AgentState) -> dict:
    prefs = state.get("preferences") or {}
    top3 = (state.get("ranked_products") or [])[:3]
    relaxed = state.get("relaxed_filters") or []
    header = _brand_note(prefs, top3)
    if not header and relaxed:
        header = f"I couldn't find an exact match, so I widened {', '.join(RELAXED_WORDS[r] for r in relaxed)}:\n"
    if not header and all(p["llm_tier"] == 1 for p in top3):
        header = "These don't match everything you asked for, but they're the closest options we have:\n"
    lines = [header or "Here are my top recommendations for you:\n"]
    for i, p in enumerate(top3, 1):
        rating = f"{p['rating']:.1f}/5" if p.get("rating") is not None else "Not rated"
        lines.append(f"{i}. **{p['name']}** — {p.get('brand') or 'Unknown brand'}")
        lines.append(f"   ₹{p['price']:,} · {rating}")
        lines.append("")
    return {"final_response": "\n".join(lines)}


def respond_no_results(state: AgentState) -> dict:
    prefs = state.get("preferences") or {}
    label = _label(prefs)
    reply = f"I couldn't find any {label} matching your request."
    brand = prefs.get("brand")
    if brand and not search_products(brand=brand, subcategory=prefs.get("subcategory"), limit=1):
        reply = f"We don't carry {brand} {label}. " + reply
    return {"final_response": reply + " Try a different budget, brand or product."}


def build_product_agent_graph():
    graph = StateGraph(AgentState)
    graph.add_node("extract_preferences", extract_preferences)
    graph.add_node("ask_for_preferences", ask_for_preferences)
    graph.add_node("respond_unavailable", respond_unavailable)
    graph.add_node("find_products", find_products)
    graph.add_node("rank_products", rank_products)
    graph.add_node("format_recommendations", format_recommendations)
    graph.add_node("respond_no_results", respond_no_results)

    graph.set_entry_point("extract_preferences")
    graph.add_conditional_edges(
        "extract_preferences",
        route_after_extraction,
        {"search": "find_products", "ask": "ask_for_preferences", "unavailable": "respond_unavailable"},
    )
    graph.add_edge("find_products", "rank_products")
    graph.add_conditional_edges(
        "rank_products", route_after_rank, {"recommend": "format_recommendations", "no_results": "respond_no_results"}
    )
    for node in ("ask_for_preferences", "respond_unavailable", "format_recommendations", "respond_no_results"):
        graph.add_edge(node, END)
    return graph.compile()


product_agent_graph = build_product_agent_graph()
