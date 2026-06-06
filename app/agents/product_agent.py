import os
import re
import json
import copy
import time
from typing import Literal
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from dotenv import load_dotenv

from app.agents.state import AgentState
from app.agents.product_agent_subgraph import product_enrichment_subgraph
from app.tools.product_tools import search_products
from app.core.logger import get_logger, get_request_id
from app.core.metrics import llm_requests_total, llm_tokens_total, llm_duration_seconds

load_dotenv()

logger = get_logger("app.agents.product_agent")

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=os.getenv("OPENAI_API_KEY"))


SERVED_CATEGORIES = {"Electronics", "Computers & Accessories", "Home & Kitchen", "Office Products"}

# Subcategories that exist in the DB but are not served — exclude from user-facing blurb
BLURB_EXCLUDED_SUBCATEGORIES = frozenset(
    {
        "smartphone",
        "laptop",
        "tablet",
        "clothing",
        "shoes",
        "furniture",
        "book",
        "toy",
        "sports equipment",
    }
)


def build_catalog_blurb() -> str:
    """Build catalog blurb from DB — only the 4 categories the system can actually serve."""
    from app.db.database import SessionLocal
    from app.models.product import Product
    from sqlalchemy import func

    db = SessionLocal()
    try:
        counts = (
            db.query(Product.category, func.count(Product.product_id).label("cnt"))
            .filter(Product.category.in_(SERVED_CATEGORIES))
            .group_by(Product.category)
            .order_by(func.count(Product.product_id).desc())
            .all()
        )

        sub_rows = (
            db.query(Product.category, Product.subcategory, func.count(Product.product_id).label("cnt"))
            .filter(
                Product.category.in_(SERVED_CATEGORIES),
                Product.subcategory.isnot(None),
                Product.subcategory.notin_(BLURB_EXCLUDED_SUBCATEGORIES),
            )
            .group_by(Product.category, Product.subcategory)
            .order_by(Product.category, func.count(Product.product_id).desc())
            .all()
        )

        subcat_map: dict = {}
        for cat, sub, _ in sub_rows:
            if cat not in subcat_map:
                subcat_map[cat] = []
            if len(subcat_map[cat]) < 3:
                subcat_map[cat].append(sub)

        lines = []
        for cat, cnt in counts:
            subs = subcat_map.get(cat, [])
            suffix = f" — {', '.join(subs)}" if subs else ""
            lines.append(f"• {cat} ({cnt} products){suffix}")

        return "\n".join(lines)
    except Exception:  # pragma: no cover
        return ""
    finally:
        db.close()


# Load once at startup — returns empty string if DB is unavailable (e.g. during tests)
CATALOG_BLURB = build_catalog_blurb()


# Controlled catalog for the extraction prompt.
# This is deliberately static — it defines what the LLM is *allowed* to search,
# not what happens to be in the DB. Update this when subcategories are added via migration.
PROMPT_CATALOG = (
    "Electronics: Cameras & Photography | adapter | battery | cable | camera accessory"
    " | calculators | charger | headphones | memory card | pen | phone case | phone stand | power bank"
    " | projector | screen protector | selfie stick | set top box | smartwatch | speakers"
    " | streaming device | tv | tv mount | tv remote\n"
    "Computers & Accessories: adapter | cable | drawing tablet | external hdd | external ssd"
    " | gamepad | ink cartridge | keyboard | laptop bag | memory card | microphone | monitor"
    " | monitor stand | mouse | pen drive | printer | router | screen protector | ups"
    " | usb hub | webcam | wifi adapter | wifi range extender\n"
    "Home & Kitchen: air conditioner | air fryer | air purifier | blender | ceiling fan"
    " | chopper | coffee maker | egg boiler | electric kettle | frother | garment steamer"
    " | hand mixer | humidifier | induction | iron | juicer | kitchen scale | kitchen tools"
    " | lint remover | mixer grinder | pedestal fan | pressure washer | rice cooker"
    " | room heater | roti maker | sandwich maker | sealing machine | sewing machine"
    " | storage organizer | toaster | vacuum cleaner | waffle maker | water filter"
    " | water heater | water purifier | yogurt maker\n"
    "Office Products: art supplies | stationery"
)

# Generic relaxation order for all categories.
# keywords before subcategory: a missing feature keyword (e.g. "noise cancelling") shouldn't
# erase the subcategory — try without the keyword first, then widen to the full subcategory.
RELAXATION_ORDER = [
    "type",
    "price_increase",
    "brand",
    "keywords",
    "subcategory",
]

EXTRACTION_SYSTEM_PROMPT = f"""Extract product search preferences. Return JSON only.

Catalog (use exact subcategory names):
{PROMPT_CATALOG}

Output schema: {{"category": str|null, "subcategory": str|null, "type": str|null, "brand": str|null, "max_price": int|null, "min_price": int|null, "min_rating": float|null, "keywords": [str], "unavailable_request": bool}}

Type variants (Electronics only):
- headphones: neckband | tws earbuds | wired earphones | over-ear headphones
- speakers: bluetooth speaker | soundbar | home theatre
- tv: smart tv
- mouse/keyboard: wired | wireless | gaming | mechanical | bluetooth (null if unspecified)
- cable/adapter: type=null — use keywords for HDMI/USB-C/lightning specifics
- Home & Kitchen: type always null

Rules:
- subcategory must exactly match catalog above
- Normalize: mice→mouse, earbuds/earphones→headphones+type, telly→tv, adaptor→adapter, geyser→water heater, AC→air conditioner
- Normalize: pencil/pen/highlighter/eraser/ruler/marker/sketch pad→stationery (Office Products), paintbrush/canvas/palette→art supplies (Office Products)
- Normalize: phone charger/mobile charger→subcategory: charger, keywords: ["USB"] (NOT "phone" — avoids matching AA battery chargers)
- keywords: features not covered by subcategory/type (calling, noise cancellation, 4K, wireless)
- min_rating: set when user asks for quality — "best rated"/"highly rated"/"top rated" → 4.0, "at least 4.5 stars" → 4.5, explicit number like "4 star and above" → 4.0; null otherwise
- Generic category browsing (no specific product): category only, subcategory: null, keywords: []
- Vague browsing (product list, show me products, what do you have): category: null, keywords: [], unavailable_request: false
- unavailable_request: true when the product cannot be mapped to any subcategory in the catalog above. Use the most common real-world interpretation for ambiguous words (e.g. "table" = dining/coffee table → furniture, not drawing tablet; "mobile" = phone → not phone case). false when it maps to a catalog subcategory even approximately.
- Never output string "null" — use JSON null

Examples:
"mixer grinder under 3000" → {{"category": "Home & Kitchen", "subcategory": "mixer grinder", "type": null, "brand": null, "max_price": 3000, "min_price": null, "min_rating": null, "keywords": [], "unavailable_request": false}}
"best rated JBL bluetooth speaker under 2000" → {{"category": "Electronics", "subcategory": "speakers", "type": "bluetooth speaker", "brand": "JBL", "max_price": 2000, "min_price": null, "min_rating": 4.0, "keywords": [], "unavailable_request": false}}
"top rated neckband under 2000" → {{"category": "Electronics", "subcategory": "headphones", "type": "neckband", "brand": null, "max_price": 2000, "min_price": null, "min_rating": 4.0, "keywords": [], "unavailable_request": false}}
"wireless mouse" → {{"category": "Computers & Accessories", "subcategory": "mouse", "type": null, "brand": null, "max_price": null, "min_price": null, "min_rating": null, "keywords": ["wireless"], "unavailable_request": false}}
"4.5 star and above air fryer" → {{"category": "Home & Kitchen", "subcategory": "air fryer", "type": null, "brand": null, "max_price": null, "min_price": null, "min_rating": 4.5, "keywords": [], "unavailable_request": false}}
"laptop under 50000" → {{"category": null, "subcategory": null, "type": null, "brand": null, "max_price": 50000, "min_price": null, "min_rating": null, "keywords": ["laptop"], "unavailable_request": true}}
"geyser under 5000" → {{"category": "Home & Kitchen", "subcategory": "water heater", "type": null, "brand": null, "max_price": 5000, "min_price": null, "min_rating": null, "keywords": [], "unavailable_request": false}}

Respond ONLY with valid JSON."""


def extract_preferences(state: AgentState) -> dict:
    """LLM node — extracts structured preferences from user message."""
    user_message = state.get("user_message", "")
    conversation_history = state.get("conversation_history", [])

    # Extract from the current message only — no history passed to LLM.
    # Context preservation (brand/price inheritance across turns) is handled entirely
    # by the Python merge logic below, not by the LLM. Passing history here caused
    # the LLM to map unrelated product names (e.g. "table" after "mouse") to the
    # previous subcategory instead of extracting them fresh.
    full_prompt = user_message

    messages = [
        SystemMessage(content=EXTRACTION_SYSTEM_PROMPT),
        HumanMessage(content=full_prompt),
    ]

    _t0 = time.perf_counter()
    response = llm.invoke(messages)
    _latency_s = time.perf_counter() - _t0
    _latency_ms = int(_latency_s * 1000)
    _meta = getattr(response, "response_metadata", {})
    _usage = _meta.get("token_usage", {}) if isinstance(_meta, dict) else {}
    logger.info(
        f"request_id={get_request_id()} | LLM_USAGE | agent=product | node=extract_preferences"
        f" | prompt_tokens={_usage.get('prompt_tokens', 0)}"
        f" | completion_tokens={_usage.get('completion_tokens', 0)}"
        f" | total_tokens={_usage.get('total_tokens', 0)}"
        f" | latency_ms={_latency_ms}"
    )
    llm_requests_total.labels(agent="product", node="extract_preferences").inc()
    llm_duration_seconds.labels(agent="product", node="extract_preferences").observe(_latency_s)
    llm_tokens_total.labels(agent="product", node="extract_preferences", token_type="prompt").inc(
        _usage.get("prompt_tokens", 0)
    )
    llm_tokens_total.labels(agent="product", node="extract_preferences", token_type="completion").inc(
        _usage.get("completion_tokens", 0)
    )
    llm_tokens_total.labels(agent="product", node="extract_preferences", token_type="total").inc(
        _usage.get("total_tokens", 0)
    )
    raw = response.content.strip()

    if raw.startswith("```"):
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        preferences = json.loads(raw)
        # LLM occasionally returns the string "null" instead of JSON null
        preferences = {k: (None if v == "null" or v == "None" else v) for k, v in preferences.items()}
    except json.JSONDecodeError as e:
        logger.error(f"request_id={get_request_id()} | " f"Preference parse error | raw={raw} | error={str(e)}")
        preferences = {"category": None, "keywords": [], "unavailable_request": False}

    logger.info(f"request_id={get_request_id()} | RAW_LLM: {json.dumps(preferences)}")

    # Brand-only refinement override: if the LLM set unavailable_request=true but
    # also extracted a brand (and no product keywords), this is a brand-switch on an
    # existing search — not an unavailable product. Clear the flag so the merge can
    # inherit the previous subcategory (e.g. "what about Bajaj" after "mixer grinder").
    previous_prefs = state.get("preferences") or {}
    if (
        preferences.get("unavailable_request")
        and preferences.get("brand")
        and not preferences.get("keywords")
        and previous_prefs.get("subcategory")
    ):
        preferences["unavailable_request"] = False

    # Merge with previous preferences — preserve context across turns
    if previous_prefs and not preferences.get("unavailable_request"):
        new_category = preferences.get("category") or previous_prefs.get("category")
        prev_category = previous_prefs.get("category")
        prev_subcategory = previous_prefs.get("subcategory")
        new_subcategory = preferences.get("subcategory")

        # Guard: if only brand changed (no type change), don't let LLM's brand-name inference
        # override the subcategory (e.g. "Samsung" → earphones when context is TVs).
        if (
            new_category == prev_category
            and prev_subcategory
            and new_subcategory
            and new_subcategory != prev_subcategory
            and not preferences.get("type")
            and preferences.get("brand") is not None
        ):
            new_subcategory = prev_subcategory

        # Detect genuine subcategory change: LLM explicitly extracted a different subcategory.
        # null means "not mentioned this turn", not "changed" — so null is not a change.
        subcategory_changed = (
            new_subcategory is not None and prev_subcategory is not None and new_subcategory != prev_subcategory
        )

        # Category-level switch (e.g. Electronics → Home & Kitchen) always resets everything.
        category_changed = (
            new_category is not None and prev_category is not None and new_category != prev_category
        )

        # Fully vague browsing: LLM found no product signal AND no filters in the new message.
        # Check raw extraction (not post-inheritance new_category) so this fires correctly even
        # mid-session — e.g. "show me something" / "" after a session with min_price=100000.
        vague_browse = (
            not preferences.get("category")
            and not preferences.get("subcategory")
            and not preferences.get("keywords")
            and not preferences.get("brand")
            and preferences.get("max_price") is None
            and preferences.get("min_price") is None
            and preferences.get("min_rating") is None
        )

        # New specific product after a keyword/feature-only turn that stored no subcategory.
        # e.g. "with calling feature" stores subcategory=null; then "calculator" is a new search.
        new_specific_product = bool(new_subcategory and not prev_subcategory)

        if vague_browse:
            # Wipe all accumulated context — show the catalog and let the user start fresh.
            preferences = {
                "category": None, "subcategory": None, "type": None, "brand": None,
                "max_price": None, "min_price": None, "min_rating": None,
                "keywords": [], "unavailable_request": False,
            }
        elif subcategory_changed or category_changed or new_specific_product:
            # New product type — reset all filters to only what the user re-specified.
            # e.g. "headphones under 2000" → "show me monitors" should not carry ₹2000 cap.
            preferences = {
                "category": new_category,
                "subcategory": new_subcategory,
                "type": preferences.get("type"),
                "brand": preferences.get("brand"),
                "max_price": preferences.get("max_price"),
                "min_price": preferences.get("min_price"),
                "min_rating": preferences.get("min_rating"),
                "keywords": preferences.get("keywords") or [],
                "unavailable_request": preferences.get("unavailable_request", False),
            }
        else:
            # Same subcategory (or refinement turn) — preserve all previous filters
            # unless the user explicitly overrode them this turn.
            # Don't inherit subcategory if the new query has keywords — keyword search
            # signals a new product intent, not a refinement (e.g. "table" after "mouse").
            inherit_subcategory = not preferences.get("keywords")

            # Safety: only inherit subcategory if the user's message contains a word from it
            # OR the user explicitly set a refinement signal (brand/price/rating/type).
            # Blocks cases where LLM extracts nothing specific but we'd silently reuse
            # the previous subcategory — e.g. "table" after "mouse" inheriting subcategory: mouse.
            if inherit_subcategory and prev_subcategory and new_subcategory is None:
                has_explicit_signal = bool(
                    preferences.get("brand") or preferences.get("type") or
                    preferences.get("max_price") or preferences.get("min_price") or
                    preferences.get("min_rating")
                )
                if not has_explicit_signal:
                    msg_words = set(user_message.lower().split())
                    prev_sub_words = set(prev_subcategory.lower().replace("-", " ").split())
                    if not msg_words & prev_sub_words:
                        inherit_subcategory = False
            preferences = {
                "category": new_category,
                "subcategory": new_subcategory or (prev_subcategory if inherit_subcategory else None),
                "type": preferences.get("type") or previous_prefs.get("type"),
                "brand": preferences.get("brand") or previous_prefs.get("brand"),
                "max_price": preferences.get("max_price") or previous_prefs.get("max_price"),
                "min_price": preferences.get("min_price") or previous_prefs.get("min_price"),
                "min_rating": preferences.get("min_rating") or previous_prefs.get("min_rating"),
                "keywords": preferences.get("keywords") if preferences.get("keywords") else [],
                "unavailable_request": preferences.get("unavailable_request", False),
            }

    logger.info(f"request_id={get_request_id()} | " f"EXTRACTED: {json.dumps(preferences)}")

    return {
        "preferences": preferences,
        "original_preferences": copy.deepcopy(preferences),
        "broaden_attempt": 0,
        "relaxed_filters": [],
        "filters_exhausted": False,
    }


def ask_for_preferences(state: AgentState) -> dict:
    logger.info(f"request_id={get_request_id()} | Asking for preferences")
    return {"final_response": f"What are you looking for? Here's what we carry:\n\n{CATALOG_BLURB}"}


_UNAVAILABLE_SYSTEM_PROMPT = f"""You are a helpful shopping assistant. The user asked for a product we don't carry.
Our catalog:
{CATALOG_BLURB}

Write a 2-sentence response:
1. Acknowledge we don't carry what they asked for (one short sentence).
2. Suggest the single most relevant category or product type from our catalog as a question — e.g. "Would you like to see our smartwatches?" or "Can I help you find a Home & Kitchen appliance instead?". If nothing is relevant, ask if they'd like to browse the full catalog.

Plain text only, no markdown headers, no bullet lists."""


def handle_unavailable_products(state: AgentState) -> dict:
    logger.info(f"request_id={get_request_id()} | Unavailable category requested")
    user_message = state.get("user_message", "")
    query = user_message.lower()

    # Keep targeted redirects only where we have a genuine alternative to point to
    if any(w in query for w in ["phone", "smartphone", "mobile", "iphone", "android", "galaxy"]):
        return {"final_response": "We don't carry smartphones. We do have **phone accessories** — cases, chargers, power banks, and phone stands."}
    if any(w in query for w in ["laptop", "notebook", "macbook", "chromebook"]):
        return {"final_response": "We don't carry laptops. We do have **computer accessories** — mouse, keyboard, monitors, and laptop bags."}
    if any(w in query for w in ["tablet", "ipad", "surface"]):
        return {"final_response": "We don't carry tablets. We do have **computer accessories** — keyboards, mouse, and adapters."}

    # LLM picks the most relevant suggestion from the catalog
    _t0 = time.perf_counter()
    response = llm.invoke([
        SystemMessage(content=_UNAVAILABLE_SYSTEM_PROMPT),
        HumanMessage(content=f'User asked for: "{user_message}"'),
    ])
    logger.info(f"request_id={get_request_id()} | unavailable_suggestion | latency_ms={int((time.perf_counter()-_t0)*1000)}")
    return {"final_response": response.content.strip()}


# ── Product search tool + ToolNode ───────────────────────────────────────────


@tool
def search_product_catalog(
    category: str = None,
    subcategory: str = None,
    brand: str = None,
    max_price: int = None,
    min_price: int = None,
    keywords: list = None,
    product_type: str = None,
) -> str:
    """
    Search the product catalog database.
    Returns up to 10 matching products as a JSON array.
    Use this to find products that match the user's search preferences.
    """
    results = search_products(
        category=category,
        subcategory=subcategory,
        product_type=product_type,
        brand=brand,
        max_price=max_price,
        min_price=min_price,
        keywords=keywords or [],
        limit=10,
    )
    if not results:
        return json.dumps([])
    slim = [
        {
            "product_id": p["product_id"],
            "name": p["name"],
            "price": p["price"],
            "rating": p["rating"],
            "brand": p.get("brand", ""),
            "category": p.get("category"),
            "subcategory": p.get("subcategory"),
        }
        for p in results
    ]
    return json.dumps(slim)


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

    # Guard: if no specificity remains beyond category, treat as exhausted.
    has_specificity = prefs.get("subcategory") or prefs.get("brand") or prefs.get("type") or prefs.get("keywords")
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
    return {
        "final_response": (
            "I couldn't find any products matching your requirements, "
            "even after relaxing several filters. Try a different category or higher budget."
        )
    }


def format_recommendations(state: AgentState) -> dict:
    ranked = state.get("ranked_products") or []
    relaxed = state.get("relaxed_filters") or []
    original_preferences = state.get("original_preferences") or state.get("preferences") or {}

    if not ranked:
        return {"final_response": "I found some products but could not rank them."}

    # Relevance check — only for specific product keywords
    if relaxed and "keywords" in relaxed:
        original_keywords = original_preferences.get("keywords") or []
        if original_keywords:
            # Skip check for generic/category-level words
            GENERIC_WORDS = {
                "items",
                "products",
                "things",
                "stuff",
                "good",
                "best",
                "something",
                "show",
                "me",
                "under",
                "below",
                "above",
                "kitchen",
                "home",
                "baby",
                "sport",
                "sports",
                "toy",
                "toys",
                "clothing",
                "office",
                "art",
                "craft",
                "outdoor",
                "fitness",
                "gear",
                "equipment",
                "accessories",
                "supplies",
                "desk",
                "indoor",
                "kids",
                "children",
                "adult",
                "women",
                "men",
                "girls",
                "boys",
                "need",
                "want",
                "looking",
                "find",
                "care",
                "essentials",
                "essential",
                "basics",
                "basic",
                "type",
                "kind",
                "sort",
                "related",
                "category",
                "range",
            }
            specific_keywords = [kw for kw in original_keywords if kw.lower() not in GENERIC_WORDS]
            if specific_keywords:
                relevant = any(any(kw.lower() in p.get("name", "").lower() for kw in specific_keywords) for p in ranked)
                if not relevant:
                    original_query = " ".join(specific_keywords)
                    _t0 = time.perf_counter()
                    _resp = llm.invoke([
                        SystemMessage(content=_UNAVAILABLE_SYSTEM_PROMPT),
                        HumanMessage(content=f'User asked for: "{original_query}"'),
                    ])
                    logger.info(f"request_id={get_request_id()} | unavailable_suggestion | latency_ms={int((time.perf_counter()-_t0)*1000)}")
                    return {"final_response": _resp.content.strip()}

    lines = []
    if relaxed:
        lines.append(f"Note — I couldn't find an exact match, so I relaxed: {', '.join(relaxed)}.\n")
        lines.append("Here are the closest options:\n")
    else:
        lines.append("Here are my top recommendations for you:\n")

    for i, p in enumerate(ranked[:3], 1):
        reviews = p.get("reviews") or []
        top_review = ""
        if reviews:
            best = max(reviews, key=lambda r: r["rating"])
            top_review = f'"{best["review_text"]}" — {best["reviewer"]}'
        lines.append(f"{i}. {p['name']} by {p['brand']}")
        lines.append(f"   Price: ₹{p['price']} | Rating: {p['rating']}/5")
        if top_review:
            lines.append(f"   {top_review}")
        lines.append("")

    return {"final_response": "\n".join(lines)}


# ROUTING FUNCTIONS (only one of each!)


def route_after_extraction(state: AgentState) -> Literal["search", "ask", "unavailable"]:
    prefs = state.get("preferences") or {}

    if prefs.get("unavailable_request"):
        return "unavailable"

    # Search if there's any signal — category, subcategory, brand, or keywords.
    # Only fall back to "ask" when the LLM found nothing at all (pure vague browse).
    has_signal = bool(
        prefs.get("category") or prefs.get("subcategory") or
        prefs.get("keywords") or prefs.get("brand")
    )
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
        SystemMessage(content="You are a product ranking expert. Return only valid JSON arrays. No explanation."),
        HumanMessage(
            content=(
                f"Rank these products by relevance to the user's request.\n\n"
                f"User request: \"{user_message}\"\n\n"
                f"Products:\n{product_list}\n\n"
                f"Rules:\n"
                f"- For feature requests (e.g. 'best battery', 'calling feature', 'noise cancellation'), "
                f"rank products that match those features first.\n"
                f"- Include any product that is a direct or close match.\n"
                f"- Return [] only if the products are entirely unrelated to the request.\n"
                f"- Otherwise, return ONLY a JSON array of 1-based indices, most relevant first. Max 5 products.\n"
                f"Example: [3, 1, 7, 2, 5]"
            )
        ),
    ]

    _t0 = time.perf_counter()
    response = llm.invoke(messages)
    _latency_s = time.perf_counter() - _t0
    _latency_ms = int(_latency_s * 1000)
    _meta = getattr(response, "response_metadata", {})
    _usage = _meta.get("token_usage", {}) if isinstance(_meta, dict) else {}
    logger.info(
        f"request_id={get_request_id()} | LLM_USAGE | agent=product | node=rank_and_filter"
        f" | prompt_tokens={_usage.get('prompt_tokens', 0)}"
        f" | completion_tokens={_usage.get('completion_tokens', 0)}"
        f" | total_tokens={_usage.get('total_tokens', 0)}"
        f" | latency_ms={_latency_ms}"
    )
    llm_requests_total.labels(agent="product", node="rank_and_filter").inc()
    llm_duration_seconds.labels(agent="product", node="rank_and_filter").observe(_latency_s)
    llm_tokens_total.labels(agent="product", node="rank_and_filter", token_type="prompt").inc(
        _usage.get("prompt_tokens", 0)
    )
    llm_tokens_total.labels(agent="product", node="rank_and_filter", token_type="completion").inc(
        _usage.get("completion_tokens", 0)
    )
    llm_tokens_total.labels(agent="product", node="rank_and_filter", token_type="total").inc(
        _usage.get("total_tokens", 0)
    )

    raw = response.content.strip()

    try:
        match = re.search(r'\[.*?\]', raw, re.DOTALL)
        if match:
            indices = json.loads(match.group())
            if not indices:
                ranked = candidates[:5]
            else:
                seen = set()
                ranked = []
                for idx in indices:
                    if isinstance(idx, int) and 1 <= idx <= len(candidates):
                        p = candidates[idx - 1]
                        if p["product_id"] not in seen:
                            ranked.append(p)
                            seen.add(p["product_id"])
                # pad up to 5 with remaining results
                for p in candidates:
                    if len(ranked) >= 5:
                        break
                    if p["product_id"] not in seen:
                        ranked.append(p)
                        seen.add(p["product_id"])
        else:
            ranked = candidates[:5]
    except Exception as e:
        logger.error(f"request_id={get_request_id()} | rank_and_filter parse error | error={e}")
        ranked = candidates[:5]

    logger.info(f"request_id={get_request_id()} | rank_and_filter | {len(ranked)} products ranked")
    return {"ranked_products": ranked}


def route_after_broaden(state: AgentState) -> Literal["retry_search", "no_results"]:
    return "no_results" if state.get("filters_exhausted") else "retry_search"


# GRAPH


def build_product_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("extract_preferences", extract_preferences)
    graph.add_node("ask_for_preferences", ask_for_preferences)
    graph.add_node("handle_unavailable", handle_unavailable_products)
    graph.add_node("search_products", do_search_products)
    graph.add_node("broaden_search", broaden_search)
    graph.add_node("respond_no_results", respond_no_results)
    graph.add_node("rank_and_filter", rank_and_filter)
    graph.add_node("product_enrichment", product_enrichment_subgraph)
    graph.add_node("format_recommendations", format_recommendations)

    graph.set_entry_point("extract_preferences")

    graph.add_conditional_edges(
        "extract_preferences",
        route_after_extraction,
        {"search": "search_products", "ask": "ask_for_preferences", "unavailable": "handle_unavailable"},
    )

    graph.add_conditional_edges(
        "search_products", route_after_search, {"rank": "rank_and_filter", "broaden": "broaden_search"}
    )

    graph.add_conditional_edges(
        "broaden_search", route_after_broaden, {"retry_search": "search_products", "no_results": "respond_no_results"}
    )

    graph.add_edge("rank_and_filter", "product_enrichment")

    graph.add_edge("product_enrichment", "format_recommendations")
    graph.add_edge("ask_for_preferences", END)
    graph.add_edge("handle_unavailable", END)
    graph.add_edge("respond_no_results", END)
    graph.add_edge("format_recommendations", END)

    return graph.compile()


product_agent_graph = build_product_agent_graph()
