"""Support: cancellations, returns, complaints, policy questions.

The router has already decided the issue, the order and whether there is a legal threat.
Everything here is deterministic, and a reply claims only what this turn's code did (ADR 0020):
a ticket that was opened, an alert that went out, an order that was cancelled. Nothing promises a
refund, a response time, an email or a call to the carrier, because no code does those.

Cancelling pauses the graph (`interrupt`) until the shopper presses Yes or No in the UI; the order
is cancelled only by plain Python after that, for its owner and only while it is still processing.
"""

import re
from typing import Literal

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app.agents.escalation import escalation_graph
from app.agents.order_agent import as_data, order_lines
from app.agents.state import SupportInput, SupportOutput, SupportState
from app.core.logger import get_logger, get_request_id
from app.tools.order_tools import cancel_order_in_db, fetch_order_from_db, fetch_user_orders
from app.tools.support_tools import get_open_ticket_for_order

logger = get_logger("app.agents.support_agent")

# Problems the policy covers: a report opens a ticket for a person (severity "medium", priority P2).
TICKET_ISSUES = {
    "refund_request",
    "damaged_delivery",
    "defective_product",
    "wrong_item",
    "missing_parts",
    "account_data",
}
# The shopper asks for a ticket in so many words ("open a ticket for ORD-2002").
ASKS_FOR_TICKET = re.compile(r"\b(?:open|create|raise|file|log)\b.{0,25}\b(?:ticket|complaint)\b", re.IGNORECASE)
NOT_ARRIVED = {"processing", "placed", "shipped", "in_transit", "out_for_delivery"}
# Issues that don't need an order before anything can happen.
NO_ORDER_NEEDED = {"policy_question", "account_data"}
# Issue names that are also ticket categories in the database; the rest are stored as "other".
DB_CATEGORIES = {"defective_product", "wrong_item", "damaged_delivery", "missing_parts", "refund_request"}

POLICY_RESPONSE = (
    "Here's a quick summary of our policies:\n\n"
    "**Returns:** Most items can be returned within 30 days of delivery in original condition.\n"
    "**Refunds:** Processed within 3-5 business days after we receive the return.\n"
    "**Defective items:** Replacement or full refund — no questions asked.\n"
    "**Damaged delivery:** Report within 48 hours for priority resolution.\n\n"
    "If you have a specific order you'd like help with, just share the order number and I'll get started."
)


def _issue(state: SupportState) -> str:
    return (state.get("support_issue") or {}).get("category") or "other"


def find_order(state: SupportState) -> dict:
    """The order the router resolved, fetched for this user only (ownership check)."""
    user_id = state.get("user_id", "")
    order_id = state.get("order_id")
    order = fetch_order_from_db(order_id, user_id) if order_id else None
    logger.info(f"request_id={get_request_id()} | support order | order_id={order_id} | found={bool(order)}")
    return {"support_order": order, "user_orders": None if order else fetch_user_orders(user_id)}


def route_support(state: SupportState) -> Literal["policy", "ticket", "ask_order", "cancel", "explain"]:
    """Act at once only when the shopper reported a problem the policy covers, or asked for a ticket;
    a cancel always asks first (it can't be undone); anything else is explained, not acted on."""
    issue = _issue(state)
    if issue == "policy_question":
        return "policy"
    if state.get("risk") == "legal" or issue == "account_data":
        return "ticket"
    if not state.get("support_order"):
        return "ask_order"
    if issue == "cancel":
        return "cancel"
    if issue == "refund_request" and _status(state["support_order"]) in NOT_ARRIVED:
        return "explain"  # a refund for an order still on its way: the policy can't do that yet
    if issue in TICKET_ISSUES or ASKS_FOR_TICKET.search(state.get("user_message") or ""):
        return "ticket"
    return "explain"


def answer_policy(state: SupportState) -> dict:
    return {"final_response": POLICY_RESPONSE}


def ask_for_order(state: SupportState) -> dict:
    orders = state.get("user_orders") or []
    order_id = state.get("order_id")
    if not orders:
        return {
            "final_response": "I'd be happy to help! To open a support ticket, I need the order this is about.\n\n"
            "I couldn't find any orders on your account. Could you double-check and provide the order number (e.g. ORD-1234)?"
        }
    if order_id:
        intro = f"I couldn't find order **{order_id}** on your account. Here are your recent orders:\n\n"
    else:
        intro = (
            "To raise a support ticket, I need to know which order this is about.\n\nHere are your recent orders:\n\n"
        )
    return {
        "final_response": f"{intro}{order_lines(orders, numbered=True)}\n\n"
        "Please reply with the order number to open a support ticket.",
        "listed_orders": as_data(orders),
    }


def _status(order: dict) -> str:
    return (order.get("status") or "").lower().replace(" ", "_")


def handle_cancellation(state: SupportState) -> dict:
    """Explain why an order can't be cancelled; a processing order goes on to ask the shopper."""
    order = state.get("support_order") or {}
    order_id = order.get("order_id")
    status = _status(order)
    if status == "processing":
        return {}
    if status in ("shipped", "out_for_delivery", "in_transit"):
        reply = f"Order **{order_id}** has already shipped — cancellation isn't possible. Once it arrives, I can help you initiate a return."
    elif status == "delivered":
        reply = f"Order **{order_id}** has been delivered and can't be cancelled. You can return it within our 30-day policy window."
    elif status in ("cancelled", "canceled"):
        reply = f"Order **{order_id}** is already cancelled — nothing further needed."
    else:
        reply = f"Order **{order_id}** has status '{order.get('status')}', so I can't cancel it here. A support agent can help."
    return {"final_response": reply}


def route_cancellation(state: SupportState) -> Literal["confirm", "done"]:
    return "confirm" if _status(state.get("support_order") or {}) == "processing" else "done"


def confirm_cancel(state: SupportState) -> dict:
    """Pause the graph until the shopper answers. Nothing happens before the pause, because the node
    runs again from the top when the graph resumes; the answer is what `interrupt` returns."""
    order = state.get("support_order") or {}
    product = order.get("product_name", "your order")
    answer = interrupt(
        {
            "type": "confirm_cancel",
            "order_id": order.get("order_id"),
            "product_name": product,
            "question": f"Your order **{order.get('order_id')}** ({product}) is in processing and can still be "
            "cancelled. Do you want to cancel it?",
        }
    )
    return {"cancel_answer": answer if isinstance(answer, dict) else {}}


def route_answer(state: SupportState) -> Literal["cancel", "keep"]:
    return "cancel" if (state.get("cancel_answer") or {}).get("confirm") is True else "keep"


def cancel_order(state: SupportState) -> dict:
    """The only place an order is cancelled: the person who pressed Yes must be the person in this
    conversation, and the database update re-checks the owner and that the order is still processing."""
    order_id = (state.get("support_order") or {}).get("order_id")
    caller = (state.get("cancel_answer") or {}).get("user_id")
    if caller and caller == state.get("user_id") and cancel_order_in_db(order_id, caller):
        logger.info(f"request_id={get_request_id()} | order cancelled after confirmation | {order_id}")
        return {"final_response": f"Order **{order_id}** has been cancelled."}
    logger.warning(f"request_id={get_request_id()} | cancel refused | order_id={order_id} | caller={caller}")
    return {
        "final_response": f"I couldn't cancel **{order_id}**. It may have shipped already, or it isn't on your "
        "account. A support agent can help if you think this is wrong."
    }


def keep_order(state: SupportState) -> dict:
    return {"final_response": "No problem! Your order is still active."}


def _category(state: SupportState) -> str:
    issue = _issue(state)
    return issue if issue in DB_CATEGORIES else "other"


def quoted(words: str, limit: int = 300) -> str:
    """The shopper's own words, kept apart from what code decided: quoted, on one line, cut to length."""
    text = " ".join(str(words or "").split())
    return f'"{text[:limit]}{"…" if len(text) > limit else ""}"'


def _description(state: SupportState) -> str:
    """What the ticket says, built by code; the shopper's words are evidence, never instructions."""
    order_id = (state.get("support_order") or {}).get("order_id")
    label = _issue(state).replace("_", " ")
    summary = f"{label}{f' | order {order_id}' if order_id else ''}"
    if state.get("risk") == "legal":
        summary = f"[LEGAL] {summary}"
    return f"{summary} | shopper wrote: {quoted(state.get('user_message', ''))}"


def create_ticket(state: SupportState) -> dict:
    """What to hand to a person (the escalation subgraph opens it). One open ticket per order."""
    user_id = state.get("user_id", "")
    order_id = (state.get("support_order") or {}).get("order_id")
    if order_id:
        existing = get_open_ticket_for_order(user_id, order_id)
        if existing:
            return {
                "escalation": None,
                "final_response": f"You already have an open ticket **{existing['ticket_id']}** for order "
                f"**{order_id}**, so I didn't open another one. Is there anything else I can help with?",
            }
    return {
        "escalation": {
            "user_id": user_id,
            "severity": "medium",
            "category": _category(state),
            "description": f"[P2] {_description(state)[:500]}",
            "order_id": order_id,
        }
    }


def route_ticket(state: SupportState) -> Literal["escalate", "done"]:
    return "escalate" if state.get("escalation") else "done"


def ticket_reply(state: SupportState) -> dict:
    """Exactly what happened: the ticket, its order and kind, and whether the team was alerted."""
    ticket = state["ticket"]
    order_id = (state.get("support_order") or {}).get("order_id")
    kind = _issue(state).replace("_", " ")
    reply = f"Ticket **{ticket['ticket_id']}** opened" + (f" for order **{order_id}**" if order_id else "")
    reply += f" ({kind})."
    reply += (
        " Our support team has been alerted."
        if ticket.get("alerted")
        else " It's in our support team's queue; the alert to them didn't go through."
    )
    return {"final_response": reply}


def explain(state: SupportState) -> dict:
    """A request no code can carry out as asked: say what the order's status means and what we can do.
    No model writes this, so it can't promise a refund, a call to the carrier or a date."""
    order = state.get("support_order") or {}
    order_id, product, status = order.get("order_id"), order.get("product_name"), _status(order)
    if _issue(state) == "refund_request":
        reply = (
            f"**{product}** (order **{order_id}**) hasn't arrived yet, so it can't be refunded now. "
            "Our return policy starts at delivery: returns within 30 days of delivery, refunded 3-5 business "
            "days after the return reaches us."
        )
    else:
        reply = f"**{product}** (order **{order_id}**) is {status.replace('_', ' ')}. I can't contact the carrier or change an order myself."
    return {
        "final_response": f"{reply}\n\nIf you'd like a person to look into it, say \"open a ticket for {order_id}\"."
    }


def build_support_agent_graph():
    graph = StateGraph(SupportState, input_schema=SupportInput, output_schema=SupportOutput)
    graph.add_node("find_order", find_order)
    graph.add_node("answer_policy", answer_policy)
    graph.add_node("ask_for_order", ask_for_order)
    graph.add_node("handle_cancellation", handle_cancellation)
    graph.add_node("confirm_cancel", confirm_cancel)
    graph.add_node("cancel_order", cancel_order)
    graph.add_node("keep_order", keep_order)
    graph.add_node("create_ticket", create_ticket)
    graph.add_node("ticket_handoff", escalation_graph)
    graph.add_node("ticket_reply", ticket_reply)
    graph.add_node("explain", explain)
    graph.set_entry_point("find_order")
    graph.add_conditional_edges(
        "find_order",
        route_support,
        {
            "policy": "answer_policy",
            "ticket": "create_ticket",
            "ask_order": "ask_for_order",
            "cancel": "handle_cancellation",
            "explain": "explain",
        },
    )
    graph.add_conditional_edges("handle_cancellation", route_cancellation, {"confirm": "confirm_cancel", "done": END})
    graph.add_conditional_edges("confirm_cancel", route_answer, {"cancel": "cancel_order", "keep": "keep_order"})
    graph.add_conditional_edges("create_ticket", route_ticket, {"escalate": "ticket_handoff", "done": END})
    graph.add_edge("ticket_handoff", "ticket_reply")
    for node in ("answer_policy", "ask_for_order", "cancel_order", "keep_order", "ticket_reply", "explain"):
        graph.add_edge(node, END)
    return graph.compile()


support_agent_graph = build_support_agent_graph()
