"""Order status. No LLM: the router has already resolved which order the user means,
and order data must be reported exactly as stored."""

from typing import Literal

from langgraph.graph import END, StateGraph

from app.agents.state import AgentState
from app.core.logger import get_logger, get_request_id
from app.tools.order_tools import fetch_order_from_db, fetch_user_orders
from app.tools.shipment_tools import fetch_tracking_info

logger = get_logger("app.agents.order_agent")


def find_order(state: AgentState) -> dict:
    """Look the order up for this user only. With no order named, a single order is used."""
    user_id = state.get("user_id", "")
    order_id = state.get("order_id")
    orders = fetch_user_orders(user_id)
    if not order_id and len(orders) == 1:
        order_id = orders[0]["order_id"]
    order = fetch_order_from_db(order_id, user_id) if order_id else None
    logger.info(f"request_id={get_request_id()} | order lookup | order_id={order_id} | found={bool(order)}")
    return {"order_id": order_id, "order_data": order, "user_orders": orders}


def route_after_find(state: AgentState) -> Literal["status", "not_found", "no_orders", "list"]:
    if state.get("order_data"):
        return "status"
    if state.get("order_id"):
        return "not_found"
    return "list" if state.get("user_orders") else "no_orders"


def order_lines(orders: list, numbered: bool) -> str:
    shown = orders[:5]
    if numbered:
        lines = [
            f"{i}. **{o['order_id']}** — {o['product_name'][:60]} ({o['status'].title()})"
            for i, o in enumerate(shown, 1)
        ]
    else:
        lines = [f"• **{o['order_id']}** - {o['product_name']} ({o['status']})" for o in shown]
    footer = f"\n_(showing {len(shown)} most recent of {len(orders)} orders)_" if len(orders) > 5 else ""
    return "\n".join(lines) + footer


def list_orders(state: AgentState) -> dict:
    orders = state.get("user_orders") or []
    return {
        "final_response": "You have multiple orders. Which one would you like to check?\n\n"
        f"{order_lines(orders, numbered=False)}\n\nPlease provide the order ID."
    }


def respond_no_orders(state: AgentState) -> dict:
    return {"final_response": "I couldn't find any orders on your account. Have you placed an order with us recently?"}


def respond_not_found(state: AgentState) -> dict:
    order_id = state.get("order_id")
    orders = state.get("user_orders") or []
    if not orders:
        return {
            "final_response": f"I couldn't find order **{order_id}** on your account. Please double-check the order ID."
        }
    return {
        "final_response": f"I couldn't find order **{order_id}** on your account. Here are your recent orders:\n\n"
        f"{order_lines(orders, numbered=True)}\n\nPlease reply with the order number you need help with."
    }


def order_status(state: AgentState) -> dict:
    """Status from the database, plus live carrier data when the tracking API has it."""
    order = state.get("order_data") or {}
    status = (order.get("status") or "").lower().replace(" ", "_")
    what = f"**{order.get('product_name')}** (order {order.get('order_id')})"
    tracking_id = order.get("tracking_id")
    live = fetch_tracking_info(tracking_id) if tracking_id else None

    if status == "delivered":
        reply = f"Good news! {what} has been delivered."
    elif status in ("shipped", "in_transit", "out_for_delivery"):
        reply = f"{what} is out for delivery" if status == "out_for_delivery" else f"{what} has shipped"
        if order.get("carrier"):
            reply += f" with {order['carrier']}"
        reply += "."
        if live:
            details = [live.get("status"), live.get("current_location") and f"at {live['current_location']}"]
            reply += " Latest update: " + " ".join(d for d in details if d) + "."
            if live.get("estimated_delivery"):
                reply += f" Expected delivery: {live['estimated_delivery']}."
    elif status in ("processing", "placed"):
        reply = f"{what} is being prepared and hasn't shipped yet."
    elif status in ("cancelled", "canceled"):
        reply = f"{what} was cancelled."
    else:
        reply = f"{what} has status: {order.get('status')}."
    if tracking_id and status not in ("processing", "placed", "cancelled", "canceled"):
        reply += f" Tracking ID: {tracking_id}."
    return {"final_response": reply, "tracking_data": live or {}}


def build_order_agent_graph():
    graph = StateGraph(AgentState)
    graph.add_node("find_order", find_order)
    graph.add_node("order_status", order_status)
    graph.add_node("respond_not_found", respond_not_found)
    graph.add_node("respond_no_orders", respond_no_orders)
    graph.add_node("list_orders", list_orders)
    graph.set_entry_point("find_order")
    graph.add_conditional_edges(
        "find_order",
        route_after_find,
        {
            "status": "order_status",
            "not_found": "respond_not_found",
            "no_orders": "respond_no_orders",
            "list": "list_orders",
        },
    )
    for node in ("order_status", "respond_not_found", "respond_no_orders", "list_orders"):
        graph.add_edge(node, END)
    return graph.compile()


order_agent_graph = build_order_agent_graph()
