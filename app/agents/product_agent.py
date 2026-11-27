import json
import re
from typing import List, Literal, Optional

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, field_validator

from app.agents.state import ProductInput, ProductOutput, ProductState, SearchInput, SearchOutput, SearchState
from app.catalog.features import features_to_filters, match_attributes
from app.catalog.runtime import catalog_blurb, fold_brand, get_catalog
from app.catalog.schema import norm
from app.tools.product_tools import search_products
from app.core import config
from app.search import hybrid
from app.agents.product_qa import product_qa_graph
from app.core.llm import call_llm
from app.core.logger import get_logger, get_request_id
from app.core.prompt_loader import load_prompt

logger = get_logger("app.agents.product_agent")

# What we sell lives in the product_types table (ADR 0005): no catalog constants in code.
CATALOG_BLURB = catalog_blurb()


class ProductSearch(BaseModel):
    """What this message changes in the shopper's search filters. Code merges it into the previous ones."""

    product: Optional[str] = Field(None, description="the product: a type or kind from the list, or the shopper's word")
    features: List[str] = Field(default_factory=list, description="features and specs asked for")
    brand: Optional[str] = None
    max_price: Optional[int] = Field(None, description="rupees")
    min_price: Optional[int] = Field(None, description="rupees")
    min_rating: Optional[float] = Field(None, description="out of 5")
    not_carried: Optional[str] = Field(None, description="what they asked for, if we don't sell that kind of thing")
    clear: List[str] = Field(
        default_factory=list, description="filters the shopper drops: features, brand, prices, rating"
    )

    @field_validator("product", "brand", "not_carried", mode="before")
    @classmethod
    def _text_or_none(cls, value):
        if not isinstance(value, str):
            return None
        # A malformed tool call can leak markup into a field ('"tablet" </Cat> <parameter=...'):
        # keep the text before the first line break or tag.
        text = re.split(r"[\n<]", value.strip(), maxsplit=1)[0]
        return text.strip().strip("\"'").strip() or None

    @field_validator("features", "clear", mode="before")
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


# Filters a shopper can drop, by name ("any brand" → clear brand). The product itself is replaced, not dropped.
FILTER_FIELDS = ("features", "brand", "max_price", "min_price", "min_rating")


def _different_product(old: Optional[str], new: str) -> bool:
    """A product of another type ("earphones" after "smartwatch") starts a new search."""
    if not old:
        return False
    catalog = get_catalog()
    (a, _), (b, _) = catalog.resolve_product(old), catalog.resolve_product(new)
    if a is not None and b is not None:
        return a.name != b.name
    return norm(old) != norm(new)


def merge_preferences(previous: dict, patch: dict) -> dict:
    """The conversation's filters, kept by code: the model only reports what the new message changes.

    A different product starts fresh (the old brand, prices and features go, unless restated); `clear`
    drops filters; new features are added to the ones already asked for.
    """
    merged = {**EMPTY_PREFERENCES, **{k: v for k, v in (previous or {}).items() if k in EMPTY_PREFERENCES}}
    product = patch.get("product")
    if product and _different_product(merged["product"], product):
        merged = dict(EMPTY_PREFERENCES)
    if product:
        merged["product"] = product
    for name in patch.get("clear") or []:
        if name in FILTER_FIELDS:
            merged[name] = [] if name == "features" else None
    for name in ("brand", "max_price", "min_price", "min_rating"):
        if patch.get(name) is not None:
            merged[name] = patch[name]
    have = list(merged["features"] or [])
    merged["features"] = have + [f for f in patch.get("features") or [] if norm(f) not in {norm(h) for h in have}]
    return merged


def active_filters(prefs: dict) -> list:
    """The filters shown as chips under the reply. Every chip but the product can be removed."""
    chips = [{"field": "product", "label": prefs["product"], "removable": False}] if prefs.get("product") else []
    chips += [{"field": "features", "value": f, "label": f, "removable": True} for f in prefs.get("features") or []]
    if prefs.get("brand"):
        chips.append({"field": "brand", "label": prefs["brand"], "removable": True})
    if prefs.get("max_price"):
        chips.append({"field": "max_price", "label": f"under ₹{prefs['max_price']:,}", "removable": True})
    if prefs.get("min_price"):
        chips.append({"field": "min_price", "label": f"over ₹{prefs['min_price']:,}", "removable": True})
    if prefs.get("min_rating"):
        chips.append({"field": "min_rating", "label": f"{prefs['min_rating']:g}★ and up", "removable": True})
    return chips


def ground_product(patch: dict, message: str, previous: dict) -> dict:
    """Check the model's product against the words the shopper actually used; the catalog decides.

    - A first message whose product the model missed ("breville electric kettle" -> only a brand) gets
      the product the message names, including one we don't sell ("iphone 15").
    - A bare type where the message names one of its kinds ("cooking appliance" for "sandwich maker")
      keeps the kind, so the search is as specific as the shopper was.
    """
    catalog = get_catalog()
    named, kind, word = catalog.product_in(message)
    if named is None:
        return patch
    product = patch.get("product")
    if not product and not patch.get("not_carried") and not previous.get("product"):
        return {**patch, "product": word}
    ptype, pkind = catalog.resolve_product(product)
    if ptype is not None and ptype.name == named.name and kind and not pkind:
        return {**patch, "product": kind}
    return patch


def extract_preferences(state: ProductState) -> dict:
    """LLM node: previous filters + new message → what changed; code merges it into the filters."""
    previous = {k: v for k, v in (state.get("preferences") or {}).items() if k in EMPTY_PREFERENCES and v}
    message = state.get("user_message", "")
    catalog = get_catalog()
    parsed = call_llm(
        "product",
        "extract_preferences",
        [
            SystemMessage(content=load_prompt("product_extraction", types=catalog.type_lines())),
            HumanMessage(content=f"So far: {json.dumps(previous)} | Message: {message}"),
        ],
        schema=ProductSearch,
    )
    out = ground_product(parsed.model_dump() if parsed is not None else {}, message, previous)

    # Whether we sell something is decided by the catalog, not the model: a type we stock but don't
    # sell (phones, laptops, tablets) gets its suggestion, and a "not carried" word that names a type
    # we do sell (the model said we don't carry geysers) is searched for instead.
    ptype, _ = catalog.resolve_product(out.get("product"))
    claimed, _ = catalog.resolve_product(out.get("not_carried"))
    not_carried = None
    for word, found in ((out.get("product"), ptype), (out.get("not_carried"), claimed)):
        if found is not None and not found.served:
            not_carried = {"item": word, "suggestion": found.suggestion}
            break
    if not_carried is None and out.get("not_carried") and ptype is None and claimed is None:
        not_carried = {"item": out["not_carried"], "suggestion": None}
    if claimed is not None and claimed.served and not out.get("product"):
        out["product"] = out["not_carried"]
    nothing_asked = not any(out.get(k) for k in ("product", "features", "brand")) and not previous.get("product")
    if not_carried is None and nothing_asked and not out.get("not_carried"):
        match = _closest_in_catalog(None, message)  # a need with no product word: "fuzz balls on sweaters"
        if match is not None:
            out["product"] = match["word"]
    if not_carried is not None and not_carried["suggestion"] is None:
        match = _closest_in_catalog(out.get("not_carried"), message)
        if match is not None:  # "lint remover" under a renamed type, "fuzz balls" -> lint remover
            not_carried = None
            out["product"], out["not_carried"] = match["word"], None
    preferences = merge_preferences(state.get("preferences") or {}, out)
    logger.info(
        f"request_id={get_request_id()} | EXTRACTED: {json.dumps(out)} | MERGED: {json.dumps(preferences)}"
        f" | not_carried={not_carried}"
    )
    return {
        "preferences": preferences,
        "not_carried": not_carried,
        "relaxed_filters": [],
        "active_filters": [] if not_carried else active_filters(preferences),
    }


def _closest_in_catalog(word: Optional[str], message: str) -> Optional[dict]:
    """Before "we don't carry X" for something the catalog has no word for: is there a product that
    means the same? Only with hybrid search on; the threshold is tuned on the dev queries."""
    if config.PRODUCT_SEARCH != "hybrid":
        return None
    matches = [m for m in (hybrid.catalog_match(word), hybrid.catalog_match(message)) if m]
    best = max(matches, key=lambda m: m["similarity"], default=None)
    logger.info(f"request_id={get_request_id()} | not_carried check | {word!r} | closest={best}")
    return best if best and best["similarity"] >= config.NOT_CARRIED_MIN_SIM else None


def apply_filter_edit(state: ProductState) -> dict:
    """A chip was removed: drop that filter and search again. No model call."""
    edit = state.get("filter_edit") or {}
    prefs = {**EMPTY_PREFERENCES, **(state.get("preferences") or {})}
    field = edit.get("field")
    if field == "features":
        prefs["features"] = [f for f in prefs.get("features") or [] if f != edit.get("value")]
    elif field in FILTER_FIELDS:
        prefs[field] = None
    else:
        logger.info(f"request_id={get_request_id()} | filter edit ignored | {edit}")
    return {"preferences": prefs, "not_carried": None, "relaxed_filters": [], "active_filters": active_filters(prefs)}


# A budget ("under 2000", "₹1500"); order ids like ORD-2005 are not prices.
PRICE_WORDS = re.compile(
    r"\b(?:under|below|above|over|less than|more than|budget|rs\.?)\b|₹|(?<![\w-])\d{3,}\b", re.IGNORECASE
)
# Pointing at the list on screen: "the first one", "which of these", "is it waterproof".
LIST_REFERENCE = re.compile(
    r"\b(?:first|second|third|1st|2nd|3rd|these|those|them|it|its|this one|that one|which one|which of)\b",
    re.IGNORECASE,
)


def names_a_search(message: str) -> bool:
    """Is this a new or refined search rather than a question about the cards on screen?

    A brand or a budget always means a search ("what about Bajaj" shows Bajaj products, not the
    Bajaj card). Otherwise a reference to the list means a question ("battery life of the third
    one"), and a product word without one means a search ("philips air purifier").
    """
    message = message or ""
    catalog = get_catalog()
    words = re.findall(r"[a-z0-9+-]+", norm(message))
    phrases = words + [f"{a} {b}" for a, b in zip(words, words[1:])]
    if PRICE_WORDS.search(message) or any(fold_brand(p) in catalog.brands for p in phrases if len(fold_brand(p)) >= 2):
        return True
    if LIST_REFERENCE.search(message):
        return False
    return catalog.product_in(message)[0] is not None


def asks_about_shown(message: str, model_says: bool, shown) -> bool:
    """A question about the cards on screen rather than a search: the router model says so, or the message
    points at the list, and either way it names no search. The model alone now and then misses "does the
    first one come with a warranty?" (1 of 5 calls on 2026-11-25), and that turn then searched for kettles."""
    if not shown or names_a_search(message):
        return False
    return bool(model_says or LIST_REFERENCE.search(message or ""))


def route_entry(state: ProductState) -> Literal["edit", "qa", "extract"]:
    if state.get("filter_edit"):
        return "edit"
    if state.get("about_shown") and state.get("shown_products"):
        return "qa"  # the router decided (asks_about_shown): the tool-using Q&A loop (ADR 0016)
    return "extract"


def ask_for_preferences(state: ProductState) -> dict:
    logger.info(f"request_id={get_request_id()} | Asking for preferences")
    return {"final_response": f"What are you looking for? Here's what we carry:\n\n{CATALOG_BLURB}"}


def respond_unavailable(state: ProductState) -> dict:
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


def route_after_extraction(state: ProductState) -> Literal["search", "ask", "unavailable"]:
    if state.get("not_carried"):
        return "unavailable"
    prefs = state.get("preferences") or {}
    has_signal = any(prefs.get(k) for k in ("product", "features", "brand"))
    return "search" if has_signal else "ask"


def _use_hybrid() -> bool:
    return config.PRODUCT_SEARCH == "hybrid" and hybrid.hybrid_available()


def search_filters(prefs: dict, message: str = "") -> dict:
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
    elif prefs.get("product") and not _use_hybrid():
        keywords = [prefs["product"], *keywords]
    words = [prefs.get("product") or "", *(prefs.get("features") or [])]
    if config.HYBRID_QUERY == "prefs+message":
        words.append(message)
    return {
        "query": " ".join(w for w in words if w).strip(),
        "product_type": ptype.name if ptype else None,
        "attributes": attributes,
        "brand": prefs.get("brand"),
        "max_price": prefs.get("max_price"),
        "min_price": prefs.get("min_price"),
        "min_rating": prefs.get("min_rating"),
        "keywords": keywords,
    }


# ── Search loop: plan → search → (nothing found?) loosen → search … ──────────────
# Optional filters, dropped one at a time (cumulatively) when a search finds nothing.
# The product type is never dropped: showing a different kind of product is not a match.
RELAXATION_ORDER = ["price", "brand", "attributes", "keywords"]


def plan_search(state: SearchState) -> dict:
    """Working filters for this turn. The loop loosens these, never the shopper's preferences."""
    filters = search_filters(state.get("preferences") or {}, state.get("user_message") or "")
    return {"search_filters": filters, "relaxed_filters": []}


def search(state: SearchState) -> dict:
    filters = state["search_filters"]
    if _use_hybrid():
        results = hybrid.hybrid_search(**filters, limit=10)
    else:
        results = search_products(**{k: v for k, v in filters.items() if k != "query"}, limit=10)
    logger.info(
        f"request_id={get_request_id()} | search | {filters} | found={len(results)}"
        f" | relaxed={state.get('relaxed_filters')}"
    )
    return {"search_results": results}


def next_relaxation(filters: dict, relaxed: list) -> Optional[str]:
    """The next filter to loosen: later in RELAXATION_ORDER than the last one, and actually set."""
    start = RELAXATION_ORDER.index(relaxed[-1]) + 1 if relaxed else 0
    for name in RELAXATION_ORDER[start:]:
        if filters.get("max_price" if name == "price" else name):
            return name
    return None


def found_what_was_asked(results: list, filters: dict) -> bool:
    """A search succeeded if it found the requested type. Hybrid search also returns other types
    (the type is a vote, not a gate), and those alone must not stop the loop from loosening the
    brand or price: "sony headphones under 500" would otherwise end on a Sony cable."""
    wanted = filters.get("product_type")
    return any(r.get("type") == wanted for r in results) if wanted else bool(results)


def route_after_loosen_check(state: SearchState) -> Literal["loosen", "done"]:
    if found_what_was_asked(state.get("search_results") or [], state["search_filters"]):
        return "done"
    return "loosen" if next_relaxation(state["search_filters"], state.get("relaxed_filters") or []) else "done"


def loosen(state: SearchState) -> dict:
    """Price goes up 25%; brand, attributes or keywords are dropped."""
    filters = dict(state["search_filters"])
    relaxed = state.get("relaxed_filters") or []
    name = next_relaxation(filters, relaxed)
    if name == "price":
        filters["max_price"] = int(filters["max_price"] * 1.25)
    else:
        filters[name] = {} if name == "attributes" else [] if name == "keywords" else None
    return {"search_filters": filters, "relaxed_filters": [*relaxed, name]}


def build_search_loop():
    """At most 1 + len(RELAXATION_ORDER) searches: each loosen step moves further down the order."""
    graph = StateGraph(SearchState, input_schema=SearchInput, output_schema=SearchOutput)
    graph.add_node("plan_search", plan_search)
    graph.add_node("search", search)
    graph.add_node("loosen", loosen)
    graph.set_entry_point("plan_search")
    graph.add_edge("plan_search", "search")
    graph.add_conditional_edges("search", route_after_loosen_check, {"loosen": "loosen", "done": END})
    graph.add_edge("loosen", "search")
    return graph.compile()


find_products = build_search_loop()


class Ranking(BaseModel):
    """1-based indices of the listed products."""

    same_kind: List[int] = Field(default_factory=list, description="the kind of product asked for, any brand/spec")
    exact: List[int] = Field(default_factory=list, description="of those, also matching brand, features and specs")


def rank_products(state: ProductState) -> dict:
    """LLM node: drop candidates that aren't what the shopper asked for, then order the rest."""
    candidates = (state.get("search_results") or [])[:10]
    if not candidates:
        return {"ranked_products": []}
    if config.PRODUCT_RANKER == "off":  # the search order as it is (evals measure retrieval this way)
        prefs = state.get("preferences") or {}
        return {"ranked_products": [{**p, "llm_tier": 0, "score": score(p, prefs)} for p in candidates[:5]]}
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
    if not picked and state.get("relaxed_filters"):
        # The loop already widened the filters and says so in the reply; products of the requested
        # type are what the shopper asked for, minus a spec ("usb hub with ethernet" -> usb hubs).
        wanted = search_filters(prefs)["product_type"]
        same_type = [p for p in candidates if wanted and p.get("type") == wanted]
        picked = [{**p, "llm_tier": 1, "score": score(p, prefs)} for p in same_type]
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


def order_by_score(state: ProductState) -> dict:
    """Ranking without the model, after a chip removal: the filters are the shopper's own, so every
    result already is what they asked for; order them by rating, budget fit and feature match."""
    prefs = state.get("preferences") or {}
    scored = [{**p, "llm_tier": 0, "score": score(p, prefs)} for p in (state.get("search_results") or [])[:10]]
    return {"ranked_products": sorted(scored, key=lambda p: -p["score"])[:5]}


def route_after_search(state: ProductState) -> Literal["rank", "score"]:
    return "score" if state.get("filter_edit") else "rank"


def route_after_rank(state: ProductState) -> Literal["recommend", "no_results"]:
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


def differences(prefs: dict, shown: list, relaxed: list) -> list:
    """How the shown products differ from the request, read off the products themselves, so a note
    is true by construction: a budget note only when a shown product is over it, and so on. Features
    can't be read off a product reliably, so they're named only when the search had to drop them."""
    notes = []
    budget = prefs.get("max_price")
    if budget and any((p.get("price") or 0) > budget for p in shown):
        notes.append(f"Some of these are over your ₹{budget:,} budget.")
    floor = prefs.get("min_price")
    if floor and any((p.get("price") or 0) < floor for p in shown):
        notes.append(f"Some of these cost less than ₹{floor:,}.")
    stars = prefs.get("min_rating")
    if stars and any((p.get("rating") or 0) < stars for p in shown):
        notes.append(f"Some of these are rated below {stars:g}★.")
    features = prefs.get("features") or []
    if features and ({"attributes", "keywords"} & set(relaxed)):
        notes.append(f"The details don't confirm {', '.join(features)} for these.")
    return notes


def format_recommendations(state: ProductState) -> dict:
    prefs = state.get("preferences") or {}
    top3 = (state.get("ranked_products") or [])[:3]
    relaxed = state.get("relaxed_filters") or []
    # Say the results miss something only when the shown products show it (ADR 0020): the brand isn't
    # among them, one is over budget, a feature had to be dropped. The search loop's history alone is no
    # evidence (it reported "widened the price" when the price was never the problem), and neither is the
    # ranker's `exact` list (empty in 65% of gpt-oss-20b's answers, matching results included).
    notes = [n for n in [_brand_note(prefs, top3).strip(), *differences(prefs, top3, relaxed)] if n]
    lines = ["\n".join(notes) + "\n" if notes else "Here's what I found:\n"]
    for i, p in enumerate(top3, 1):
        rating = f"{p['rating']:.1f}/5" if p.get("rating") is not None else "Not rated"
        lines.append(f"{i}. **{p.get('title') or p['name']}** — {p.get('brand') or 'Unknown brand'}")
        lines.append(f"   ₹{p['price']:,} · {rating}")
        lines.append("")
    shown = [{k: p.get(k) for k in ("product_id", "title", "brand", "price")} for p in top3]
    return {"final_response": "\n".join(lines), "shown_products": shown}


def respond_no_results(state: ProductState) -> dict:
    prefs = state.get("preferences") or {}
    label = _label(prefs)
    reply = f"I couldn't find any {label} matching your request."
    if prefs.get("brand") and not _stocks_brand(prefs):
        reply = f"We don't carry {prefs['brand']} {label}. " + reply
    return {"final_response": reply + " Try a different budget, brand or product."}


def build_product_agent_graph():
    graph = StateGraph(ProductState, input_schema=ProductInput, output_schema=ProductOutput)
    graph.add_node("extract_preferences", extract_preferences)
    graph.add_node("apply_filter_edit", apply_filter_edit)
    graph.add_node("order_by_score", order_by_score)
    graph.add_node("ask_for_preferences", ask_for_preferences)
    graph.add_node("respond_unavailable", respond_unavailable)
    graph.add_node("find_products", find_products)
    graph.add_node("rank_products", rank_products)
    graph.add_node("format_recommendations", format_recommendations)
    graph.add_node("respond_no_results", respond_no_results)
    graph.add_node("answer_question", product_qa_graph)

    graph.add_conditional_edges(
        START, route_entry, {"edit": "apply_filter_edit", "qa": "answer_question", "extract": "extract_preferences"}
    )
    after_filters = {"search": "find_products", "ask": "ask_for_preferences", "unavailable": "respond_unavailable"}
    graph.add_conditional_edges("extract_preferences", route_after_extraction, after_filters)
    graph.add_conditional_edges("apply_filter_edit", route_after_extraction, after_filters)
    graph.add_conditional_edges(
        "find_products", route_after_search, {"rank": "rank_products", "score": "order_by_score"}
    )
    after_rank = {"recommend": "format_recommendations", "no_results": "respond_no_results"}
    graph.add_conditional_edges("rank_products", route_after_rank, after_rank)
    graph.add_conditional_edges("order_by_score", route_after_rank, after_rank)
    terminal = ("ask_for_preferences", "respond_unavailable", "format_recommendations", "respond_no_results")
    for node in (*terminal, "answer_question"):
        graph.add_edge(node, END)
    return graph.compile()


product_agent_graph = build_product_agent_graph()
