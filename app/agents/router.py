import json
import os
import time
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
from app.core.metrics import agent_requests_total, llm_requests_total, llm_tokens_total, llm_duration_seconds

load_dotenv()

logger = get_logger("app.agents.router")

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=os.getenv("OPENAI_API_KEY"))


ROUTER_SYSTEM_PROMPT = """Classify user intent for a customer service app. Use conversation history to resolve references and follow-ups.

Intents:
- "order" — order status, tracking, delivery, shipping, listing orders ("my orders", "show my orders", "order history"), cancellation requests ("cancel ORD-1234", "I want to cancel my order"). If assistant asked for order ID and user provides one → "order"
- "product" — ANY shopping, browsing, recommendations, refinement of a previous product search, vague catalog browsing ("product list", "show products", "what do you have", "appliances", "electronics"), or a bare product name ("tv", "fan", "mouse", "heater", "headphones", "speaker")
- "support" — complaints, refunds, returns, defective items, broken products, or general policy questions ("return policy", "refund policy", "warranty", "how do returns work", "can I return")
- "unclear" — truly off-topic (geography, general knowledge) or pure pronoun with no referent

CONTEXT PRIORITY — check the last assistant message first:
- If the last assistant message is from a SUPPORT flow ASKING A QUESTION (contains "support ticket", "open a support ticket", "raise a support ticket", "for your support ticket", or "please reply with the order number") → follow-up is "support"
- If the last assistant message is a RESOLVED support response (gave a resolution/ticket number but is NOT asking a question) → treat next message based on its OWN content, not support context
- If the last assistant message is from the ORDER agent (listed orders with ORD-XXXX numbers AND said "Please provide the order ID") → follow-up is "order"
- If the last assistant message showed product recommendations → refinements are "product"
- "support" context only applies when support is actively asking a clarification question
- POLICY QUESTIONS always map to "support" regardless of prior context — "return policy", "refund policy", "how do returns work", "can I return", "what is your warranty"

Product follow-up rules (if history shows a product search, ALWAYS classify as "product"):
- Price only: "under 2000", "cheaper", "between 1000 and 2000"
- Brand only: "what about Sony", "show me Bajaj"
- Feature: "ones with calling feature", "wireless ones", "show more"
- Any refinement of prior search → "product", confidence >= 0.9

Support follow-up rules (only when last assistant message is actively asking a support clarification):
- Product name reply: "the iphone one", "samsung tv", "the headphones" → "support"
- Bare number: "9901", "2002" → "support"
- Any reply to support's open question → "support"

Order ID: extract if present (ORD-1234, order #1234, "the first one", "the shipped one").
"list/show my orders" → order_id: null.

Examples:
History: "You have ORD-2002 (delivered), ORD-2001 (shipped). Which one?" | Message: "the first one"
→ {"intent": "order", "confidence": 1.0, "order_id": "ORD-2002"}

History: "Here are smartwatches under 3000..." | Message: "under 2000"
→ {"intent": "product", "confidence": 0.95, "order_id": null}

History: "To raise a support ticket, I need to know which order... Please reply with the order number." | Message: "the iphone one"
→ {"intent": "support", "confidence": 0.95, "order_id": null}

History: "To raise a support ticket, I need to know which order this is about... Please reply with the order number to open a support ticket." | Message: "ORD-2002"
→ {"intent": "support", "confidence": 0.95, "order_id": "ORD-2002"}

History: "I couldn't find that order. Here are your orders: 1. ORD-9904 Samsung 43 inch 4K Smart TV... Please reply with the order number." | Message: "samsung tv"
→ {"intent": "support", "confidence": 0.95, "order_id": "ORD-9904"}

History: "Which order is this regarding? Here are your recent orders: 1. ORD-9901 iPhone..." | Message: "9901"
→ {"intent": "support", "confidence": 0.95, "order_id": "ORD-9901"}

Message: "my orders"
→ {"intent": "order", "confidence": 0.95, "order_id": null}

History: "You have multiple orders: • ORD-9901 iPhone... • ORD-9905 Bajaj Mixer... Please provide the order ID." | Message: "9905 status"
→ {"intent": "order", "confidence": 0.95, "order_id": "ORD-9905"}

History: "You have multiple orders: • ORD-9902 boAt Rockerz 450... Please provide the order ID." | Message: "boAt Rockerz 450 status"
→ {"intent": "order", "confidence": 0.95, "order_id": "ORD-9902"}

History: "I've created a support ticket TKT-XXXX for your damaged Samsung TV..." | Message: "what about my iphone order"
→ {"intent": "order", "confidence": 0.9, "order_id": null}

History: "You have multiple orders: • ORD-2005 Logitech... Please provide the order ID." | Message: "1001"
→ {"intent": "order", "confidence": 0.95, "order_id": "ORD-1001"}

Message: "cancel ORD-2005"
→ {"intent": "order", "confidence": 0.95, "order_id": "ORD-2005"}

Message: "I want to cancel my order"
→ {"intent": "order", "confidence": 0.9, "order_id": null}

Message: "What's your return policy?"
→ {"intent": "support", "confidence": 0.9, "order_id": null}

History: "Your order ORD-2002 has shipped and is currently in transit..." | Message: "Whats your return policy"
→ {"intent": "support", "confidence": 0.9, "order_id": null}

Message: "tv"
→ {"intent": "product", "confidence": 0.95, "order_id": null}

Message: "products list"
→ {"intent": "product", "confidence": 0.95, "order_id": null}

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

    # Router only needs the last assistant message to apply context-priority rules.
    # Last 2 messages (prev user + last assistant) is sufficient — no need for full history.
    history_context = ""
    if conversation_history:
        recent = conversation_history[-2:]
        history_context = "\n".join([f"{msg['role'].title()}: {msg['content'][:300]}" for msg in recent])

    prompt = user_message
    if history_context:
        prompt = f"Recent conversation:\n{history_context}\n\nCurrent message: {user_message}"

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=prompt),
    ]

    _t0 = time.perf_counter()
    response = llm.invoke(
        messages, config={"metadata": {"prompt_name": "router-classification-prompt", "prompt_version": commit_hash}}
    )
    _latency_s = time.perf_counter() - _t0
    _latency_ms = int(_latency_s * 1000)
    _meta = getattr(response, "response_metadata", {})
    _usage = _meta.get("token_usage", {}) if isinstance(_meta, dict) else {}
    logger.info(
        f"request_id={get_request_id()} | LLM_USAGE | agent=router | node=classify_intent"
        f" | prompt_tokens={_usage.get('prompt_tokens', 0)}"
        f" | completion_tokens={_usage.get('completion_tokens', 0)}"
        f" | total_tokens={_usage.get('total_tokens', 0)}"
        f" | latency_ms={_latency_ms}"
    )
    llm_requests_total.labels(agent="router", node="classify_intent").inc()
    llm_duration_seconds.labels(agent="router", node="classify_intent").observe(_latency_s)
    llm_tokens_total.labels(agent="router", node="classify_intent", token_type="prompt").inc(
        _usage.get("prompt_tokens", 0)
    )
    llm_tokens_total.labels(agent="router", node="classify_intent", token_type="completion").inc(
        _usage.get("completion_tokens", 0)
    )
    llm_tokens_total.labels(agent="router", node="classify_intent", token_type="total").inc(
        _usage.get("total_tokens", 0)
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

    if intent in ("order", "product", "support"):
        agent_requests_total.labels(agent=intent).inc()

    logger.info(
        f"request_id={get_request_id()} | Router classified | intent={intent} | confidence={confidence} | order_id={order_id} | prompt_version={commit_hash}"
    )

    return {
        "intent": intent,
        "confidence": confidence,
        "order_id": order_id,
    }


_GREETINGS = {
    "hi",
    "hello",
    "hey",
    "hiya",
    "howdy",
    "greetings",
    "good morning",
    "good afternoon",
    "good evening",
    "sup",
    "what's up",
    "whats up",
}


def ask_for_clarification(state: AgentState) -> dict:
    user_message = state.get("user_message", "").strip().lower().rstrip("!.,")
    conversation_history = state.get("conversation_history", [])

    if user_message in _GREETINGS:
        return {
            "final_response": "Hi there! I'm your shopping assistant. I can help you:\n\n• 🛍️ Find products\n• 📦 Track your orders\n• 🛠️ Resolve support issues\n\nWhat can I help you with today?"
        }

    if conversation_history:
        return {
            "final_response": "I didn't quite understand that. Are you looking for a product, checking an order, or need support?"
        }

    return {
        "final_response": "Hi! I'm a shopping assistant. I can help you find products, track orders, or resolve support issues. What are you looking for?"
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
    if intent == "support":
        context = "I'd love to help resolve this for you! To raise a support ticket we need to verify your account and find your order."
    else:
        context = "I'd love to help you with your order!"
    return {
        "final_response": (
            f"{context}\n\n"
            "Please sign in first using the **Sign In** button at the top of the page.\n\n"
            "It only takes a moment with Google, and your conversation will be saved so you can continue right where you left off."
        )
    }


def route_after_classification(state: AgentState) -> Literal["auth_gate", "clarify"]:
    """Conditional edge function — after classification, route to auth gate or clarify."""
    if state.get("confidence", 0) < 0.7:
        return "clarify"
    if state.get("intent") not in ("order", "product", "support"):
        return "clarify"
    return "auth_gate"


def route_after_auth_gate(state: AgentState) -> Literal["order_agent", "product_agent", "support_agent", "sign_in"]:
    """Conditional edge function — enforces auth rules per intent."""
    user_id = state.get("user_id", "")
    intent = state.get("intent", "")
    is_anonymous = user_id.startswith("anon-")

    # Orders and support require authentication (both need verified customer + DB orders)
    if intent in ("order", "support") and is_anonymous:
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
        },
    )

    graph.add_conditional_edges(
        "auth_gate",
        route_after_auth_gate,
        {
            "order_agent": "order_agent",
            "product_agent": "product_agent",
            "support_agent": "support_agent",
            "sign_in": "sign_in",
        },
    )

    graph.add_edge("order_agent", END)
    graph.add_edge("product_agent", END)
    graph.add_edge("support_agent", END)
    graph.add_edge("clarify", END)
    graph.add_edge("sign_in", END)

    return graph.compile()


router_graph = build_router_graph()
