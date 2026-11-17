import json
import copy
import re
from functools import lru_cache
from typing import List, Literal, Optional

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field, field_validator

from app.agents.state import AgentState
from app.agents.product_agent_subgraph import product_enrichment_subgraph
from app.tools.product_tools import search_products, _get_known_brands
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
    """Pydantic schema for the extraction call. Enums come from the DB catalog."""
    subs = _subcategories()
    SubLiteral = Literal[subs] if subs else str
    allowed = {
        "category": SERVED_CATEGORIES,
        "subcategory": subs,
        "suggestion": subs,
        "type": PRODUCT_TYPES,
    }

    class ProductSearch(BaseModel):
        """Catalog search filters for what the shopper wants now."""

        category: Optional[Literal[SERVED_CATEGORIES]] = Field(None, description="catalog category")
        subcategory: Optional[SubLiteral] = Field(None, description="catalog subcategory, null if none fits")
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
            wanted = value.strip().lower()
            return next((a for a in options if a.lower() == wanted), None)

        @field_validator("keywords", mode="before")
        @classmethod
        def _list(cls, value):
            return [k for k in value if isinstance(k, str) and k.strip()] if isinstance(value, list) else []

    return ProductSearch


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
            SystemMessage(content=load_prompt("product_extraction")),
            HumanMessage(content=f"Previous: {json.dumps(previous)} | Message: {message}"),
        ],
        schema=search_schema(),
    )
    out = parsed.model_dump() if parsed is not None else {}
    preferences = {k: out.get(k, v) for k, v in EMPTY_PREFERENCES.items()}
    preferences["keywords"] = out.get("keywords") or []
    preferences["category"] = _category_of(preferences["subcategory"], preferences["category"])
    not_carried = out.get("not_carried")
    logger.info(
        f"request_id={get_request_id()} | EXTRACTED: {json.dumps(preferences)} | not_carried={not_carried!r}"
    )
    return {
        "preferences": preferences,
        "original_preferences": copy.deepcopy(preferences),
        "not_carried": {"item": not_carried, "suggestion": out.get("suggestion")} if not_carried else None,
        "broaden_attempt": 0,
        "relaxed_filters": [],
        "filters_exhausted": False,
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


# Order in which optional filters are dropped when a search finds nothing.
RELAXATION_ORDER = [
    "type",
    "price_increase",
    "brand",
    "keywords",
]


# ── Product search ───────────────────────────────────────────────────────────


def do_search_products(state: AgentState) -> dict:
    """Deterministic node — reads preferences from state and calls search_products directly."""
    prefs = state.get("preferences") or {}
    logger.info(
        f"request_id={get_request_id()} | Searching | category={prefs.get('category')} | subcategory={prefs.get('subcategory')}"
    )
    results = search_products(
        category=prefs.get("category"),
        subcategory=prefs.get("subcategory"),
        product_type=prefs.get("type"),
        brand=prefs.get("brand"),
        max_price=prefs.get("max_price"),
        min_price=prefs.get("min_price"),
        min_rating=prefs.get("min_rating"),
        keywords=prefs.get("keywords") or [],
        limit=10,
    )
    logger.info(f"request_id={get_request_id()} | Found {len(results)} products")
    return {"search_results": results}


def broaden_search(state: AgentState) -> dict:
    prefs = (state.get("preferences") or {}).copy()
    attempt = state.get("broaden_attempt", 0)
    relaxed = list(state.get("relaxed_filters") or [])

    # Walk forward through the relaxation order until we find a filter we can actually relax.
    # Using a loop instead of recursion so each graph invocation does one unit of work
    # and the graph edge (broaden → search_products) handles the retry — traceable in LangSmith.
    while attempt < len(RELAXATION_ORDER):
        filter_to_relax = RELAXATION_ORDER[attempt]
        attempt += 1

        if filter_to_relax == "price_increase":
            if prefs.get("max_price"):
                old_price = prefs["max_price"]
                prefs["max_price"] = int(old_price * 1.25)
                relaxed.append(f"price increased from {old_price} to {prefs['max_price']}")
                break
        else:
            if prefs.get(filter_to_relax):
                relaxed.append(filter_to_relax)
                prefs[filter_to_relax] = None
                break
    else:
        return {"broaden_attempt": attempt, "filters_exhausted": True}

    # Category alone is enough to fetch a candidate set for the ranker.
    has_specificity = (
        prefs.get("category")
        or prefs.get("subcategory")
        or prefs.get("brand")
        or prefs.get("type")
        or prefs.get("keywords")
    )
    if not has_specificity:
        return {"broaden_attempt": attempt, "filters_exhausted": True}

    return {
        "preferences": prefs,
        "broaden_attempt": attempt,
        "relaxed_filters": relaxed,
        "filters_exhausted": False,
    }


def respond_no_results(state: AgentState) -> dict:
    logger.info(f"request_id={get_request_id()} | No results after exhausting filters")
    original = state.get("original_preferences") or {}
    brand = original.get("brand")
    # Restore context from original so follow-up messages (e.g. "under 2000") keep subcategory.
    # Relaxation strips preferences to null by the time this node fires; without restoration
    # the next turn has no category/subcategory context and returns unrelated products.
    _restored = {**original, "brand": None}

    if brand:
        subcategory = original.get("subcategory")
        category = original.get("category")
        # Distinguish a brand we stock (filters just too narrow) from one we genuinely don't carry.
        known_brands = _get_known_brands()
        brand_in_catalog = any(k.lower() == brand.lower() for k in known_brands)
        if brand_in_catalog:
            # Check if this brand makes the requested product at all (ignoring filters).
            brand_has_product = bool(search_products(brand=brand, subcategory=subcategory, limit=1))
            if brand_has_product:
                # Brand makes the product but price/rating filters were too tight.
                # Clear the constraints we're telling the user to relax — the next turn's
                # price ("under 3000") should not be intersected with the old tight filters.
                label = subcategory or category or "products"
                return {
                    "final_response": (
                        f"I couldn't find any {brand} {label} matching your filters. "
                        f"Try relaxing the price or rating — or let me know if you'd like to see other brands."
                    ),
                    "preferences": {**original, "max_price": None, "min_price": None, "min_rating": None},
                }
            # Brand is in our catalog but doesn't make this product — show alternatives.
            no_carry_msg = f"We carry {brand} but not {subcategory or category or 'that product'}."
        else:
            no_carry_msg = f"We don't carry {brand}."
        alternatives = search_products(category=category, subcategory=subcategory, limit=10)
        if alternatives:
            top3 = sorted(alternatives, key=lambda p: p.get("rating") or 0, reverse=True)[:3]
            label = subcategory or category or "products"
            lines = [f"{no_carry_msg} Here are our top-rated {label} from brands we stock:\n"]
            for i, p in enumerate(top3, 1):
                price = f"₹{p['price']:,}" if p.get("price") else ""
                rating = f"{p['rating']}/5" if p.get("rating") else ""
                lines.append(f"{i}. **{p['name']}** by {p.get('brand', '')}")
                lines.append(f"   {price} | ⭐ {rating}\n")
            return {"final_response": "\n".join(lines), "preferences": _restored}
        return {
            "final_response": f"{no_carry_msg} Let me know what you need and I can suggest alternatives from brands we stock.",
            "preferences": _restored,
        }

    return {
        "final_response": (
            "I couldn't find any products matching your requirements, "
            "even after relaxing several filters. Try a different category or higher budget."
        ),
        "preferences": _restored,
    }


def format_recommendations(state: AgentState) -> dict:
    ranked = state.get("ranked_products") or []
    relaxed = state.get("relaxed_filters") or []

    if not ranked:
        return {"final_response": "I found some products but could not rank them."}

    top3 = ranked[:3]
    all_maybe = all(p.get("llm_tier", 0) == 1 for p in top3) or bool(state.get("keyword_recovery_attempted"))

    lines = []
    if relaxed and not state.get("keyword_recovery_attempted"):
        lines.append("I found close matches after broadening a few optional filters:\n")
    elif all_maybe:
        lines.append(
            "I couldn't find products that exactly match your request, but here are some related options — let me know if any of these work for you or if you'd like me to look for something else:\n"
        )
    else:
        lines.append("Here are my top recommendations for you:\n")

    for i, p in enumerate(top3, 1):
        brand = p.get("brand") or "Unknown brand"
        rating = f"{p['rating']:.1f}/5" if p.get("rating") is not None else "Not rated"
        lines.append(f"{i}. **{p['name']}** — {brand}")
        lines.append(f"   ₹{p['price']:,} · {rating}")
        lines.append("")

    return {"final_response": "\n".join(lines)}


# ROUTING FUNCTIONS (only one of each!)


def route_after_extraction(state: AgentState) -> Literal["search", "ask", "unavailable"]:
    if state.get("not_carried"):
        return "unavailable"
    prefs = state.get("preferences") or {}
    has_signal = any(prefs.get(k) for k in ("category", "subcategory", "type", "keywords", "brand"))
    return "search" if has_signal else "ask"


def route_after_search(state: AgentState) -> Literal["rank", "broaden"]:
    results = state.get("search_results") or []
    return "rank" if results else "broaden"


def rank_and_filter(state: AgentState) -> dict:
    """LLM node — ranks raw search results by relevance to the user's request."""
    search_results = state.get("search_results") or []
    user_message = state.get("user_message", "")

    if not search_results:
        return {"ranked_products": []}

    candidates = search_results[:10]
    product_list = "\n".join(
        [
            f"{i+1}. {p['name'][:60]} | ₹{p['price']} | {p['rating']}★ | {p.get('brand', 'N/A')}"
            for i, p in enumerate(candidates)
        ]
    )

    messages = [
        SystemMessage(content=load_prompt("product_ranking")),
        HumanMessage(content=f'User request: "{user_message}"\n\nProducts:\n{product_list}'),
    ]

    raw = call_llm("product", "rank_and_filter", messages)
    logger.info(f"request_id={get_request_id()} | ranker_raw={raw!r} | candidates={len(candidates)}")

    try:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
            parsed = json.loads(match.group()) if match else {}
        if isinstance(parsed, list):
            relevant_idx = parsed
            maybe_idx = []
        else:
            relevant_idx = parsed.get("relevant") or []
            maybe_idx = parsed.get("maybe") or []

        ranked = []
        seen = set()
        for tier, idx_list in ((0, relevant_idx), (1, maybe_idx)):
            for idx in idx_list:
                if isinstance(idx, int) and 1 <= idx <= len(candidates):
                    p = candidates[idx - 1]
                    if p["product_id"] not in seen:
                        ranked.append({**p, "llm_tier": tier})
                        seen.add(p["product_id"])
        # ranked stays [] if ranker explicitly put everything in "no" — let broaden handle it

    except Exception as e:
        logger.error(f"request_id={get_request_id()} | rank_and_filter parse error | error={e}")
        ranked = [{**p, "llm_tier": 1} for p in candidates[:5]]

    logger.info(
        f"request_id={get_request_id()} | rank_and_filter | {len(ranked)} products "
        f"(tier 0: {sum(1 for p in ranked if p.get('llm_tier') == 0)}, "
        f"tier 1: {sum(1 for p in ranked if p.get('llm_tier') == 1)})"
    )
    return {"ranked_products": ranked}


def route_after_rank(state: AgentState) -> Literal["enrich", "broaden"]:
    ranked = state.get("ranked_products") or []
    return "enrich" if ranked else "broaden"


def route_after_broaden(state: AgentState) -> Literal["retry_search", "keyword_recovery", "no_results"]:
    if not state.get("filters_exhausted"):
        return "retry_search"
    original_kw = (state.get("original_preferences") or {}).get("keywords") or []
    keywords_were_relaxed = "keywords" in (state.get("relaxed_filters") or [])
    if original_kw and keywords_were_relaxed and not state.get("keyword_recovery_attempted"):
        return "keyword_recovery"
    return "no_results"


def keyword_recovery(state: AgentState) -> dict:
    """Last-resort cross-catalog search using only the user's original keywords.
    Fires once after full filter exhaustion — finds products under a different
    subcategory than what was searched (e.g. ethernet adapter for 'usb hub with ethernet').
    """
    original_kw = (state.get("original_preferences") or {}).get("keywords") or []
    logger.info(f"request_id={get_request_id()} | keyword_recovery | keywords={original_kw}")
    results = search_products(keywords=original_kw, limit=20)
    if results:
        return {"search_results": results, "keyword_recovery_attempted": True, "filters_exhausted": False}
    return {"keyword_recovery_attempted": True, "filters_exhausted": True}


def route_after_keyword_recovery(state: AgentState) -> Literal["rank", "no_results"]:
    if state.get("filters_exhausted") or not state.get("search_results"):
        return "no_results"
    return "rank"


# GRAPH


def build_product_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("extract_preferences", extract_preferences)
    graph.add_node("ask_for_preferences", ask_for_preferences)
    graph.add_node("respond_unavailable", respond_unavailable)
    graph.add_node("search_products", do_search_products)
    graph.add_node("broaden_search", broaden_search)
    graph.add_node("keyword_recovery", keyword_recovery)
    graph.add_node("respond_no_results", respond_no_results)
    graph.add_node("rank_and_filter", rank_and_filter)
    graph.add_node("product_enrichment", product_enrichment_subgraph)
    graph.add_node("format_recommendations", format_recommendations)

    graph.set_entry_point("extract_preferences")

    graph.add_conditional_edges(
        "extract_preferences",
        route_after_extraction,
        {"search": "search_products", "ask": "ask_for_preferences", "unavailable": "respond_unavailable"},
    )

    graph.add_conditional_edges(
        "search_products", route_after_search, {"rank": "rank_and_filter", "broaden": "broaden_search"}
    )

    graph.add_conditional_edges(
        "broaden_search",
        route_after_broaden,
        {"retry_search": "search_products", "keyword_recovery": "keyword_recovery", "no_results": "respond_no_results"},
    )

    graph.add_conditional_edges(
        "keyword_recovery",
        route_after_keyword_recovery,
        {"rank": "rank_and_filter", "no_results": "respond_no_results"},
    )

    graph.add_conditional_edges(
        "rank_and_filter", route_after_rank, {"enrich": "product_enrichment", "broaden": "broaden_search"}
    )

    graph.add_edge("product_enrichment", "format_recommendations")
    graph.add_edge("ask_for_preferences", END)
    graph.add_edge("respond_unavailable", END)
    graph.add_edge("respond_no_results", END)
    graph.add_edge("format_recommendations", END)

    return graph.compile()


product_agent_graph = build_product_agent_graph()
