"""Hand an issue to a person: open a ticket, then alert the support team.

One subgraph for every escalation: safety reports from the router (ADR 0008) and refunds, damage,
wrong items and legal threats from the support agent. The ticket stays open, waiting for a person;
answering it from an admin page comes in Phase 5.

The alert goes to ESCALATION_WEBHOOK_URL when it is set (a Slack or Discord incoming webhook),
otherwise to the log. A failed alert never blocks the shopper's reply: the ticket is already saved.
"""

from typing import Optional, TypedDict

import httpx
from langgraph.graph import END, StateGraph

from app.core.config import ESCALATION_WEBHOOK_URL
from app.core.logger import get_logger, get_request_id
from app.tools.support_tools import create_support_ticket

logger = get_logger("app.agents.escalation")


class EscalationInput(TypedDict, total=False):
    # user_id, severity, category, description, and optionally order_id and safety_alert
    escalation: Optional[dict]


class EscalationOutput(TypedDict, total=False):
    ticket: Optional[dict]


class EscalationState(EscalationInput, EscalationOutput, total=False):
    pass


def open_ticket(state: EscalationState) -> dict:
    ticket = create_support_ticket(**state["escalation"])
    logger.info(f"request_id={get_request_id()} | ticket opened | {ticket['ticket_id']} | {ticket.get('severity')}")
    return {"ticket": ticket}


def alert_text(request: dict, ticket: dict) -> str:
    severity = str(request.get("severity", "")).upper()
    order = f" | order {request['order_id']}" if request.get("order_id") else ""
    return (
        f"[{severity}] {ticket['ticket_id']} | {request.get('category')}{order} | user {request.get('user_id')}\n"
        f"{str(request.get('description', ''))[:300]}"
    )


def alert_payload(text: str) -> dict:
    """Slack reads "text", Discord reads "content"; each ignores the other. The shopper's words are in
    the text, so Discord must not turn "@everyone" or a role name in them into a ping."""
    return {"text": text, "content": text, "allowed_mentions": {"parse": []}}


def notify(state: EscalationState) -> dict:
    """Alert the team. The ticket records whether the alert went out, so the reply can say so."""
    ticket = state["ticket"]
    text = alert_text(state["escalation"], ticket)
    if not ESCALATION_WEBHOOK_URL:
        logger.warning(f"request_id={get_request_id()} | ESCALATION | {text}")
        return {"ticket": {**ticket, "alerted": False}}
    try:
        httpx.post(ESCALATION_WEBHOOK_URL, json=alert_payload(text), timeout=3).raise_for_status()
        logger.info(f"request_id={get_request_id()} | escalation alert sent | {ticket['ticket_id']}")
        return {"ticket": {**ticket, "alerted": True}}
    except Exception as exc:  # the ticket exists either way; a person will still find it
        logger.error(f"request_id={get_request_id()} | escalation alert failed | {type(exc).__name__} | {text}")
        return {"ticket": {**ticket, "alerted": False}}


def build_escalation_graph():
    graph = StateGraph(EscalationState, input_schema=EscalationInput, output_schema=EscalationOutput)
    graph.add_node("open_ticket", open_ticket)
    graph.add_node("notify", notify)
    graph.set_entry_point("open_ticket")
    graph.add_edge("open_ticket", "notify")
    graph.add_edge("notify", END)
    return graph.compile()


escalation_graph = build_escalation_graph()
