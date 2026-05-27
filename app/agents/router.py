import json
import os
from typing import Literal
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from dotenv import load_dotenv

from app.agents.state import AgentState

from app.agents.order_agent import order_agent_graph
from app.agents.product_agent import product_agent_graph
from app.agents.support_agent import support_agent_graph

from app.core.prompt_loader import load_prompt, PROMPT_VERSIONS

from app.core.logger import get_logger, get_request_id

load_dotenv()

logger = get_logger("app.agents.router")

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=os.getenv("OPENAI_API_KEY"))


ROUTER_SYSTEM_PROMPT = """You are an intent classification system for a customer service application.

You receive conversation history to understand context. Use it to interpret references, pronouns, and follow-up messages.

## CRITICAL: Understanding Conversation Context

When conversation history is provided, CAREFULLY READ IT to understand:
1. What was just asked or shown to the user
2. What the user is referring to with pronouns or references
3. The current topic of conversation

### Examples of Context Understanding:

**Example 1 - Reference Resolution:**
History:
- Assistant: "You have 2 orders: ORD-2002 (delivered), ORD-2001 (shipped). Which one?"
Current message: "the first one"

Analysis: User is answering the question. "the first one" = ORD-2002 (first in the list).
Output: {"intent": "order", "confidence": 1.0, "order_id": "ORD-2002"}

**Example 2 - Pronoun Resolution:**
History:
- Assistant: "You have 2 orders: ORD-2002, ORD-2001. Which one?"
Current message: "the shipped one"

Analysis: User is specifying which order. "shipped one" = ORD-2001 (shown as shipped).
Output: {"intent": "order", "confidence": 1.0, "order_id": "ORD-2001"}

**Example 3 - Topic Continuation:**
History:
- Assistant: "Here are some headphones..."
Current message: "what about for older kids?"

Analysis: User is continuing the product search topic, just refining criteria.
Output: {"intent": "product", "confidence": 0.95, "order_id": null}

**Example 4 - Pure Pronoun:**
History:
- Assistant: "You have 2 orders: ORD-2002, ORD-2001. Which one?"
Current message: "it"

Analysis: "it" is too vague - need to ask for clarification.
Output: {"intent": "unclear", "confidence": 0.3, "order_id": null}

**Example 5 - Price Refinement:**
History:
- Assistant: "Here are smartwatches under 3000..."
Current message: "under 2000"

Analysis: Price refinement of ongoing product search. Always product intent.
Output: {"intent": "product", "confidence": 0.95, "order_id": null}

**Example 6 - Brand Switch:**
History:
- Assistant: "Here are headphones under 2000..."
Current message: "what about Sony"

Analysis: Brand switch in ongoing product search. Always product intent.
Output: {"intent": "product", "confidence": 0.95, "order_id": null}

**Example 7 - Feature Refinement:**
History:
- Assistant: "Here are wireless mice..."
Current message: "ones with long battery life"

Analysis: Feature refinement of ongoing product search. Always product intent.
Output: {"intent": "product", "confidence": 0.95, "order_id": null}

**Example 8 - Out of Scope:**
Current message: "what is the capital of France?"

Analysis: Not related to shopping, orders, or support.
Output: {"intent": "unclear", "confidence": 0.9, "order_id": null}

**Example 9 - Show More:**
History:
- Assistant: "Here are mixer grinders under 2000..."
Current message: "show me more"

Analysis: Continuation of product search.
Output: {"intent": "product", "confidence": 0.95, "order_id": null}

## Intent Classification Rules:

Classify the user's message into ONE of these intents:

**"order"** — Questions about order status, shipping, tracking, delivery
- Examples: "where is my order", "track my package", "order status"
- IMPORTANT: If conversation shows assistant asked for order ID and user provides one → "order"

**"product"** — ANYTHING related to shopping, products, browsing, recommendations
- Examples: "laptops", "headphones", "show me shoes", "I need a gift"
- Price-only follow-ups: "under 2000", "cheaper", "5000 to 8000" → ALWAYS "product" if history shows product search
- Brand-only follow-ups: "what about Sony", "show Bajaj" → ALWAYS "product" if history shows product search
- Feature follow-ups: "ones with calling feature", "wireless ones" → ALWAYS "product"
- Price range: "between 1000 and 2000" → ALWAYS "product" if history shows product search
- Any refinement of previous product search → "product" with confidence >= 0.9

**"support"** — Complaints, refunds, returns, defective items, issues
- Examples: "this is broken", "I want a refund", "complaint"

**"unclear"** — ONLY use this if:
- Message is completely ambiguous with NO conversation history
- Truly off-topic (weather, geography, general knowledge questions)
- Pure pronouns without clear referent

## Order ID Extraction:

Extract order ID if present:
- Direct formats: ORD-1234, ORD1234, order #1234
- Contextual references: "the first one", "the delivered one"

## Important: List Intent
If user says "show my orders", "list my orders" → set order_id to null. User wants a list.

## Response Format:

Respond ONLY with valid JSON:
{
  "intent": "order" | "product" | "support" | "unclear",
  "confidence": 0.0 to 1.0,
  "order_id": "ORD-1234" or null
}

## Reasoning Process:

1. Read conversation history carefully
2. Identify what was just discussed
3. Understand what user is referring to
4. Classify intent based on context
5. Extract order_id if applicable

Do not include any text outside the JSON."""

def classify_intent_and_extract(state: AgentState) -> dict:
    """LLM node — classifies intent using prompt from LangSmith Hub"""
    user_message = state["user_message"]
    conversation_history = state.get("conversation_history", [])
    
    # Load prompt from LangSmith Hub
    version = PROMPT_VERSIONS.get("router-classification-prompt", "latest")
    system_prompt, commit_hash = load_prompt("router-classification-prompt", version)
    
    # Fallback to hardcoded if hub fails
    if not system_prompt:
        logger.warning(f"request_id={get_request_id()} | Using fallback router prompt")
        system_prompt = ROUTER_SYSTEM_PROMPT
        commit_hash = "fallback"
    
    # Build conversation context
    history_context = ""
    if conversation_history:
        recent = conversation_history[-4:]
        history_context = "\n".join([
            f"{msg['role'].title()}: {msg['content']}"
            for msg in recent
        ])
    
    prompt = user_message
    if history_context:
        prompt = f"Recent conversation:\n{history_context}\n\nCurrent message: {user_message}"

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=prompt),
    ]

    response = llm.invoke(
        messages,
        config={
            "metadata": {
                "prompt_name": "router-classification-prompt",
                "prompt_version": commit_hash
            }
        }
    )
    
    raw = response.content.strip()

    try:
        parsed = json.loads(raw)
        intent = parsed.get("intent", "unclear")
        confidence = float(parsed.get("confidence", 0.0))
        order_id = parsed.get("order_id")
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"request_id={get_request_id()} | Router parse error | raw={raw} | error={str(e)}")
        intent = "unclear"
        confidence = 0.0
        order_id = None

    logger.info(f"request_id={get_request_id()} | Router classified | intent={intent} | confidence={confidence} | order_id={order_id} | prompt_version={commit_hash}")

    return {
        "intent": intent,
        "confidence": confidence,
        "order_id": order_id,
    }


def ask_for_clarification(state: AgentState) -> dict:
    user_message = state.get("user_message", "")
    conversation_history = state.get("conversation_history", [])
    
    # If there's product history, likely a follow-up that wasn't understood
    if conversation_history:
        return {
            "final_response": "I didn't quite understand that. Are you looking for a product, checking an order, or need support?"
        }
    
    return {
        "final_response": "I'm a shopping assistant. I can help you find products, track orders, or resolve support issues. What are you looking for?"
    }

def auth_gate(state: AgentState) -> dict:
    """Deterministic node — pass-through for auth routing."""
    user_id = state.get("user_id", "")
    intent = state.get("intent", "")
    is_anonymous = user_id.startswith("anon-")
    logger.info(f"request_id={get_request_id()} | Auth gate | intent={intent} | anonymous={is_anonymous}")
    return {}


def respond_sign_in(state: AgentState) -> dict:
    intent = state.get("intent", "")
    return {
        "final_response": (
            "To track your orders, you need to sign in first.\n\n"
            "👆 Click the **Sign In** button at the top of the page to continue with Google.\n\n"
            "After signing in, your conversation will be saved and you can pick up right where you left off!"
        )
    }


def route_after_classification(state: AgentState) -> Literal["auth_gate", "clarify"]:
    """Conditional edge function — after classification, route to auth gate or clarify."""
    if state.get("confidence", 0) < 0.8:
        return "clarify"
    if state.get("intent") not in ("order", "product", "support"):
        return "clarify"
    return "auth_gate"


def route_after_auth_gate(state: AgentState) -> Literal["order_agent", "product_agent", "support_agent", "sign_in"]:
    """Conditional edge function — enforces auth rules per intent."""
    user_id = state.get("user_id", "")
    intent = state.get("intent", "")
    is_anonymous = user_id.startswith("anon-")

    # Only orders require authentication
    if intent == "order" and is_anonymous:
        return "sign_in"

    if intent == "order":
        return "order_agent"
    if intent == "product":
        return "product_agent"
    if intent == "support":
        return "support_agent"

    return "sign_in"


def placeholder_product_agent(state: AgentState) -> dict:
    """Placeholder — Agent 2 not built yet."""
    logger.info(f"request_id={get_request_id()} | Product agent placeholder hit")
    return {"final_response": "Product recommendations are coming soon."}


def placeholder_support_agent(state: AgentState) -> dict:
    """Placeholder — Agent 3 not built yet."""
    logger.info(f"request_id={get_request_id()} | Support agent placeholder hit")
    return {"final_response": "Support is coming soon."}


def placeholder_order_agent(state: AgentState) -> dict:
    """Placeholder — Agent 1 will replace this in the next step."""
    logger.info(f"request_id={get_request_id()} | Order agent placeholder hit | order_id={state.get('order_id')}")
    return {"final_response": f"Order agent placeholder. Detected order_id: {state.get('order_id')}"}


def build_router_graph():
    graph = StateGraph(AgentState)

    graph.add_node("classify", classify_intent_and_extract)
    graph.add_node("clarify", ask_for_clarification)
    graph.add_node("auth_gate", auth_gate)
    graph.add_node("sign_in", respond_sign_in)
    graph.add_node("order_agent", order_agent_graph)
    graph.add_node("product_agent", product_agent_graph)
    graph.add_node("support_agent", support_agent_graph)

    graph.set_entry_point("classify")

    graph.add_conditional_edges(
        "classify",
        route_after_classification,
        {
            "clarify": "clarify",
            "auth_gate": "auth_gate",
        }
    )

    graph.add_conditional_edges(
        "auth_gate",
        route_after_auth_gate,
        {
            "order_agent": "order_agent",
            "product_agent": "product_agent",
            "support_agent": "support_agent",
            "sign_in": "sign_in",
        }
    )

    graph.add_edge("order_agent", END)
    graph.add_edge("product_agent", END)
    graph.add_edge("support_agent", END)
    graph.add_edge("clarify", END)
    graph.add_edge("sign_in", END)

    return graph.compile()


router_graph = build_router_graph()