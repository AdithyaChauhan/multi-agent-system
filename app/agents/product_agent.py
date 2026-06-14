import os
import re
import json
import copy
import time
import threading
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
from app.core.prompt_loader import load_prompt, PROMPT_VERSIONS

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


_CATALOG_CACHE: dict = {"value": "", "ts": 0.0}
_CATALOG_LOCK = threading.Lock()
_CATALOG_TTL = 300  # seconds


def _build_prompt_catalog_from_db() -> str:
    """Query DB for distinct served subcategories and format as extraction catalog string."""
    from app.db.database import SessionLocal
    from app.models.product import Product

    db = SessionLocal()
    try:
        rows = (
            db.query(Product.category, Product.subcategory)
            .filter(
                Product.category.in_(SERVED_CATEGORIES),
                Product.subcategory.isnot(None),
                Product.subcategory.notin_(BLURB_EXCLUDED_SUBCATEGORIES),
            )
            .distinct()
            .order_by(Product.category, Product.subcategory)
            .all()
        )
        cat_map: dict[str, list[str]] = {}
        for cat, sub in rows:
            cat_map.setdefault(cat, []).append(sub)

        return "\n".join(
            f"{cat}: {' | '.join(subs)}" for cat, subs in sorted(cat_map.items())
        )
    except Exception:
        return ""
    finally:
        db.close()


def get_prompt_catalog() -> str:
    """Return cached catalog string, refreshing from DB if older than TTL."""
    now = time.time()
    with _CATALOG_LOCK:
        if now - _CATALOG_CACHE["ts"] < _CATALOG_TTL and _CATALOG_CACHE["value"]:
            return _CATALOG_CACHE["value"]
        fresh = _build_prompt_catalog_from_db()
        if fresh:
            _CATALOG_CACHE["value"] = fresh
            _CATALOG_CACHE["ts"] = now
        return _CATALOG_CACHE["value"]


# Initialise cache at startup so the first request doesn't pay the DB round-trip.
PROMPT_CATALOG = get_prompt_catalog()

# All catalog subcategories, longest-first so multi-word names ("usb hub", "air fryer")
# match before single-word prefixes ("hub", "fryer").
def _build_all_subcategories() -> list[str]:
    catalog = get_prompt_catalog()
    return sorted(
        {
            s.strip()
            for line in catalog.split("\n")
            for part in (line.split(":", 1)[1:] or [""])
            for s in part.split("|")
            if s.strip()
        },
        key=len,
        reverse=True,
    )


_ALL_SUBCATEGORIES: list[str] = _build_all_subcategories()


def _subcategory_in_message(message: str) -> str | None:
    """Return the first catalog subcategory found verbatim in message, else None."""
    m = message.lower()
    for sub in _ALL_SUBCATEGORIES:
        if sub in m:
            return sub
    return None


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

def _extraction_system_prompt() -> str:
    return f"""Extract product search preferences. Return JSON only.

Catalog:
{get_prompt_catalog()}

Schema: {{"category":str|null,"subcategory":str|null,"type":str|null,"brand":str|null,"max_price":int|null,"min_price":int|null,"min_rating":float|null,"keywords":[str],"unavailable_request":bool}}

Types (Electronics only; null if unspecified):
headphones: neckband|tws earbuds|wired earphones|over-ear headphones
speakers: bluetooth speaker|soundbar|home theatre  tv: smart tv
mouse/keyboard: wired|wireless|gaming|mechanical|bluetooth
cable/adapter/H&K: type=null, use keywords for HDMI/USB-C/lightning specifics

Rules:
- Exact catalog subcategory names only
- mice→mouse; earbuds/earphones→headphones+type; telly→tv; adaptor→adapter; geyser→water heater; AC→air conditioner
- pencil/pen/highlighter/eraser/ruler/marker/sketch pad→stationery; paintbrush/canvas/palette→art supplies
- phone/mobile charger→sub:charger, keywords:["USB"]
- keywords: features beyond subcategory/type (calling, noise cancellation, 4K, wireless)
- best/highly/top rated→min_rating:4.0; "4.5 stars"→4.5; "4 stars and above"→4.0; null otherwise
- Category-only browse: subcategory null, keywords []
- Vague browse (show products/what do you have): category null, unavailable_request false
- unavailable_request true ONLY for absent types (laptops, phones, tablets, clothing, food, furniture) — not for brands, specs, or features
- JSON null only, never string "null"
- Need/goal queries: when the user describes a problem, activity, or desired outcome rather than naming a specific product, infer the catalog subcategory that best enables it. This applies to multi-word intent phrases ("something to keep warm", "for the gym"), NOT to bare single nouns that are product names ("table", "chair", "book") — treat those as direct product searches.
- If the user names a product type not in the catalog (furniture, food, clothing, books, toys), set unavailable_request: true.

Examples:
"mixer grinder under 3000" → {{"category": "Home & Kitchen", "subcategory": "mixer grinder", "type": null, "brand": null, "max_price": 3000, "min_price": null, "min_rating": null, "keywords": [], "unavailable_request": false}}
"best rated JBL bluetooth speaker under 2000" → {{"category": "Electronics", "subcategory": "speakers", "type": "bluetooth speaker", "brand": "JBL", "max_price": 2000, "min_price": null, "min_rating": 4.0, "keywords": [], "unavailable_request": false}}
"top rated neckband under 2000" → {{"category": "Electronics", "subcategory": "headphones", "type": "neckband", "brand": null, "max_price": 2000, "min_price": null, "min_rating": 4.0, "keywords": [], "unavailable_request": false}}
"wireless mouse" → {{"category": "Computers & Accessories", "subcategory": "mouse", "type": null, "brand": null, "max_price": null, "min_price": null, "min_rating": null, "keywords": ["wireless"], "unavailable_request": false}}
"4.5 star and above air fryer" → {{"category": "Home & Kitchen", "subcategory": "air fryer", "type": null, "brand": null, "max_price": null, "min_price": null, "min_rating": 4.5, "keywords": [], "unavailable_request": false}}
"laptop under 50000" → {{"category": null, "subcategory": null, "type": null, "brand": null, "max_price": 50000, "min_price": null, "min_rating": null, "keywords": ["laptop"], "unavailable_request": true}}
"geyser under 5000" → {{"category": "Home & Kitchen", "subcategory": "water heater", "type": null, "brand": null, "max_price": 5000, "min_price": null, "min_rating": null, "keywords": [], "unavailable_request": false}}
"4K monitor" → {{"category": "Computers & Accessories", "subcategory": "monitor", "type": null, "brand": null, "max_price": null, "min_price": null, "min_rating": null, "keywords": ["4K"], "unavailable_request": false}}
"USB hub with ethernet" → {{"category": "Computers & Accessories", "subcategory": "usb hub", "type": null, "brand": null, "max_price": null, "min_price": null, "min_rating": null, "keywords": ["ethernet"], "unavailable_request": false}}
"Sony headphones under 5000" → {{"category": "Electronics", "subcategory": "headphones", "type": null, "brand": "Sony", "max_price": 5000, "min_price": null, "min_rating": null, "keywords": [], "unavailable_request": false}}
"affordable headphones" → {{"category": "Electronics", "subcategory": "headphones", "type": null, "brand": null, "max_price": null, "min_price": null, "min_rating": null, "keywords": [], "unavailable_request": false}}

Respond ONLY with valid JSON."""


def extract_preferences(state: AgentState) -> dict:
    """LLM node — extracts structured preferences from user message."""
    user_message = state.get("user_message", "")

    # Extract from the current message only — no history passed to LLM.
    # Context preservation across turns is handled by the Python merge logic below.
    full_prompt = user_message

    _ext_prompt = _extraction_system_prompt()
    _ext_hash = "hardcoded"

    messages = [
        SystemMessage(content=_ext_prompt),
        HumanMessage(content=full_prompt),
    ]

    _t0 = time.perf_counter()
    response = llm.invoke(
        messages,
        config={"metadata": {"prompt_name": "product-extraction-prompt", "prompt_version": _ext_hash}},
    )
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

    # Subcategory guard: if the LLM still flags unavailable_request but the user's
    # message contains a known catalog subcategory, the product is in scope — specs
    # like "4K" or "ethernet" should not trigger unavailable.
    if preferences.get("unavailable_request"):
        found_sub = _subcategory_in_message(user_message)
        if found_sub:
            preferences["unavailable_request"] = False
            if not preferences.get("subcategory"):
                preferences["subcategory"] = found_sub

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
        category_changed = new_category is not None and prev_category is not None and new_category != prev_category

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

        # Price-comparative refinement ("cheaper", "less expensive", etc.) returns nothing from
        # the extraction LLM because there's no specific number. Don't reset context for these —
        # reduce the previous max_price by 30% so the search narrows within the same subcategory.
        _price_down_words = {"cheaper", "less expensive", "lower price", "more affordable", "budget option", "budget"}
        _user_msg_lower = state.get("user_message", "").lower()
        if vague_browse and prev_subcategory and any(w in _user_msg_lower for w in _price_down_words):
            vague_browse = False
            preferences["category"] = prev_category
            preferences["subcategory"] = prev_subcategory
            if previous_prefs.get("max_price"):
                preferences["max_price"] = int(previous_prefs["max_price"] * 0.7)

        # New specific product after a keyword/feature-only turn that stored no subcategory.
        # e.g. "with calling feature" stores subcategory=null; then "calculator" is a new search.
        new_specific_product = bool(new_subcategory and not prev_subcategory)

        if vague_browse:
            # Wipe all accumulated context — show the catalog and let the user start fresh.
            preferences = {
                "category": None,
                "subcategory": None,
                "type": None,
                "brand": None,
                "max_price": None,
                "min_price": None,
                "min_rating": None,
                "keywords": [],
                "unavailable_request": False,
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
                    preferences.get("brand")
                    or preferences.get("type")
                    or preferences.get("max_price")
                    or preferences.get("min_price")
                    or preferences.get("min_rating")
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
        return {
            "final_response": "We don't carry smartphones. We do have **phone accessories** — cases, chargers, power banks, and phone stands."
        }
    if any(w in query for w in ["laptop", "notebook", "macbook", "chromebook"]):
        return {
            "final_response": "We don't carry laptops. We do have **computer accessories** — mouse, keyboard, monitors, and laptop bags."
        }
    if any(w in query for w in ["tablet", "ipad", "surface"]):
        return {
            "final_response": "We don't carry tablets. We do have **computer accessories** — keyboards, mouse, and adapters."
        }

    # LLM picks the most relevant suggestion from the catalog
    _t0 = time.perf_counter()
    response = llm.invoke(
        [
            SystemMessage(content=_UNAVAILABLE_SYSTEM_PROMPT),
            HumanMessage(content=f'User asked for: "{user_message}"'),
        ]
    )
    logger.info(
        f"request_id={get_request_id()} | unavailable_suggestion | latency_ms={int((time.perf_counter()-_t0)*1000)}"
    )
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

    # Category alone is enough to fetch a candidate set for the ranker.
    has_specificity = prefs.get("category") or prefs.get("subcategory") or prefs.get("brand") or prefs.get("type") or prefs.get("keywords")
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

    top3 = ranked[:3]
    all_maybe = all(p.get("llm_tier", 0) == 1 for p in top3)

    lines = []
    if relaxed:
        lines.append(f"Note — I couldn't find an exact match, so I relaxed: {', '.join(relaxed)}.\n")
        lines.append("Here are the closest options:\n")
    elif all_maybe:
        lines.append("I couldn't find products that exactly match your request, but here are some related options — let me know if any of these work for you or if you'd like me to look for something else:\n")
    else:
        lines.append("Here are my top recommendations for you:\n")

    for i, p in enumerate(top3, 1):
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
    has_signal = bool(prefs.get("category") or prefs.get("subcategory") or prefs.get("keywords") or prefs.get("brand"))
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
        SystemMessage(content="You are a product relevance classifier. Return only valid JSON. No explanation."),
        HumanMessage(
            content=(
                f"Classify each product by how well it matches the user's request.\n\n"
                f"User request: \"{user_message}\"\n\n"
                f"Products:\n{product_list}\n\n"
                f"For each product, assign:\n"
                f"- \"relevant\": directly addresses the user's need\n"
                f"- \"maybe\": right product type but missing a requested spec, feature, or brand\n"
                f"- \"no\": wrong product category — unrelated to what was asked\n\n"
                f"Return ONLY a JSON object with three lists of 1-based indices:\n"
                f'Example: {{"relevant": [3, 7], "maybe": [1, 5], "no": [2, 4, 6, 8]}}'
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
    logger.info(f"request_id={get_request_id()} | ranker_raw={raw!r} | candidates={len(candidates)}")

    try:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        parsed = json.loads(match.group()) if match else {}
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

    logger.info(f"request_id={get_request_id()} | rank_and_filter | {len(ranked)} products (tier 0: {sum(1 for p in ranked if p.get('llm_tier')==0)}, tier 1: {sum(1 for p in ranked if p.get('llm_tier')==1)})")
    return {"ranked_products": ranked}


def route_after_rank(state: AgentState) -> Literal["enrich", "broaden"]:
    ranked = state.get("ranked_products") or []
    return "enrich" if ranked else "broaden"


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

    graph.add_conditional_edges(
        "rank_and_filter", route_after_rank, {"enrich": "product_enrichment", "broaden": "broaden_search"}
    )

    graph.add_edge("product_enrichment", "format_recommendations")
    graph.add_edge("ask_for_preferences", END)
    graph.add_edge("handle_unavailable", END)
    graph.add_edge("respond_no_results", END)
    graph.add_edge("format_recommendations", END)

    return graph.compile()


product_agent_graph = build_product_agent_graph()
