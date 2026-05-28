"""
Escalation Handler Subgraph — Agent 3 (Support)

Handles HIGH and MEDIUM severity issues:
  check_history   → is_repeat_complainant (open ticket for same order?)
  assign_priority → URGENT / HIGH / MEDIUM
  create_ticket   → duplicate check → create or return existing ticket
"""

from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.tools.support_tools import (
    create_support_ticket,
    get_open_ticket_for_order,
    get_user_ticket_history,
)
from app.core.logger import get_logger, get_request_id

logger = get_logger("app.agents.support_agent_subgraph")


def check_history(state: AgentState) -> dict:
    """
    Checks if the user already has an open ticket for this same order.
    is_repeat_complainant = True only when an open/in-progress ticket
    exists for the exact same order_id.
    """
    user_id = state.get("user_id", "")
    support_order = state.get("support_order") or {}
    order_id = support_order.get("order_id")

    history = get_user_ticket_history(user_id, limit=10)

    is_repeat = False
    if order_id:
        is_repeat = any(
            t.get("order_id") == order_id and t.get("status") in ("open", "in_progress")
            for t in history
        )

    logger.info(
        f"request_id={get_request_id()} | "
        f"History check | tickets={len(history)} | is_repeat={is_repeat} | order_id={order_id}"
    )
    return {
        "ticket_history": history,
        "recent_critical_count": int(is_repeat),  # reuse existing state field
    }


def assign_priority(state: AgentState) -> dict:
    """
    Priority matrix:
      HIGH   + repeat → URGENT
      HIGH   + first  → HIGH
      MEDIUM + repeat → HIGH
      MEDIUM + first  → MEDIUM
    """
    severity = state.get("severity", "medium")
    is_repeat = bool(state.get("recent_critical_count", 0))

    if severity == "high" and is_repeat:
        priority = "URGENT"
    elif severity == "high":
        priority = "HIGH"
    elif severity == "medium" and is_repeat:
        priority = "HIGH"
    else:
        priority = "MEDIUM"

    logger.info(
        f"request_id={get_request_id()} | "
        f"Priority | severity={severity} | is_repeat={is_repeat} | priority={priority}"
    )
    return {"priority": priority}


def create_ticket_node(state: AgentState) -> dict:
    """
    Duplicate check first — if an open ticket already exists for this order,
    return it instead of creating a new one.
    Otherwise create a fresh ticket and draft a response.
    """
    issue = state.get("support_issue", {})
    support_order = state.get("support_order") or {}
    user_id = state.get("user_id", "")
    severity = state.get("severity", "medium")
    priority = state.get("priority", "MEDIUM")
    policy = state.get("policy", {})
    order_id = support_order.get("order_id")
    product_name = support_order.get("product_name", "your product")

    # ── Duplicate check ──────────────────────────────────────────────────
    if order_id:
        existing = get_open_ticket_for_order(user_id, order_id)
        if existing:
            logger.info(
                f"request_id={get_request_id()} | "
                f"Duplicate ticket found | ticket_id={existing['ticket_id']}"
            )
            return {
                "final_response": (
                    f"You already have an open ticket **{existing['ticket_id']}** for this order.\n\n"
                    f"**Status:** {existing['status'].replace('_', ' ').title()}\n"
                    f"**Priority:** {existing.get('priority', 'MEDIUM')}\n\n"
                    f"Our team is already working on it. "
                    f"You'll be contacted within {policy.get('response_time', '24-48 hours')}."
                )
            }

    # ── Create new ticket ─────────────────────────────────────────────────
    ticket = create_support_ticket(
        user_id=user_id,
        severity=severity,
        category=issue.get("category", "general_query"),
        description=f"[{priority}] {issue.get('description', '')}",
        priority=priority,
        order_id=order_id,
    )

    logger.info(
        f"request_id={get_request_id()} | "
        f"Ticket created | ticket_id={ticket['ticket_id']} | priority={priority}"
    )

    response_time = policy.get("response_time", "24-48 hours")
    category_display = (issue.get("category") or "issue").replace("_", " ").title()

    response = (
        f"I've raised a support ticket for your {category_display.lower()} with "
        f"**{product_name}**.\n\n"
        f"**Ticket ID:** {ticket['ticket_id']}\n"
        f"**Priority:** {priority}\n"
        f"**Response time:** {response_time}\n\n"
        f"Our support team will reach out to you within {response_time}. "
        f"You'll receive updates at your registered email address."
    )

    return {"final_response": response}


def build_escalation_subgraph():
    subgraph = StateGraph(AgentState)

    subgraph.add_node("check_history",  check_history)
    subgraph.add_node("assign_priority", assign_priority)
    subgraph.add_node("create_ticket",  create_ticket_node)

    subgraph.set_entry_point("check_history")
    subgraph.add_edge("check_history",   "assign_priority")
    subgraph.add_edge("assign_priority", "create_ticket")
    subgraph.add_edge("create_ticket",   END)

    return subgraph.compile()


escalation_handler_subgraph = build_escalation_subgraph()
