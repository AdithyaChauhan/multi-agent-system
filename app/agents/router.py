import json
import os
import time
from typing import Literal
from langchain_groq import ChatGroq
from app.core.config import GROQ_MODEL
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from dotenv import load_dotenv

from app.agents.state import AgentState

from app.agents.order_agent import order_agent_graph
from app.agents.product_agent import product_agent_graph
from app.agents.support_agent import support_agent_graph

from app.core.logger import get_logger, get_request_id
from app.core.prompt_loader import load_prompt
from app.core.metrics import agent_requests_total, llm_requests_total, llm_tokens_total, llm_duration_seconds

load_dotenv()

logger = get_logger("app.agents.router")

llm = ChatGroq(model=GROQ_MODEL, temperature=0, api_key=os.getenv("GROQ_API_KEY"))


ROUTER_SYSTEM_PROMPT = load_prompt("router")


def classify_intent_and_extract(state: AgentState) -> dict:
    """LLM node — classifies intent using prompt from LangSmith Hub"""
    user_message = state["user_message"]
    conversation_history = state.get("conversation_history", [])

    system_prompt = ROUTER_SYSTEM_PROMPT

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
        messages, config={"metadata": {"prompt_name": "router"}}
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

    # Safety override: if LLM returned unclear but recent history contains product
    # responses, the user is in a shopping session — treat as a new product request.
    # Handles ambiguous bare nouns (blanket, milk, book) that the LLM misclassifies.
    # Does NOT apply to navigation phrases or greetings — those stay as unclear.
    _NAVIGATION_PHRASES = {
        "find a product",
        "find products",
        "find product",
        "i need help",
        "i need support",
        "help me",
        "help",
        "resolve support issues",
        "get support",
        "what can you do",
        "what do you do",
        "get started",
        "browse",
        "browse products",
    }
    if intent == "unclear":
        msg_normalized = user_message.strip().lower().rstrip("!.,?")
        if msg_normalized not in _GREETINGS and msg_normalized not in _NAVIGATION_PHRASES:
            history = state.get("conversation_history") or []
            recent_assistant = [m["content"] for m in history[-4:] if m.get("role") == "assistant"]
            if any("Here are" in m or "recommendations" in m or "don't carry" in m for m in recent_assistant):
                intent = "product"
                confidence = 0.8
                logger.info(f"request_id={get_request_id()} | unclear→product override (active product session)")

    if intent in ("order", "product", "support"):
        agent_requests_total.labels(agent=intent).inc()

    logger.info(
        f"request_id={get_request_id()} | Router classified | intent={intent} | confidence={confidence} | order_id={order_id}"
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


_CLARIFY_SYSTEM = load_prompt("clarify")


def ask_for_clarification(state: AgentState) -> dict:
    user_message = state.get("user_message", "")
    messages = [
        SystemMessage(content=_CLARIFY_SYSTEM),
        HumanMessage(content=user_message),
    ]
    response = llm.invoke(messages)
    return {"final_response": response.content.strip()}


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
