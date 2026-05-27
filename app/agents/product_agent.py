import os
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
    "subcategory",
    "brand",
    "price_increase",
    "keywords",
]

EXTRACTION_SYSTEM_PROMPT = """You are a product preference extraction system for an e-commerce catalog.

Our catalog has these categories and subcategories:

Electronics:
- HomeTheater,TV & Video
- Headphones,Earbuds & Accessories
- WearableTechnology
- HomeAudio
- Mobiles & Accessories
- Cameras & Photography
- GeneralPurposeBatteries & BatteryChargers

Computers & Accessories:
- Accessories & Peripherals
- NetworkingDevices
- ExternalDevices & DataStorage
- Monitors
- Printers,Inks & Accessories

Home & Kitchen:
- Kitchen & HomeAppliances
- Heating,Cooling & AirQuality
- HomeStorage & Organization

Office Products (no subcategories)

Extract user preferences and return JSON:
{
  "category": "string or null",
  "subcategory": "string or null",
  "type": "string or null",
  "brand": "string or null",
  "max_price": integer or null,
  "min_price": integer or null,
  "keywords": ["list of strings"],
  "unavailable_request": false
}

RULES:
- Match user query to the most appropriate category and subcategory from the list above
- Set subcategory whenever you can confidently identify it — it filters more precisely than keywords
- Keywords should only contain product-specific terms not covered by category/subcategory (e.g. brand features, specific model types)
- Normalize keywords to standard English (adaptor→adapter, mice→mouse, telly→TV)
- Rating/review score is NOT a searchable field — ignore rating mentions in keywords
- Strip noise words from keywords (feature, support, mode, enabled, compatible)

NOTE: Set unavailable_request TRUE for:
- Laptops, desktop computers, tablets (accessories only, NOT the devices)
- Smartphones, mobile phones as devices (accessories like cases, chargers are fine)
- Cameras (NOT in catalog)
- Clothing, shoes, toys, food, furniture, books

Set unavailable_request FALSE for all accessories and peripherals.

EXAMPLES:
Input: "show me boAt headphones under 2000"
Output: {"category": "Electronics", "subcategory": "Headphones,Earbuds & Accessories", "brand": "boAt", "max_price": 2000, "min_price": null, "keywords": [], "unavailable_request": false}

Input: "USB Type-C cable"
Output: {"category": "Computers & Accessories", "subcategory": "Accessories & Peripherals", "brand": null, "max_price": null, "min_price": null, "keywords": ["USB", "Type-C", "cable"], "unavailable_request": false}

Input: "smart TV under 15000"
Output: {"category": "Electronics", "subcategory": "HomeTheater,TV & Video", "brand": null, "max_price": 15000, "min_price": null, "keywords": [], "unavailable_request": false}

Input: "football shoes"
Output: {"category": null, "subcategory": null, "brand": null, "max_price": null, "min_price": null, "keywords": ["football", "shoes"], "unavailable_request": true}

Input: "laptop under 50000"
Output: {"category": null, "subcategory": null, "brand": null, "max_price": 50000, "min_price": null, "keywords": ["laptop"], "unavailable_request": true}

Input: "smartwatch with calling feature"
Output: {"category": "Electronics", "subcategory": "WearableTechnology", "brand": null, "max_price": null, "min_price": null, "keywords": ["calling"], "unavailable_request": false}

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

    # Include history in prompt for follow-up understanding
    if history_context:
        full_prompt = (
            f"Recent conversation:\n{history_context}\n\n"
            f"Current message: {user_message}\n\n"
            f"IMPORTANT: If the current message is a follow-up or refinement, extract accordingly:\n"
            f"- 'cheaper ones', 'under 1000', 'more affordable' → keep category, lower max_price\n"
            f"- 'ones with X feature', 'what about X' → keep category+price, add X as keyword\n"
            f"- 'different brand', 'what about boAt' → keep category+price, change brand\n"
            f"- 'best rating', 'highest rated', 'top rated' → keep category+price, add 'best' keyword\n"
            f"- 'show more', 'other options' → keep all same filters\n"
            f"Example: history has 'air purifier under 15000', user says 'cheaper ones' "
            # f"→ category='Home & Kitchen', max_price=8000, keywords=['air purifier']\n"
            # f"Example: history has 'mixer grinder results', user says 'which has best rating' "
            f"→ category='Home & Kitchen', keywords=['mixer grinder']\n"
            f"PRIORITY: Current message always takes precedence over history. Extract keywords ONLY from current message, use history only to understand context like price range or category."
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
    except json.JSONDecodeError as e:
        logger.error(
            f"request_id={get_request_id()} | "
            f"Preference parse error | raw={raw} | error={str(e)}"
        )
        preferences = {"category": None, "keywords": [], "unavailable_request": False}

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
        return "ask"
    
    return "search"


def route_after_search(state: AgentState) -> Literal["rank", "broaden"]:
    results = state.get("search_results") or []
    return "rank" if results else "broaden"


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
        {"rank": "product_enrichment", "broaden": "broaden_search"}
    )

    graph.add_conditional_edges(
        "broaden_search",
        route_after_broaden,
        {"retry_search": "search_products", "no_results": "respond_no_results"}
    )

    graph.add_edge("product_enrichment", "format_recommendations")
    graph.add_edge("ask_for_preferences", END)
    graph.add_edge("handle_unavailable", END)
    graph.add_edge("respond_no_results", END)
    graph.add_edge("format_recommendations", END)

    return graph.compile()


product_agent_graph = build_product_agent_graph()