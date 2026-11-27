import re
from typing import Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.agents.escalation import escalation_graph
from app.agents.order_agent import order_agent_graph
from app.agents.product_agent import asks_about_shown, product_agent_graph
from app.agents.state import RouterState
from app.agents.support_agent import support_agent_graph
from app.core import config
from app.core.checkpoint import make_checkpointer
from app.core.llm import call_llm
from app.core.logger import get_logger, get_request_id
from app.core.metrics import agent_requests_total
from app.core.prompt_loader import load_prompt
from app.search import hybrid
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
    about_shown: bool = Field(False, description="product only: a question about the products just shown")
    reply: Optional[str] = Field(None, description="unclear only: the reply to send")


STORE = "Wattnest"
GREETING_REPLY = (
    f"Hi! I'm the {STORE} assistant. I can help you find products, check an order, or sort out a problem "
    "with one. What do you need?"
)
OUT_OF_SCOPE_REPLY = (
    f"I can only help with {STORE}'s products, your orders and problems with them, so I can't help with "
    "that. What are you looking for?"
)
# Kept for imports elsewhere: the reply when the router's call fails.
CLARIFY_FALLBACK = GREETING_REPLY
GREETING = re.compile(
    r"^\s*(?:hi+|hello|hey+|hiya|namaste|good (?:morning|afternoon|evening)|thanks?|thank you|ok(?:ay)?)\b[\s!.,?]*"
    r"(?:there|again|team)?[\s!.,?]*$",
    re.IGNORECASE,
)

# Immediate steps that are right for any electrical hazard, then what code did: no promise of a call.
SAFETY_STEPS = (
    "If there's fire, smoke or an injury, call emergency services (112) now. Stop using the product: switch it "
    "off, unplug it, don't charge it, and keep it away from anything that can burn."
)
SAFETY_RESPONSE = SAFETY_STEPS  # the reply when no ticket could be opened


# The safety floor (ADR 0008): phrases that only describe something dangerous happening. It can only
# escalate, never route a message anywhere else, so a rare false match costs one extra ticket.
# Product names never match: "fire tv stick", "Fire-Boltt", "fire sale" have no harm word after them.
SAFETY_PATTERN = re.compile(
    r"\b(caught fire|catch(?:es|ing)? fire|burst into flames|(?:is|was|went|set) on fire(?! sale)"
    r"|burn(?:ed|t) (?:my|me|him|her|his|our|the)\b|electric(?:al)? shock|(?:gave|giving) (?:me|him|her) (?:a )?shock"
    r"|sparks? (?:from|came|coming|flying)|sparking|smok(?:e|ing) (?:from|came|coming)|exploded|explosion"
    r"|melted|injur(?:ed|y|ies))",
    re.IGNORECASE,
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


def _sells_what_this_describes(message: str) -> bool:
    """The router found the message unclear, but the catalog has a product that means the same
    ("remove fuzz balls from my sweaters" -> lint remover): search instead of asking."""
    if config.PRODUCT_SEARCH != "hybrid":
        return False
    match = hybrid.catalog_match(message)
    if match and match["similarity"] >= config.NOT_CARRIED_MIN_SIM:
        logger.info(f"request_id={get_request_id()} | unclear -> product | closest={match}")
        return True
    return False


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

    if decision.risk != "safety" and SAFETY_PATTERN.search(message):
        logger.warning(f"request_id={get_request_id()} | safety floor matched | model risk={decision.risk}")
        decision.risk = "safety"
    if decision.intent == "unclear" and _sells_what_this_describes(message):
        decision.intent, decision.reply = "product", None

    about_shown = decision.intent == "product" and asks_about_shown(
        message, decision.about_shown, state.get("shown_products")
    )
    if decision.intent in ("order", "product", "support"):
        agent_requests_total.labels(agent=decision.intent).inc()
    logger.info(
        f"request_id={get_request_id()} | Router | intent={decision.intent} | order_id={decision.order_id}"
        f" | issue={decision.issue} | risk={decision.risk} | about_shown={about_shown} (model {decision.about_shown})"
    )
    return {
        "intent": decision.intent,
        "order_id": normalize_order_id(decision.order_id),
        "support_issue": {"category": decision.issue or "other", "description": state.get("user_message", "")},
        "risk": decision.risk,
        "about_shown": about_shown,
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
    """A fixed reply, never the model's: a greeting gets a greeting, anything else outside the
    assistant's job is told plainly what it does (the router's `reply` field is ignored)."""
    message = state.get("user_message") or ""
    reply = GREETING_REPLY if not message or GREETING.match(message) else OUT_OF_SCOPE_REPLY
    return {"route": "clarify", "final_response": reply}


def respond_sign_in(state: RouterState) -> dict:
    if state.get("intent") == "support":
        context = "To help with a problem with an order, I need to know whose orders to look at."
    else:
        context = "To look up an order, I need to know whose orders to look at."
    return {
        "route": "sign_in",
        "final_response": (
            f"{context}\n\n"
            "Please press **Sign In** at the top of the page. You can sign in with Google, or press "
            "**Try as a demo shopper** for a demo account with five orders of its own. This conversation "
            "carries on after you sign in."
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
    """The immediate steps first, then exactly what code did: the ticket, and whether the alert went out."""
    ticket = state.get("ticket") or {}
    if not ticket.get("ticket_id"):
        return {"final_response": SAFETY_RESPONSE}
    done = f"I've opened safety ticket **{ticket['ticket_id']}**"
    done += " and alerted our support team." if ticket.get("alerted") else "; it's in our support team's queue."
    return {"final_response": f"{SAFETY_STEPS}\n\n{done}"}


def new_turn(user_message: str, user_id: str, session_id: str, conversation_history: list, filter_edit=None) -> dict:
    """Graph input for one chat turn. The checkpoint carries the conversation's state between turns;
    everything the last turn decided or answered is cleared, so only `preferences` carries over."""
    return {
        "user_message": user_message,
        "user_id": user_id,
        "session_id": session_id,
        "conversation_history": conversation_history,
        "filter_edit": filter_edit,
        "intent": None,
        "order_id": None,
        "risk": None,
        "support_issue": None,
        "route": None,
        "about_shown": None,
        "ranked_products": None,
        "active_filters": None,
        "relaxed_filters": None,
        "order_data": None,
        "support_order": None,
        "listed_orders": None,
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
    graph.add_node("safety_handoff", escalation_graph)
    graph.add_node("safety_reply", safety_reply)
    graph.add_node("product_agent", product_agent_graph)
    graph.add_node("order_agent", order_agent_graph)
    graph.add_node("support_agent", support_agent_graph)

    # A removed filter chip goes straight to the product agent: nothing to classify.
    graph.add_conditional_edges(
        START, lambda s: "product_agent" if s.get("filter_edit") else "classify", ["product_agent", "classify"]
    )
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
    graph.add_edge("safety", "safety_handoff")
    graph.add_edge("safety_handoff", "safety_reply")
    for node in ("clarify", "sign_in", "safety_reply", "product_agent", "order_agent", "support_agent"):
        graph.add_edge(node, END)
    return graph.compile(checkpointer=checkpointer)


router_graph = build_router_graph(make_checkpointer())
