import copy
import json
from typing import List, Literal, Optional

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from pydantic import BaseModel, Field, field_validator

from app.agents.state import AgentState
from app.catalog.features import features_to_filters, match_attributes
from app.catalog.runtime import catalog_blurb, get_catalog
from app.tools.product_tools import search_products
from app.core.llm import call_llm
from app.core.logger import get_logger, get_request_id
from app.core.prompt_loader import load_prompt

logger = get_logger("app.agents.product_agent")

# What we sell lives in the product_types table (ADR 0005): no catalog constants in code.
CATALOG_BLURB = catalog_blurb()


class ProductSearch(BaseModel):
    """Catalog search filters for what the shopper wants now."""

    product: Optional[str] = Field(None, description="the product: a type or kind from the list, or the shopper's word")
    features: List[str] = Field(default_factory=list, description="features and specs asked for")
    brand: Optional[str] = None
    max_price: Optional[int] = Field(None, description="rupees")
    min_price: Optional[int] = Field(None, description="rupees")
    min_rating: Optional[float] = Field(None, description="out of 5")
    not_carried: Optional[str] = Field(None, description="what they asked for, if we don't sell that kind of thing")

    @field_validator("product", "brand", "not_carried", mode="before")
    @classmethod
    def _text_or_none(cls, value):
        return value.strip() or None if isinstance(value, str) else None

    @field_validator("features", mode="before")
    @classmethod
    def _list(cls, value):
        return [k.strip() for k in value if isinstance(k, str) and k.strip()] if isinstance(value, list) else []


def search_schema():
    return ProductSearch


EMPTY_PREFERENCES = {
    "product": None,
    "features": [],
    "brand": None,
    "max_price": None,
    "min_price": None,
    "min_rating": None,
}


def extract_preferences(state: AgentState) -> dict:
    """LLM node: previous filters + new message → complete filters for what the shopper wants now."""
    previous = {k: v for k, v in (state.get("preferences") or {}).items() if k in EMPTY_PREFERENCES and v}
    message = state.get("user_message", "")
    catalog = get_catalog()
    parsed = call_llm(
        "product",
        "extract_preferences",
        [
            SystemMessage(content=load_prompt("product_extraction", types=catalog.type_lines())),
            HumanMessage(content=f"Previous: {json.dumps(previous)} | Message: {message}"),
        ],
        schema=ProductSearch,
    )
    out = parsed.model_dump() if parsed is not None else {}
    preferences = {k: out.get(k, v) for k, v in EMPTY_PREFERENCES.items()}
    preferences["features"] = out.get("features") or []

    # Whether we sell something is decided by the catalog, not the model: a type we stock but don't
    # sell (phones, laptops, tablets) gets its suggestion, and a "not carried" word that names a type
    # we do sell (the model said we don't carry geysers) is ignored.
    ptype, _ = catalog.resolve_product(preferences["product"])
    claimed, _ = catalog.resolve_product(out.get("not_carried"))
    not_carried = None
    for word, found in ((preferences["product"], ptype), (out.get("not_carried"), claimed)):
        if found is not None and not found.served:
            not_carried = {"item": word, "suggestion": found.suggestion}
            break
    if not_carried is None and out.get("not_carried") and ptype is None and claimed is None:
        not_carried = {"item": out["not_carried"], "suggestion": None}
    if claimed is not None and claimed.served and not preferences["product"]:
        preferences["product"] = out["not_carried"]  # search for it instead of refusing
    logger.info(f"request_id={get_request_id()} | EXTRACTED: {json.dumps(preferences)} | not_carried={not_carried}")
    return {
        "preferences": preferences,
        "original_preferences": copy.deepcopy(preferences),
        "not_carried": not_carried,
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
    has_signal = any(prefs.get(k) for k in ("product", "features", "brand"))
    return "search" if has_signal else "ask"


def search_filters(prefs: dict) -> dict:
    """Shopper preferences → search_products arguments, using the catalog (no model call).

    The product word picks the type (and kind); feature words that name an attribute value become
    attribute filters; anything else is matched against product names. An unknown product word is
    searched by name across every served type.
    """
    ptype, kind = get_catalog().resolve_product(prefs.get("product"))
    attributes, keywords = features_to_filters(ptype, prefs.get("features") or [])
    if ptype is not None:
        # "immersion rod" names the type and also its heater_type; the word itself is never a keyword.
        attributes = {**match_attributes(ptype, prefs["product"]), **attributes}
        if kind:
            attributes["kind"] = kind
    elif prefs.get("product"):
        keywords = [prefs["product"], *keywords]
    return {
        "product_type": ptype.name if ptype else None,
        "attributes": attributes,
        "brand": prefs.get("brand"),
        "max_price": prefs.get("max_price"),
        "min_price": prefs.get("min_price"),
        "min_rating": prefs.get("min_rating"),
        "keywords": keywords,
    }


# Optional filters, dropped one at a time (cumulatively) when a search finds nothing.
# The product type is never dropped: showing a different kind of product is not a match.
RELAXATION_ORDER = ["price", "brand", "attributes", "keywords"]


def find_products(state: AgentState) -> dict:
    """Deterministic search with one fallback loop: relax optional filters until something matches.

    Works on a copy, so the shopper's own preferences (kept for the next turn) are never relaxed.
    """
    filters = search_filters(state.get("preferences") or {})
    relaxed: list = []
    results = search_products(**filters, limit=10)
    for name in RELAXATION_ORDER:
        if results:
            break
        if name == "price" and filters.get("max_price"):
            filters["max_price"] = int(filters["max_price"] * 1.25)
        elif name != "price" and filters.get(name):
            filters[name] = {} if name == "attributes" else [] if name == "keywords" else None
        else:
            continue
        relaxed.append(name)
        results = search_products(**filters, limit=10)
    logger.info(f"request_id={get_request_id()} | search | {filters} | found={len(results)} | relaxed={relaxed}")
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
    """Three factors: rating, how well the price uses the budget, and match on brand and features."""
    rating = (product.get("rating") or 0) / 5
    budget = prefs.get("max_price")
    if budget:
        ratio = (product.get("price") or 0) / budget
        price_fit = 0.0 if ratio > 1 else (1.0 if ratio >= 0.5 else 0.5)
    else:
        price_fit = 0.5
    text = f"{product.get('name', '')} {product.get('brand', '')} {product.get('type', '')}".lower()
    wanted = [w.lower() for w in [prefs.get("brand"), *(prefs.get("features") or [])] if w]
    match = sum(w in text for w in wanted) / len(wanted) if wanted else 0.5
    return round(0.5 * rating + 0.25 * price_fit + 0.25 * match, 3)


def route_after_rank(state: AgentState) -> Literal["recommend", "no_results"]:
    return "recommend" if state.get("ranked_products") else "no_results"


def _label(prefs: dict) -> str:
    return prefs.get("product") or (prefs.get("features") or [None])[0] or "products"


def _stocks_brand(prefs: dict) -> bool:
    """Do we sell this brand in this product type at all, ignoring every other filter?"""
    product_type = search_filters(prefs)["product_type"]
    return bool(search_products(brand=prefs["brand"], product_type=product_type, limit=1))


def _brand_note(prefs: dict, shown: list) -> str:
    """Say plainly when the brand asked for isn't in the results."""
    brand = prefs.get("brand")
    resolved = get_catalog().resolve_brand(brand) if brand else None
    names = {brand.lower(), resolved[1].lower()} if resolved else {(brand or "").lower()}
    if not brand or any((p.get("brand") or "").lower() in names for p in shown):
        return ""
    label = _label(prefs)
    if _stocks_brand(prefs):
        return (
            f"I couldn't find {brand} {label} within your filters, so here are the closest options from other brands:\n"
        )
    return f"We don't carry {brand} {label}, so here are the closest options from other brands:\n"


RELAXED_WORDS = {
    "price": "the price limit (+25%)",
    "brand": "the brand",
    "attributes": "some features",
    "keywords": "some keywords",
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
        lines.append(f"{i}. **{p.get('title') or p['name']}** — {p.get('brand') or 'Unknown brand'}")
        lines.append(f"   ₹{p['price']:,} · {rating}")
        lines.append("")
    return {"final_response": "\n".join(lines)}


def respond_no_results(state: AgentState) -> dict:
    prefs = state.get("preferences") or {}
    label = _label(prefs)
    reply = f"I couldn't find any {label} matching your request."
    if prefs.get("brand") and not _stocks_brand(prefs):
        reply = f"We don't carry {prefs['brand']} {label}. " + reply
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
