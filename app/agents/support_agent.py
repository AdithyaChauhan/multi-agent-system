"""Support: cancellations, returns, complaints, policy questions.

The router has already decided the issue, the order and whether there is a legal threat.
Everything here is deterministic except the drafted reply for low-severity issues.

Cancelling pauses the graph (`interrupt`) until the shopper presses Yes or No in the UI; the order
is cancelled only by plain Python after that, for its owner and only while it is still processing.
"""

import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app.agents.order_agent import order_lines
from app.agents.state import SupportInput, SupportOutput, SupportState
from app.core.llm import call_llm
from app.core.logger import get_logger, get_request_id
from app.core.prompt_loader import load_prompt
from app.tools.order_tools import cancel_order_in_db, fetch_order_from_db, fetch_user_orders
from app.tools.support_tools import create_support_ticket, get_open_ticket_for_order, lookup_support_policy

logger = get_logger("app.agents.support_agent")

# Issues a human should handle: they get a ticket (severity "medium", priority P2).
TICKET_ISSUES = {"refund_request", "damaged_delivery", "defective_product", "wrong_item", "account_data"}
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


def route_support(state: SupportState) -> Literal["policy", "ticket", "ask_order", "cancel", "draft"]:
    issue = _issue(state)
    if issue == "policy_question":
        return "policy"
    if state.get("risk") == "legal" or issue == "account_data":
        return "ticket"
    if not state.get("support_order"):
        return "ask_order"
    if issue == "cancel":
        return "cancel"
    return "ticket" if issue in TICKET_ISSUES else "draft"


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
        "Please reply with the order number to open a support ticket."
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


def create_ticket(state: SupportState) -> dict:
    """Hand the issue to a human. One open ticket per order."""
    user_id = state.get("user_id", "")
    issue = _issue(state)
    order_id = (state.get("support_order") or {}).get("order_id")
    if order_id:
        existing = get_open_ticket_for_order(user_id, order_id)
        if existing:
            return {
                "final_response": f"You already have an open ticket **{existing['ticket_id']}** for this order. "
                "Our support team will be in touch within the agreed timeframe. Is there anything else I can help you with?"
            }
    category = issue if issue in DB_CATEGORIES else "other"
    description = (state.get("support_issue") or {}).get("description") or state.get("user_message", "")
    if state.get("risk") == "legal":
        description = f"[LEGAL] {description}"
    ticket = create_support_ticket(
        user_id=user_id,
        severity="medium",
        category=category,
        description=f"[P2] {description[:500]}",
        order_id=order_id,
    )
    policy = lookup_support_policy(category, "medium")
    logger.info(f"request_id={get_request_id()} | ticket created | {ticket['ticket_id']} | category={category}")
    return {
        "final_response": f"I've created a support ticket: **{ticket['ticket_id']}**\n\n"
        f"**Issue:** {description[:200]}\n"
        f"**Category:** {category.replace('_', ' ').title()}\n"
        "**Priority:** P2\n"
        f"**Response Time:** {policy.get('response_time', '24 hours')}\n\n"
        "Our support team will review this and contact you. You'll receive email updates at your registered address."
    }


def draft_resolution(state: SupportState) -> dict:
    """LLM node, low-severity issues only: a short reply grounded in the policy table."""
    order = state.get("support_order") or {}
    issue = _issue(state)
    policy = lookup_support_policy(issue if issue in DB_CATEGORIES else "other", "low")
    context = (
        f"Order: {order.get('order_id')} — {order.get('product_name')}\n"
        f"Order status: {order.get('status')}\n"
        f"Customer said: {state.get('user_message', '')}\n"
        f"Issue: {issue.replace('_', ' ')}\n"
        f"Policy: {json.dumps(policy)}"
    )
    reply = call_llm(
        "support",
        "draft_resolution",
        [SystemMessage(content=load_prompt("support_resolution")), HumanMessage(content=context)],
    )
    return {"final_response": reply}


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
    graph.add_node("draft_resolution", draft_resolution)
    graph.set_entry_point("find_order")
    graph.add_conditional_edges(
        "find_order",
        route_support,
        {
            "policy": "answer_policy",
            "ticket": "create_ticket",
            "ask_order": "ask_for_order",
            "cancel": "handle_cancellation",
            "draft": "draft_resolution",
        },
    )
    graph.add_conditional_edges("handle_cancellation", route_cancellation, {"confirm": "confirm_cancel", "done": END})
    graph.add_conditional_edges("confirm_cancel", route_answer, {"cancel": "cancel_order", "keep": "keep_order"})
    for node in ("answer_policy", "ask_for_order", "cancel_order", "keep_order", "create_ticket", "draft_resolution"):
        graph.add_edge(node, END)
    return graph.compile()


support_agent_graph = build_support_agent_graph()
