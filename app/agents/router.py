import re
from typing import Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from app.agents.escalation import escalation_graph
from app.agents.order_agent import order_agent_graph
from app.agents.product_agent import product_agent_graph
from app.agents.state import RouterState
from app.agents.support_agent import support_agent_graph
from app.core.checkpoint import make_checkpointer
from app.core.llm import call_llm
from app.core.logger import get_logger, get_request_id
from app.core.metrics import agent_requests_total
from app.core.prompt_loader import load_prompt
from app.tools.order_tools import fetch_user_orders

logger = get_logger("app.agents.router")

ISSUES = (
    "cancel",
    "refund_request",
    "damaged_delivery",
    "defective_product",
    "wrong_item",
    "missing_parts",
    "policy_question",
    "account_data",
    "other",
)


class RouteDecision(BaseModel):
    """Where the message goes, plus what the next step needs."""

    intent: Literal["product", "order", "support", "unclear"]
    order_id: Optional[str] = Field(None, description="ORD-1234, matched against the user's orders")
    issue: Optional[Literal[ISSUES]] = Field(None, description="support only")
    risk: Literal["none", "legal", "safety"] = "none"
    reply: Optional[str] = Field(None, description="unclear only: the reply to send")


CLARIFY_FALLBACK = "Hi! I can help you find products, check an order, or sort out a problem with one. What do you need?"

SAFETY_RESPONSE = (
    "We take safety seriously. If you're in immediate danger, please call emergency services. "
    "We've flagged your message and a human team member will follow up with you."
)


def normalize_order_id(value) -> Optional[str]:
    """'2002', 'ord 2002', 'ORD-2002' → 'ORD-2002'. Anything without digits → None."""
    digits = re.findall(r"\d+", str(value or ""))
    return f"ORD-{digits[0]}" if digits else None


def _orders_line(user_id: str) -> str:
    if not user_id or user_id.startswith("anon-"):
        return "Their orders: not signed in."
    orders = fetch_user_orders(user_id)[:8]
    if not orders:
        return "Their orders: none."
    return "Their orders: " + "; ".join(f"{o['order_id']} {o['product_name']} ({o['status']})" for o in orders)


def classify(state: RouterState) -> dict:
    """LLM node: one structured call decides intent, order, support issue and risk."""
    history = list(state.get("conversation_history") or [])
    message = state.get("user_message", "")
    if history and history[-1].get("role") == "user" and history[-1].get("content") == message:
        history = history[:-1]  # main.py stores the new message before loading history
    recent = "\n".join(f"{m['role'].title()}: {m['content'][:400]}" for m in history[-4:])
    content = f"{_orders_line(state.get('user_id', ''))}\n"
    if recent:
        content += f"Recent conversation:\n{recent}\n"
    content += f"Message: {message}"

    decision = call_llm(
        "router",
        "classify",
        [SystemMessage(content=load_prompt("router")), HumanMessage(content=content)],
        schema=RouteDecision,
    )
    if decision is None:
        decision = RouteDecision(intent="unclear")

    if decision.intent in ("order", "product", "support"):
        agent_requests_total.labels(agent=decision.intent).inc()
    logger.info(
        f"request_id={get_request_id()} | Router | intent={decision.intent} | order_id={decision.order_id}"
        f" | issue={decision.issue} | risk={decision.risk}"
    )
    return {
        "intent": decision.intent,
        "order_id": normalize_order_id(decision.order_id),
        "support_issue": {"category": decision.issue or "other", "description": state.get("user_message", "")},
        "risk": decision.risk,
        "final_response": decision.reply if decision.intent == "unclear" else None,
    }


def route(state: RouterState) -> str:
    """Deterministic routing. Sign-in is required for orders and support; safety goes to a human."""
    if state.get("risk") == "safety":
        return "safety"
    intent = state.get("intent")
    if intent not in ("order", "product", "support"):
        return "clarify"
    if intent in ("order", "support") and state.get("user_id", "").startswith("anon-"):
        return "sign_in"
    return intent


def clarify(state: RouterState) -> dict:
    return {"route": "clarify", "final_response": state.get("final_response") or CLARIFY_FALLBACK}


def respond_sign_in(state: RouterState) -> dict:
    if state.get("intent") == "support":
        context = "I'd love to help resolve this for you! To raise a support ticket we need to verify your account and find your order."
    else:
        context = "I'd love to help you with your order!"
    return {
        "route": "sign_in",
        "final_response": (
            f"{context}\n\n"
            "Please sign in first using the **Sign In** button at the top of the page.\n\n"
            "It only takes a moment with Google, and your conversation will be saved so you can continue right where you left off."
        ),
    }


def safety_escalation(state: RouterState) -> dict:
    """Someone may be hurt: a critical ticket for a person (the escalation subgraph), then a fixed reply."""
    message = state.get("user_message", "")
    logger.warning(f"request_id={get_request_id()} | SAFETY | user_id={state.get('user_id')} | {message[:100]}")
    return {
        "route": "safety",
        "escalation": {
            "user_id": state.get("user_id", ""),
            "severity": "critical",
            "category": "other",
            "description": f"[SAFETY_ALERT] {message[:500]}",
            "safety_alert": True,
        },
    }


def safety_reply(state: RouterState) -> dict:
    return {"final_response": SAFETY_RESPONSE}


def new_turn(user_message: str, user_id: str, session_id: str, conversation_history: list) -> dict:
    """Graph input for one chat turn. The checkpoint carries the conversation's state between turns;
    everything the last turn decided or answered is cleared, so only `preferences` carries over."""
    return {
        "user_message": user_message,
        "user_id": user_id,
        "session_id": session_id,
        "conversation_history": conversation_history,
        "intent": None,
        "order_id": None,
        "risk": None,
        "support_issue": None,
        "route": None,
        "ranked_products": None,
        "relaxed_filters": None,
        "order_data": None,
        "support_order": None,
        "escalation": None,
        "ticket": None,
        "final_response": None,
    }


def build_router_graph(checkpointer=None):
    graph = StateGraph(RouterState)
    graph.add_node("classify", classify)
    graph.add_node("clarify", clarify)
    graph.add_node("sign_in", respond_sign_in)
    graph.add_node("safety", safety_escalation)
    graph.add_node("escalate", escalation_graph)
    graph.add_node("safety_reply", safety_reply)
    graph.add_node("product_agent", product_agent_graph)
    graph.add_node("order_agent", order_agent_graph)
    graph.add_node("support_agent", support_agent_graph)

    graph.set_entry_point("classify")
    graph.add_conditional_edges(
        "classify",
        route,
        {
            "safety": "safety",
            "clarify": "clarify",
            "sign_in": "sign_in",
            "product": "product_agent",
            "order": "order_agent",
            "support": "support_agent",
        },
    )
    graph.add_edge("safety", "escalate")
    graph.add_edge("escalate", "safety_reply")
    for node in ("clarify", "sign_in", "safety_reply", "product_agent", "order_agent", "support_agent"):
        graph.add_edge(node, END)
    return graph.compile(checkpointer=checkpointer)


router_graph = build_router_graph(make_checkpointer())
