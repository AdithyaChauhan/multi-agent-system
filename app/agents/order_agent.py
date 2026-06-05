import os
import re
import time
from typing import Literal
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from dotenv import load_dotenv

from app.agents.state import AgentState
from app.agents.order_agent_subgraph import shipment_tracking_subgraph
from app.tools.order_tools import fetch_order_from_db, fetch_user_orders
from app.tools.shipment_tools import fetch_tracking_info
from app.core.logger import get_logger, get_request_id
from app.core.metrics import llm_requests_total, llm_tokens_total, llm_duration_seconds

load_dotenv()

logger = get_logger("app.agents.order_agent")

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3, api_key=os.getenv("OPENAI_API_KEY"))


RESPONSE_SYSTEM_PROMPT = """You are a customer service agent for an e-commerce store.
Generate a concise (1-3 sentence) response about the customer's order using ONLY the data below.

Rules:
- "delivered": confirm the order has been delivered; mention tracking ID if available.
- "shipped" / "out_for_delivery": state the current status and estimated delivery if present.
- "processing": say the order is being prepared / will ship soon.
- If live tracking data is "N/A" or missing, rely on the DB status field only.
- NEVER suggest the customer check the website or their account — give the answer directly.
- NEVER invent carrier names, locations, or dates that are not in the data."""


# ==================== HELPER FUNCTIONS ====================


def extract_order_id_from_text(text: str) -> str:
    """Extract order_id from text using regex"""
    pattern = r'\b(ORD-?\d{4})\b'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        order_id = match.group(1).upper()
        # Normalize to ORD-1234 format
        if not order_id.startswith("ORD-"):
            order_id = f"ORD-{order_id.replace('ORD', '')}"
        return order_id
    return None


# ==================== NODES ====================


def check_order_id(state: AgentState) -> dict:
    """
    Smart order_id detection:
    1. Check if Router already extracted order_id
    2. Check conversation history for context
    3. Fetch user's orders from database
    4. Auto-select if user has only 1 order
    """
    user_id = state.get("user_id")
    user_message = state.get("user_message", "")
    conversation_history = state.get("conversation_history", [])
    order_id = state.get("order_id")  # From Router

    # Try to extract from current message
    if not order_id:
        order_id = extract_order_id_from_text(user_message)

    # Check conversation history for context
    if not order_id and conversation_history:
        recent_messages = conversation_history[-4:]

        # Check if assistant recently asked for order_id
        assistant_asked = False
        for msg in reversed(recent_messages):
            if msg.get("role") == "assistant":
                content = msg.get("content", "").lower()
                if any(
                    phrase in content
                    for phrase in ["order id", "order number", "which order", "provide your order", "share your order"]
                ):
                    assistant_asked = True
                    break

        # If asked, try to extract from current message
        if assistant_asked:
            order_id = extract_order_id_from_text(user_message)

            # Bare 4-digit number anywhere in message (e.g. "9905 status", "what about 9901")
            if not order_id:
                match = re.search(r'\b(\d{4})\b', user_message)
                if match:
                    order_id = f"ORD-{match.group(1)}"

    # If we have order_id, return it
    if order_id:
        logger.info(f"request_id={get_request_id()} | Order ID extracted: {order_id}")
        return {"order_id": order_id}

    # Otherwise, fetch user's orders from database
    user_orders = fetch_user_orders(user_id)

    logger.info(f"request_id={get_request_id()} | User has {len(user_orders)} orders")

    if len(user_orders) == 0:
        return {"order_id": None, "user_orders": []}
    elif len(user_orders) == 1:
        logger.info(f"request_id={get_request_id()} | Auto-selected order: {user_orders[0]['order_id']}")
        return {"order_id": user_orders[0]["order_id"], "user_orders": user_orders}

    # Try matching product name from message against order list
    msg_lower = user_message.lower()
    for order in user_orders:
        product_words = [w for w in order.get("product_name", "").lower().split() if len(w) > 3]
        if product_words and any(w in msg_lower for w in product_words):
            logger.info(f"request_id={get_request_id()} | Matched order by product name: {order['order_id']}")
            return {"order_id": order["order_id"], "user_orders": user_orders}

    return {"order_id": None, "user_orders": user_orders}


def respond_no_orders(state: AgentState) -> dict:
    """User has no orders in database"""
    logger.info(f"request_id={get_request_id()} | No orders found for user")
    return {"final_response": "I couldn't find any orders on your account. Have you placed an order with us recently?"}


def ask_which_order(state: AgentState) -> dict:
    """User has multiple orders, ask which one"""
    user_orders = state.get("user_orders", [])

    logger.info(f"request_id={get_request_id()} | Asking user to select from {len(user_orders)} orders")

    shown = user_orders[:5]
    order_list = "\n".join([f"• **{o['order_id']}** - {o['product_name']} ({o['status']})" for o in shown])
    footer = f"\n\n_(showing {len(shown)} most recent of {len(user_orders)} orders)_" if len(user_orders) > 5 else ""

    return {
        "final_response": f"You have multiple orders. Which one would you like to check?\n\n{order_list}{footer}\n\nPlease provide the order ID."
    }


def fetch_order(state: AgentState) -> dict:
    """Fetch order from database using order_id and user_id"""
    order_id = state.get("order_id")
    user_id = state.get("user_id")

    order = fetch_order_from_db(order_id, user_id)

    if not order:
        return {"order_data": None}

    return {"order_data": order}


def respond_not_found(state: AgentState) -> dict:
    """Order not found for this user"""
    order_id = state.get("order_id")
    logger.info(f"request_id={get_request_id()} | Order not found: {order_id}")
    return {
        "final_response": f"I couldn't find order **{order_id}** on your account. Please double-check the order ID."
    }


# ── Order tool + ToolNode ─────────────────────────────────────────────────────


@tool
def get_live_tracking(tracking_id: str) -> str:
    """
    Fetch live shipment tracking information from the carrier API.
    Use this when you need real-time delivery status for a tracking ID.
    Returns carrier, current location, live status, and estimated delivery as JSON.
    """
    import json

    info = fetch_tracking_info(tracking_id)
    if not info:
        return json.dumps({"error": "No live tracking data available."})
    return json.dumps(info)


_order_tools = [get_live_tracking]
order_tool_node = ToolNode(_order_tools)


def response_generation(state: AgentState) -> dict:
    """LLM node — generates natural language response; can call get_live_tracking tool."""
    order_data = state.get("order_data") or {}
    tracking_data = state.get("tracking_data") or {}
    conversation_history = state.get("conversation_history", [])

    # Deterministic short-circuit for delivered orders — no LLM needed,
    # avoids "check your account" hallucinations when tracking data is N/A.
    status = (order_data.get("status") or "").lower()
    if status == "delivered":
        product = order_data.get("product_name", "Your order")
        tracking_id = tracking_data.get("tracking_id") or order_data.get("tracking_id")
        msg = f"Good news! **{product}** (Order {order_data.get('order_id')}) has been delivered."
        if tracking_id and tracking_id != "N/A":
            msg += f" Tracking reference: {tracking_id}."
        return {"final_response": msg}

    # Build conversation context
    history_context = ""
    if conversation_history:
        recent = conversation_history[-4:]
        history_context = "\n".join([f"{msg['role'].title()}: {msg['content']}" for msg in recent])

    context = f"""
{"Recent conversation:" + chr(10) + history_context + chr(10) if history_context else ""}
Order details:
- Order ID: {order_data.get('order_id')}
- Product: {order_data.get('product_name')}
- Status: {order_data.get('status')}
- Carrier: {tracking_data.get('carrier', 'Not assigned')}
- Tracking ID: {tracking_data.get('tracking_id', 'N/A')}
- Live status: {tracking_data.get('live_status', 'N/A')}
- Current location: {tracking_data.get('current_location', 'N/A')}
- Estimated delivery: {tracking_data.get('estimated_delivery', 'N/A')}

User asked: {state.get('user_message')}"""

    call_messages = [
        SystemMessage(content=RESPONSE_SYSTEM_PROMPT),
        HumanMessage(content=context),
    ]

    _t0 = time.perf_counter()
    response = llm.bind_tools(_order_tools).invoke(call_messages)
    _latency_s = time.perf_counter() - _t0
    _latency_ms = int(_latency_s * 1000)
    _meta = getattr(response, "response_metadata", {})
    _usage = _meta.get("token_usage", {}) if isinstance(_meta, dict) else {}
    logger.info(
        f"request_id={get_request_id()} | LLM_USAGE | agent=order | node=response_generation"
        f" | prompt_tokens={_usage.get('prompt_tokens', 0)}"
        f" | completion_tokens={_usage.get('completion_tokens', 0)}"
        f" | total_tokens={_usage.get('total_tokens', 0)}"
        f" | latency_ms={_latency_ms}"
    )
    llm_requests_total.labels(agent="order", node="response_generation").inc()
    llm_duration_seconds.labels(agent="order", node="response_generation").observe(_latency_s)
    llm_tokens_total.labels(agent="order", node="response_generation", token_type="prompt").inc(
        _usage.get("prompt_tokens", 0)
    )
    llm_tokens_total.labels(agent="order", node="response_generation", token_type="completion").inc(
        _usage.get("completion_tokens", 0)
    )
    llm_tokens_total.labels(agent="order", node="response_generation", token_type="total").inc(
        _usage.get("total_tokens", 0)
    )

    # If LLM called the tracking tool, route to ToolNode; otherwise generate final response
    if getattr(response, "tool_calls", None):
        logger.info(f"request_id={get_request_id()} | Calling order tool")
        return {"messages": [response]}

    logger.info(f"request_id={get_request_id()} | Response generated")
    return {"final_response": response.content.strip()}


def finalize_order_response(state: AgentState) -> dict:
    """Deterministic node: after ToolNode returns live tracking, generate final response."""
    import json as _json

    order_data = state.get("order_data") or {}
    tracking_data = state.get("tracking_data") or {}
    messages = state.get("messages") or []

    # Collect any live tracking data returned by the tool
    extra = ""
    for msg in messages:
        if isinstance(msg, ToolMessage):
            try:
                live = _json.loads(msg.content)
                if isinstance(live, dict) and "error" not in live:
                    extra = f"\nLive carrier data: {msg.content}"
            except (ValueError, TypeError):
                pass

    history_context = ""
    conv = state.get("conversation_history", [])
    if conv:
        history_context = "\n".join([f"{m['role'].title()}: {m['content']}" for m in conv[-4:]])

    context = f"""
{"Recent conversation:" + chr(10) + history_context + chr(10) if history_context else ""}
Order details:
- Order ID: {order_data.get('order_id')}
- Product: {order_data.get('product_name')}
- Status: {order_data.get('status')}
- Carrier: {tracking_data.get('carrier', 'Not assigned')}
- Tracking ID: {tracking_data.get('tracking_id', 'N/A')}
- Live status: {tracking_data.get('live_status', 'N/A')}
- Current location: {tracking_data.get('current_location', 'N/A')}
- Estimated delivery: {tracking_data.get('estimated_delivery', 'N/A')}{extra}

User asked: {state.get('user_message')}"""

    response = llm.invoke([SystemMessage(content=RESPONSE_SYSTEM_PROMPT), HumanMessage(content=context)])
    logger.info(f"request_id={get_request_id()} | Response generated (post-tool)")
    return {"final_response": response.content.strip()}


def route_to_order_tool(state: AgentState) -> Literal["order_tools", "end"]:
    messages = state.get("messages") or []
    if messages and getattr(messages[-1], "tool_calls", None):
        return "order_tools"
    return "end"


# ==================== ROUTING ====================


def route_after_check(state: AgentState) -> Literal["has_id", "no_orders", "multiple_orders"]:
    """Route based on order_id detection"""
    order_id = state.get("order_id")
    user_orders = state.get("user_orders", [])

    if order_id:
        return "has_id"
    elif len(user_orders) == 0:
        return "no_orders"
    else:
        return "multiple_orders"


def route_after_fetch(state: AgentState) -> Literal["found", "not_found"]:
    """Route based on whether order was found"""
    return "found" if state.get("order_data") else "not_found"


# ==================== GRAPH ====================


def build_order_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("check_order_id", check_order_id)
    graph.add_node("respond_no_orders", respond_no_orders)
    graph.add_node("ask_which_order", ask_which_order)
    graph.add_node("fetch_order", fetch_order)
    graph.add_node("respond_not_found", respond_not_found)
    graph.add_node("shipment_tracking", shipment_tracking_subgraph)
    graph.add_node("response_generation", response_generation)
    graph.add_node("order_tools", order_tool_node)
    graph.add_node("finalize_order_response", finalize_order_response)

    graph.set_entry_point("check_order_id")

    graph.add_conditional_edges(
        "check_order_id",
        route_after_check,
        {
            "has_id": "fetch_order",
            "no_orders": "respond_no_orders",
            "multiple_orders": "ask_which_order",
        },
    )

    graph.add_conditional_edges(
        "fetch_order",
        route_after_fetch,
        {
            "found": "shipment_tracking",
            "not_found": "respond_not_found",
        },
    )

    graph.add_edge("respond_no_orders", END)
    graph.add_edge("ask_which_order", END)
    graph.add_edge("respond_not_found", END)
    graph.add_edge("shipment_tracking", "response_generation")
    graph.add_conditional_edges(
        "response_generation",
        route_to_order_tool,
        {"order_tools": "order_tools", "end": END},
    )
    graph.add_edge("order_tools", "finalize_order_response")
    graph.add_edge("finalize_order_response", END)

    return graph.compile()


order_agent_graph = build_order_agent_graph()
