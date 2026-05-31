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

# Load once at startup
CATALOG_STRUCTURE = get_catalog_structure()

# Generic relaxation order for all categories
RELAXATION_ORDER = [
    "type",
    "subcategory",
    "brand",
    "price_increase",
    "keywords",
]

EXTRACTION_SYSTEM_PROMPT = """Extract product search preferences. Return JSON only.

Catalog (use exact subcategory names):
Electronics: HomeTheater,TV & Video | Headphones,Earbuds & Accessories | WearableTechnology | HomeAudio | Mobiles & Accessories | GeneralPurposeBatteries & BatteryChargers
Computers & Accessories: Accessories & Peripherals | NetworkingDevices | ExternalDevices & DataStorage | Monitors | Printers,Inks & Accessories
Home & Kitchen (subcategory = the appliance, type = null): iron | mixer grinder | blender | electric kettle | air fryer | vacuum cleaner | induction | sandwich maker | toaster | rice cooker | juicer | egg boiler | water purifier | water filter | frother | chopper | hand mixer | garment steamer | kitchen scale | lint remover | coffee maker | room heater | ceiling fan | air purifier | water heater | pedestal fan | humidifier | air conditioner | HomeStorage & Organization
Office Products (no subcategory)

Output schema: {"category": str|null, "subcategory": str|null, "type": str|null, "brand": str|null, "max_price": int|null, "min_price": int|null, "keywords": [str], "unavailable_request": bool}

Rules:
- Use exact subcategory name from the list above
- For Home & Kitchen: subcategory = specific appliance from list, type = null
- For Electronics: type = specific product (smart tv, tws earbuds, neckband, over-ear headphones, wired earphones, smartwatch, bluetooth speaker, soundbar, projector, streaming device, router, pen drive, keyboard, mouse, webcam)
- Bluetooth/portable speakers, soundbars → HomeAudio (NOT Headphones,Earbuds & Accessories)
- keywords: only product-specific features not covered by subcategory/type (e.g. "wireless", "calling", "noise cancellation")
- wired/wireless is a keyword for headphones; normalize: mice→mouse, telly→TV, adaptor→adapter
- Never output string "null" — use JSON null
- "notebook" or "notebooks" alone = paper/stationery notebooks → category: "Office Products", subcategory: null, unavailable_request: false. Only "laptop" or "laptop notebook" = unavailable.
- Indian colloquial terms: "geyser"/"geysers" → subcategory: "water heater"; "AC"/"ACs" → subcategory: "air conditioner"; "cooler" → subcategory: "air purifier" (if no room cooler subcategory exists)
- Vague browsing ("give me a list", "show me products", "product list", "browse", "what do you have", "show everything") → category: null, subcategory: null, keywords: [], unavailable_request: false
- unavailable_request TRUE: laptops, desktop PCs, tablets (devices), smartphones (devices), clothing, shoes, furniture, food, books, novels, magazines, toys, sports equipment, automotive parts, garden supplies, pet supplies, beauty products, medicines
- unavailable_request FALSE: all appliances, accessories, peripherals, fans, air purifiers, geysers, paper notebooks, stationery

Examples:
"mixer grinder under 3000" → {"category": "Home & Kitchen", "subcategory": "mixer grinder", "type": null, "brand": null, "max_price": 3000, "min_price": null, "keywords": [], "unavailable_request": false}
"air purifier under 10000" → {"category": "Home & Kitchen", "subcategory": "air purifier", "type": null, "brand": null, "max_price": 10000, "min_price": null, "keywords": [], "unavailable_request": false}
"JBL bluetooth speaker under 2000" → {"category": "Electronics", "subcategory": "HomeAudio", "type": null, "brand": "JBL", "max_price": 2000, "min_price": null, "keywords": [], "unavailable_request": false}
"laptop under 50000" → {"category": null, "subcategory": null, "type": null, "brand": null, "max_price": 50000, "min_price": null, "keywords": ["laptop"], "unavailable_request": true}
"notebooks" → {"category": "Office Products", "subcategory": null, "type": null, "brand": null, "max_price": null, "min_price": null, "keywords": [], "unavailable_request": false}
"books" → {"category": null, "subcategory": null, "type": null, "brand": null, "max_price": null, "min_price": null, "keywords": ["books"], "unavailable_request": true}
"geyser under 5000" → {"category": "Home & Kitchen", "subcategory": "water heater", "type": null, "brand": null, "max_price": 5000, "min_price": null, "keywords": [], "unavailable_request": false}
"AC under 30000" → {"category": "Home & Kitchen", "subcategory": "air conditioner", "type": null, "brand": null, "max_price": 30000, "min_price": null, "keywords": [], "unavailable_request": false}
"give me product list" → {"category": null, "subcategory": null, "type": null, "brand": null, "max_price": null, "min_price": null, "keywords": [], "unavailable_request": false}
"show me everything" → {"category": null, "subcategory": null, "type": null, "brand": null, "max_price": null, "min_price": null, "keywords": [], "unavailable_request": false}

Respond ONLY with valid JSON."""


def extract_preferences(state: AgentState) -> dict:
    """LLM node — extracts structured preferences from user message."""
    user_message = state.get("user_message", "")
    conversation_history = state.get("conversation_history", [])

    # Build context from history for follow-up understanding
    history_context = ""
    if conversation_history:
        recent = conversation_history[-4:]
        history_context = "\n".join([
            f"{msg['role'].title()}: {msg['content']}"
            for msg in recent
        ])

    if history_context:
        full_prompt = (
            f"Recent conversation:\n{history_context}\n\n"
            f"Current message: {user_message}\n\n"
            f"Follow-up rules:\n"
            f"- If the user is refining the SAME product (e.g. changing price, brand, or adding a feature), preserve subcategory from history.\n"
            f"- If the user mentions a DIFFERENT product type, extract fresh preferences — do NOT carry over subcategory from history.\n"
            f"CRITICAL: When user says 'what about [Brand]', keep the same subcategory from history — do NOT infer subcategory from brand name."
        )
    else:
        full_prompt = user_message

    messages = [
        SystemMessage(content=EXTRACTION_SYSTEM_PROMPT),
        HumanMessage(content=full_prompt),
    ]

    response = llm.invoke(messages)
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

    # Merge with previous preferences — preserve context across turns
    previous_prefs = state.get("preferences") or {}
    if previous_prefs and not preferences.get("unavailable_request"):
        new_category = preferences.get("category") or previous_prefs.get("category")
        prev_category = previous_prefs.get("category")
        prev_subcategory = previous_prefs.get("subcategory")
        new_subcategory = preferences.get("subcategory")

        # If category is unchanged and only brand differs, the LLM may infer the wrong
        # subcategory from the brand name (e.g. Samsung → earphones when context is TVs).
        # Keep the previous subcategory in that case.
        if (
            new_category == prev_category
            and prev_subcategory
            and new_subcategory
            and new_subcategory != prev_subcategory
            and not preferences.get("type")       # no explicit type change
            and preferences.get("brand") is not None  # only brand was specified
        ):
            new_subcategory = prev_subcategory

        preferences = {
            "category":    new_category,
            "subcategory": new_subcategory or prev_subcategory,
            "type":        preferences.get("type")        or previous_prefs.get("type"),
            "brand":       preferences.get("brand"),
            "max_price":   preferences.get("max_price")   or previous_prefs.get("max_price"),
            "min_price":   preferences.get("min_price")   or previous_prefs.get("min_price"),
            "keywords":    preferences.get("keywords")    or previous_prefs.get("keywords"),
            "unavailable_request": preferences.get("unavailable_request", False),
        }

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
        "final_response": (
            f"• Electronics (490 products) — TVs, headphones, smartwatches, cameras\n"
            f"• Computers & Accessories (375 products) — Cables, chargers, keyboards, mice\n"
            f"• Home & Kitchen (447 products) — Appliances, cookware, fans, air purifiers\n"
            f"• Office Products (31 products) — Stationery, paper products\n\n"
        )
    }


def handle_unavailable_products(state: AgentState) -> dict:
    user_message = state.get("user_message", "")
    logger.info(f"request_id={get_request_id()} | Unavailable category requested")
    
    return {
        "final_response": (
            f"I'm sorry, we don't carry that item in our catalog. "
            f"However, we have a great selection in other categories:\n\n"
            f"• Electronics (490 products) - TVs, headphones, cameras, wearables\n"
            f"• Computers & Accessories (375 products) - Cables, chargers, keyboards\n"
            f"• Home & Kitchen (447 products) - Appliances, cookware, fans\n"
            f"• Office Products (31 products) - Stationery, paper products\n\n"
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
        limit=20,
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
                            f"We carry:\n"
                            f"• Electronics (490 products) — TVs, headphones, smartwatches, cameras\n"
                            f"• Computers & Accessories (375 products) — Cables, chargers, keyboards, mice\n"
                            f"• Home & Kitchen (447 products) — Appliances, cookware, fans, air purifiers\n"
                            f"• Office Products (31 products) — Stationery, paper products\n\n"
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
        # Specific request with no matching category = not in catalog
        if prefs.get("keywords"):
            return "unavailable"
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

    candidates = search_results[:20]
    product_list = "\n".join([
        f"{i+1}. {p['name'][:70]} | Price: ₹{p['price']} | Rating: {p['rating']} | Brand: {p.get('brand', 'N/A')}"
        for i, p in enumerate(candidates)
    ])

    messages = [
        SystemMessage(content="You are a product ranking expert. Return only valid JSON arrays. No explanation."),
        HumanMessage(content=(
            f"Rank these products by relevance to the user's request.\n\n"
            f"User request: \"{user_message}\"\n\n"
            f"Products:\n{product_list}\n\n"
            f"Rules:\n"
            f"- For feature requests (e.g. 'best battery', 'calling feature', 'noise cancellation'), "
            f"rank products that match those features first.\n"
            f"- Include any product that is a direct or close match.\n"
            f"- Return [] only if the products are entirely unrelated to the request.\n\n"
            f"Return ONLY a JSON array of 1-based indices, most relevant first. Max 5 products.\n"
            f"Example: [3, 1, 7, 2, 5]"
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

    graph.add_edge("rank_and_filter", "product_enrichment")
    graph.add_edge("product_enrichment", "format_recommendations")
    graph.add_edge("ask_for_preferences", END)
    graph.add_edge("handle_unavailable", END)
    graph.add_edge("respond_no_results", END)
    graph.add_edge("format_recommendations", END)

    return graph.compile()


product_agent_graph = build_product_agent_graph()