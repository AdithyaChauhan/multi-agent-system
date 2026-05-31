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


ROUTER_SYSTEM_PROMPT = """Classify user intent for a customer service app. Use conversation history to resolve references and follow-ups.

Intents:
- "order" — order status, tracking, delivery, shipping. If assistant asked for order ID and user provides one → "order"
- "product" — ANY shopping, browsing, recommendations, or refinement of a previous product search
- "support" — complaints, refunds, returns, defective items, broken products
- "unclear" — truly off-topic (geography, general knowledge) or pure pronoun with no referent

CONTEXT PRIORITY — check the last assistant message first:
- If the last assistant message is from a support flow (asked "which order", "order number", "please reply with the order number", "raise a support ticket", "support ticket") → classify the follow-up as "support" regardless of its content
- If the last assistant message showed product recommendations → classify refinements as "product"
- "support" context beats product keyword matching — a product name reply to a support question is "support", not "product"

Product follow-up rules (if history shows a product search, ALWAYS classify as "product"):
- Price only: "under 2000", "cheaper", "between 1000 and 2000"
- Brand only: "what about Sony", "show me Bajaj"
- Feature: "ones with calling feature", "wireless ones", "show more"
- Any refinement of prior search → "product", confidence >= 0.9

Support follow-up rules (if last assistant message is from a support flow):
- Product name reply: "the iphone one", "samsung tv", "the headphones" → "support", confidence >= 0.9
- Bare number: "9901", "2002" → "support", confidence >= 0.9
- Any reply to support's clarification question → "support", confidence >= 0.9

Order ID: extract if present (ORD-1234, order #1234, "the first one", "the shipped one").
"list/show my orders" → order_id: null.

Examples:
History: "You have ORD-2002 (delivered), ORD-2001 (shipped). Which one?" | Message: "the first one"
→ {"intent": "order", "confidence": 1.0, "order_id": "ORD-2002"}

History: "Here are smartwatches under 3000..." | Message: "under 2000"
→ {"intent": "product", "confidence": 0.95, "order_id": null}

History: "To raise a support ticket, I need to know which order... Please reply with the order number." | Message: "the iphone one"
→ {"intent": "support", "confidence": 0.95, "order_id": null}

History: "I couldn't find that order. Here are your orders: 1. ORD-9904 Samsung 43 inch 4K Smart TV... Please reply with the order number." | Message: "samsung tv"
→ {"intent": "support", "confidence": 0.95, "order_id": "ORD-9904"}

History: "Which order is this regarding? Here are your recent orders: 1. ORD-9901 iPhone..." | Message: "9901"
→ {"intent": "support", "confidence": 0.95, "order_id": "ORD-9901"}

Message: "it" (no clear referent in history)
→ {"intent": "unclear", "confidence": 0.3, "order_id": null}

Respond ONLY with valid JSON:
{"intent": "order"|"product"|"support"|"unclear", "confidence": 0.0-1.0, "order_id": "ORD-1234"|null}"""

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