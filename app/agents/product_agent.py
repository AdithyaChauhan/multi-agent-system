import os
import re
import json
import copy
from typing import Literal
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from dotenv import load_dotenv

from app.agents.state import AgentState
from app.agents.product_agent_subgraph import product_enrichment_subgraph
from app.tools.product_tools import search_products
from app.core.logger import get_logger, get_request_id
from app.core.prompt_loader import load_prompt, PROMPT_VERSIONS

load_dotenv()

logger = get_logger("app.agents.product_agent")

llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0,
    api_key=os.getenv("OPENAI_API_KEY")
)

def get_catalog_structure() -> str:
    """Load category/subcategory structure from DB dynamically"""
    from app.db.database import SessionLocal
    from app.models.product import Product
    from sqlalchemy import distinct

    db = SessionLocal()
    try:
        rows = db.query(
            Product.category,
            Product.subcategory
        ).distinct().filter(
            Product.category.isnot(None)
        ).order_by(Product.category, Product.subcategory).all()

        structure = {}
        for category, subcategory in rows:
            if category not in structure:
                structure[category] = set()
            if subcategory:
                structure[category].add(subcategory)

        lines = []
        for cat, subs in sorted(structure.items()):
            lines.append(f"{cat}:")
            for sub in sorted(subs):
                lines.append(f"  - {sub}")

        return "\n".join(lines)
    finally:
        db.close()

CATEGORY_DESCRIPTIONS = {
    "Electronics": "TVs, headphones, smartwatches, cameras",
    "Computers & Accessories": "Cables, chargers, keyboards, mice",
    "Home & Kitchen": "Appliances, fans, air purifiers, room heaters",
    "Office Products": "Stationery, paper products",
}

def get_catalog_summary() -> str:
    from app.db.database import SessionLocal
    from app.models.product import Product
    from sqlalchemy import func
    db = SessionLocal()
    try:
        rows = db.query(
            Product.category,
            func.count(Product.id).label("count")
        ).filter(
            Product.category.isnot(None)
        ).group_by(Product.category).having(
            func.count(Product.id) >= 10
        ).order_by(func.count(Product.id).desc()).all()
        lines = []
        for cat, cnt in rows:
            desc = CATEGORY_DESCRIPTIONS.get(cat, "")
            suffix = f" — {desc}" if desc else ""
            lines.append(f"• {cat} ({cnt} products){suffix}")
        return "\n".join(lines)
    finally:
        db.close()

# Load once at startup
CATALOG_STRUCTURE = get_catalog_structure()
CATALOG_SUMMARY = get_catalog_summary()

# Relaxation order: keep the product category as long as possible.
# Relax brand first (try any brand), then specific features/keywords,
# then type variant (e.g. neckband → any headphone), then price,
# and only as a last resort drop the subcategory.
RELAXATION_ORDER = [
    "brand",
    "keywords",
    "type",
    "price_increase",
    "subcategory",
]

EXTRACTION_SYSTEM_PROMPT = """Extract product search preferences. Return JSON only, omit null/empty fields.

Catalog (EXACT subcategory names):
Electronics: headphones(neckband|tws earbuds|wired earphones|over-ear) · speakers(bluetooth speaker|soundbar|home theatre) · tv(smart tv) · smartwatch · tv remote · set top box · projector · streaming device · Mobiles & Accessories · GeneralPurposeBatteries & BatteryChargers
Computers & Accessories: mouse · keyboard · cable · adapter · drawing tablet · external hdd · external ssd · pen drive · usb hub · webcam · router · wifi adapter · wifi range extender · laptop bag · monitor stand · mouse pad · gamepad · microphone · screen protector · speakers · printer · ink cartridge · monitor · ups
Home & Kitchen(type=null): iron · mixer grinder · blender · electric kettle · air fryer · vacuum cleaner · induction · sandwich maker · toaster · rice cooker · juicer · egg boiler · water purifier · water filter · frother · chopper · hand mixer · garment steamer · kitchen scale · lint remover · coffee maker · room heater · ceiling fan · air purifier · water heater · pedestal fan · humidifier · air conditioner · HomeStorage & Organization
Office Products: OfficePaperProducts · OfficeElectronics

Output fields: category, subcategory, type, brand, max_price, min_price, keywords(list), unavailable_request(bool)

Rules:
- Electronics: subcategory=product class, type=variant from parentheses above
- Computers: subcategory=specific product; mouse/keyboard type: wired|wireless|gaming|mechanical; wifi dongles→wifi adapter; laptop stands/desks/cooling pads→monitor stand; USB chargers/dongles→adapter; external drives→external hdd; flash drives→pen drive
- Home & Kitchen: subcategory=appliance name from list above, type=null
- keywords: features NOT implied by subcategory/type (e.g. "calling", "noise cancellation", "HDMI"). Normalize: blutooth→bluetooth, speker→speaker, mice→mouse
- unavailable_request=true for: laptops, desktop PCs, tablets(devices), smartphones(devices), clothing, shoes, furniture, food. Price/brand/feature alone NEVER makes unavailable.

Follow-up rules:
- "what about [Brand]" → keep EXACT prior subcategory, set brand only — never infer subcategory from brand
- "under [price]"/"cheaper"/"ones with [X]" → keep all prior fields, change only relevant one, unavailable_request=false
- New product mentioned → extract fresh

Examples:
"wireless mouse" → {"category":"Computers & Accessories","subcategory":"mouse","keywords":["wireless"],"unavailable_request":false}
"neckband under 2000" → {"category":"Electronics","subcategory":"headphones","type":"neckband","max_price":2000,"unavailable_request":false}
"Samsung smart TV under 15000" → {"category":"Electronics","subcategory":"tv","type":"smart tv","brand":"Samsung","max_price":15000,"unavailable_request":false}
"mixer grinder under 3000" → {"category":"Home & Kitchen","subcategory":"mixer grinder","max_price":3000,"unavailable_request":false}
"laptop under 50000" → {"keywords":["laptop"],"unavailable_request":true}

History: "User: mixer grinder under 2000" | Message: "what about Bajaj"
→ {"category":"Home & Kitchen","subcategory":"mixer grinder","brand":"Bajaj","max_price":2000,"unavailable_request":false}

History: "User: room heater under 2000" | Message: "what about Bajaj"
→ {"category":"Home & Kitchen","subcategory":"room heater","brand":"Bajaj","max_price":2000,"unavailable_request":false}

History: "User: boAt headphones under 1500" | Message: "under 1000"
→ {"category":"Electronics","subcategory":"headphones","brand":"boAt","max_price":1000,"unavailable_request":false}

Respond ONLY with valid JSON."""


def _find_product_anchor(conversation_history: list, recent_user_texts: set) -> str | None:
    """
    Scan full conversation history for the most recent user message that preceded
    a product recommendations response, but has since scrolled out of the [-6:] window.
    Returns that user message so it can be injected as context for the extraction LLM.
    """
    for i in range(len(conversation_history) - 1, -1, -1):
        msg = conversation_history[i]
        if msg["role"] != "assistant":
            continue
        content = msg["content"]
        if not any(phrase in content for phrase in (
            "Here are my top recommendations",
            "I could not find an exact match",
            "Here are the closest options",
        )):
            continue
        # Find the user message immediately before this assistant turn
        for j in range(i - 1, -1, -1):
            if conversation_history[j]["role"] == "user":
                user_msg = conversation_history[j]["content"]
                if user_msg not in recent_user_texts:
                    return user_msg
                # Already in window — no need to inject
                return None
    return None


def extract_preferences(state: AgentState) -> dict:
    """LLM node — extracts structured preferences from user message."""
    user_message = state.get("user_message", "")
    conversation_history = state.get("conversation_history", [])

    # Keep history so the LLM can resolve follow-up references ("ones", "what about X").
    # For assistant replies: strip the numbered product list, keep only the intro/outcome lines
    # (e.g. "Here are my top recommendations for you:"). Arbitrary char-truncation cuts product
    # names mid-word, leaving misleading keywords like "Bluetooth Call" from a watch name that
    # cause the LLM to infer the wrong subcategory on the next turn.
    history_context = ""
    if conversation_history:
        recent = conversation_history[-6:]
        recent_user_texts = {m["content"] for m in recent if m["role"] == "user"}

        lines = []
        for msg in recent:
            if msg["role"] == "assistant":
                intro = []
                for line in msg["content"].split("\n"):
                    stripped = line.strip()
                    if stripped and (
                        (stripped[0].isdigit() and ". " in stripped)
                        or stripped.startswith("•")
                    ):
                        break
                    intro.append(line)
                content = "\n".join(intro).strip() or msg["content"][:80]
            else:
                content = msg["content"]
            lines.append(f"{msg['role'].title()}: {content}")
        history_context = "\n".join(lines)

        # Anchor: when the original product-establishing message has scrolled past
        # the [-6:] window (e.g. 4+ consecutive price refinements), the LLM loses
        # the subcategory entirely. Scan the full history for the last user message
        # that was followed by a product recommendations response and inject it.
        anchor = _find_product_anchor(conversation_history, recent_user_texts)
        if anchor:
            history_context = f"User (prior search): {anchor}\n\n" + history_context

    if history_context:
        full_prompt = f"Recent conversation:\n{history_context}\n\nCurrent message: {user_message}"
    else:
        full_prompt = user_message

    version = PROMPT_VERSIONS.get("product-extraction-prompt", "latest")
    system_prompt, commit_hash = load_prompt("product-extraction-prompt", version)
    if not system_prompt:
        system_prompt = EXTRACTION_SYSTEM_PROMPT
        commit_hash = "fallback"

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=full_prompt),
    ]

    response = llm.invoke(
        messages,
        config={"metadata": {"prompt_name": "product-extraction-prompt", "prompt_version": commit_hash}}
    )
    raw = response.content.strip()

    if raw.startswith("```"):
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        preferences = json.loads(raw)
        # LLM occasionally returns the string "null" instead of JSON null
        preferences = {k: (None if v == "null" or v == "None" else v) for k, v in preferences.items()}
    except json.JSONDecodeError as e:
        logger.error(
            f"request_id={get_request_id()} | "
            f"Preference parse error | raw={raw} | error={str(e)}"
        )
        preferences = {"category": None, "keywords": [], "unavailable_request": False}

    # Safety: a pure price refinement ("under 1000", "cheaper") with no category
    # extracted should never be marked unavailable — the LLM occasionally does this
    # when conversation context includes a support turn before the product turn.
    # Clear unavailable_request so routing falls through to "ask" at worst.
    if (preferences.get("unavailable_request")
            and not preferences.get("category")
            and not preferences.get("subcategory")
            and preferences.get("max_price") is not None
            and conversation_history):
        preferences["unavailable_request"] = False
        logger.info(f"request_id={get_request_id()} | Cleared false-positive unavailable_request on price refinement")

    # Merge with previous preferences — preserve context across turns
    previous_prefs = state.get("preferences") or {}
    if previous_prefs and not preferences.get("unavailable_request"):
        new_category = preferences.get("category") or previous_prefs.get("category")
        prev_category = previous_prefs.get("category")
        prev_subcategory = previous_prefs.get("subcategory")
        new_subcategory = preferences.get("subcategory")

        # Subcategory persistence: keep the active subcategory unless the user's current
        # message explicitly names a new product type. Prevents brand names that span
        # multiple categories (e.g. "Noise" makes both watches and earbuds) from
        # flipping subcategory on a message like "what about Noise".
        subcategory_changed = bool(
            prev_subcategory
            and new_subcategory
            and new_subcategory != prev_subcategory
        )
        if subcategory_changed:
            msg_lower = user_message.lower()
            subcat_words = [
                w for w in new_subcategory.lower().replace("-", " ").split()
                if len(w) > 3
            ]
            explicitly_mentioned = any(w in msg_lower for w in subcat_words)
            if not explicitly_mentioned:
                new_subcategory = prev_subcategory
                subcategory_changed = False

        # When subcategory genuinely changes, drop type and keywords from the old
        # product class entirely — they described a different product type.
        # When subcategory is stable, carry type and keywords forward across turns.
        if subcategory_changed:
            carried_type     = preferences.get("type")
            carried_keywords = preferences.get("keywords") or []
        else:
            carried_type     = preferences.get("type") or previous_prefs.get("type")
            carried_keywords = (
                preferences.get("keywords") or previous_prefs.get("keywords") or []
            )

        preferences = {
            "category":    new_category,
            "subcategory": new_subcategory or prev_subcategory,
            "type":        carried_type,
            "brand":       preferences.get("brand"),
            "max_price":   preferences.get("max_price")   or previous_prefs.get("max_price"),
            "min_price":   preferences.get("min_price")   or previous_prefs.get("min_price"),
            "keywords":    carried_keywords,
            "unavailable_request": preferences.get("unavailable_request", False),
        }

    # Remove null/empty fields — downstream code uses .get() so missing == None.
    # Keeps state small and LangSmith traces readable.
    preferences = {k: v for k, v in preferences.items()
                   if v is not None and v != [] and v != ""}

    logger.info(
        f"request_id={get_request_id()} | "
        f"EXTRACTED: {json.dumps(preferences)}"
    )

    return {
        "preferences": preferences,
        "original_preferences": copy.deepcopy(preferences),
        "broaden_attempt": 0,
        "relaxed_filters": [],
        "filters_exhausted": False,
    }


def ask_for_preferences(state: AgentState) -> dict:
    logger.info(f"request_id={get_request_id()} | Asking for preferences")
    return {
        "final_response": f"What are you looking for? Here's what we carry:\n\n{CATALOG_SUMMARY}"
    }


def handle_unavailable_products(state: AgentState) -> dict:
    user_message = state.get("user_message", "")
    logger.info(f"request_id={get_request_id()} | Unavailable category requested")
    
    return {
        "final_response": (
            f"I'm sorry, we don't carry that item in our catalog. "
            f"However, we have a great selection in other categories:\n\n"
            f"{CATALOG_SUMMARY}\n\n"
            f"Would you like to explore any of these categories?"
        )
    }


def do_search_products(state: AgentState) -> dict:
    prefs = state.get("preferences") or {}
    category = prefs.get("category")
    subcategory = prefs.get("subcategory")
    
    logger.info(
        f"request_id={get_request_id()} | "
        f"Searching | category={category} | subcategory={subcategory}"
    )

    keywords = prefs.get("keywords") or []
    
    results = search_products(
        category=category,
        subcategory=subcategory,
        product_type=prefs.get("type"),
        brand=prefs.get("brand"),
        max_price=prefs.get("max_price"),
        min_price=prefs.get("min_price"),
        keywords=keywords,
        limit=10,
    )

    logger.info(f"request_id={get_request_id()} | Found {len(results)} products")
    return {"search_results": results}


def broaden_search(state: AgentState) -> dict:
    prefs = (state.get("preferences") or {}).copy()
    attempt = state.get("broaden_attempt", 0)
    relaxed = list(state.get("relaxed_filters") or [])

    if attempt >= len(RELAXATION_ORDER):
        return {"broaden_attempt": attempt + 1, "filters_exhausted": True}

    filter_to_relax = RELAXATION_ORDER[attempt]

    if filter_to_relax == "price_increase":
        if prefs.get("max_price"):
            old_price = prefs["max_price"]
            prefs["max_price"] = int(old_price * 1.25)
            relaxed.append(f"price increased from {old_price} to {prefs['max_price']}")
        else:
            return broaden_search({**state, "broaden_attempt": attempt + 1})
    else:
        if prefs.get(filter_to_relax):
            relaxed.append(filter_to_relax)
            prefs[filter_to_relax] = None
        else:
            return broaden_search({**state, "broaden_attempt": attempt + 1})

    # Guard: if after relaxation no specificity remains beyond category alone,
    # the search would return anything in the category — treat as exhausted.
    has_specificity = (
        prefs.get("subcategory") or
        prefs.get("brand") or
        prefs.get("type") or
        prefs.get("keywords")
    )
    if not has_specificity:
        return {"broaden_attempt": attempt + 1, "filters_exhausted": True}

    return {
        "preferences": prefs,
        "broaden_attempt": attempt + 1,
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
                "items", "products", "things", "stuff", "good", "best",
                "something", "show", "me", "under", "below", "above",
                "kitchen", "home", "baby", "sport", "sports", "toy", "toys",
                "clothing", "office", "art", "craft", "outdoor", "fitness",
                "gear", "equipment", "accessories", "supplies", "desk",
                "indoor", "kids", "children", "adult", "women",
                "men", "girls", "boys", "need", "want", "looking", "find",
                "care", "essentials", "essential", "basics", "basic",
                "type", "kind", "sort", "related", "category", "range"
            }
            specific_keywords = [
                kw for kw in original_keywords
                if kw.lower() not in GENERIC_WORDS
            ]
            if specific_keywords:
                relevant = any(
                    any(kw.lower() in p.get("name", "").lower() for kw in specific_keywords)
                    for p in ranked
                )
                if not relevant:
                    original_query = " ".join(specific_keywords)
                    return {
                        "final_response": (
                            f"I couldn't find '{original_query}' in our catalog. "
                            f"Our inventory may not carry this specific item.\n\n"
                            f"We carry:\n{CATALOG_SUMMARY}\n\n"
                            f"Would you like to explore any of these categories?"
                        )
                    }
                

    lines = []
    if relaxed:
        lines.append(f"Note — I could not find an exact match, so I relaxed: {', '.join(relaxed)}.\n")
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
    
    if not prefs.get("category"):
        return "ask"
    
    return "search"


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
    product_list = "\n".join([
        f"{i+1}. {p['name'][:60]} | ₹{p['price']} | {p['rating']}★ | {p.get('brand', '')}"
        for i, p in enumerate(candidates)
    ])

    messages = [
        SystemMessage(content="Rank products by relevance. Return a JSON array of 1-based indices only."),
        HumanMessage(content=(
            f"Request: \"{user_message}\"\n\n"
            f"Products:\n{product_list}\n\n"
            f"Return indices most-relevant-first, max 5. [] only if entirely unrelated.\n"
            f"Example: [3, 1, 2]"
        )),
    ]

    response = llm.invoke(messages)
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
        {"search": "search_products", "ask": "ask_for_preferences", "unavailable": "handle_unavailable"}
    )

    graph.add_conditional_edges(
        "search_products",
        route_after_search,
        {"rank": "rank_and_filter", "broaden": "broaden_search"}
    )

    graph.add_conditional_edges(
        "broaden_search",
        route_after_broaden,
        {"retry_search": "search_products", "no_results": "respond_no_results"}
    )

    graph.add_conditional_edges(
        "rank_and_filter",
        lambda s: "format" if not s.get("ranked_products") else "enrich",
        {"enrich": "product_enrichment", "format": "format_recommendations"}
    )
    graph.add_edge("product_enrichment", "format_recommendations")
    graph.add_edge("ask_for_preferences", END)
    graph.add_edge("handle_unavailable", END)
    graph.add_edge("respond_no_results", END)
    graph.add_edge("format_recommendations", END)

    return graph.compile()


product_agent_graph = build_product_agent_graph()