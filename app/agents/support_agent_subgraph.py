"""
Escalation Handler Subgraph for Agent 3 (Support & Resolution)

Handles high-severity issues (medium/critical) with:
1. check_history - Load user's ticket history
2. assign_priority - Assign P0/P1/P2 based on severity + history
3. create_ticket - Create support ticket in database
"""

from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.tools.support_tools import create_support_ticket, get_user_ticket_history
from app.core.logger import get_logger, get_request_id

logger = get_logger("app.agents.support_agent_subgraph")


def check_history(state: AgentState) -> dict:
    """Check user's ticket history"""
    user_id = state.get("user_id", "")
    
    history = get_user_ticket_history(user_id, limit=5)
    
    # Count recent critical tickets
    recent_critical = sum(1 for t in history if t.get("severity") == "critical")
    
    logger.info(
        f"request_id={get_request_id()} | "
        f"Checked history | total_tickets={len(history)} | recent_critical={recent_critical}"
    )
    
    return {
        "ticket_history": history,
        "recent_critical_count": recent_critical,
    }


def assign_priority(state: AgentState) -> dict:
    """Assign priority based on severity and history"""
    severity = state.get("severity", "medium")
    recent_critical = state.get("recent_critical_count", 0)
    
    # Escalate priority if user has multiple recent critical issues
    if severity == "critical" and recent_critical >= 2:
        priority = "P0"  # Highest priority
    elif severity == "critical":
        priority = "P1"
    elif severity == "medium":
        priority = "P2"
    else:
        priority = "P3"
    
    logger.info(
        f"request_id={get_request_id()} | "
        f"Assigned priority | priority={priority} | severity={severity}"
    )
    
    return {"priority": priority}


def create_ticket_node(state: AgentState) -> dict:
    """Create support ticket in database"""
    issue = state.get("support_issue", {})
    user_id = state.get("user_id", "")
    severity = state.get("severity", "medium")
    priority = state.get("priority", "P2")
    policy = state.get("policy", {})
    
    # Create ticket
    ticket = create_support_ticket(
        user_id=user_id,
        severity=severity,
        category=issue.get("category", "other"),
        description=f"[{priority}] {issue.get('description', '')}",
        order_id=issue.get("order_id"),
    )
    
    logger.info(
        f"request_id={get_request_id()} | "
        f"Ticket created | ticket_id={ticket['ticket_id']} | priority={priority}"
    )
    
    # Format response based on severity
    if severity == "critical":
        response = (
            f"🚨 **URGENT ISSUE ESCALATED** 🚨\n\n"
            f"Ticket ID: **{ticket['ticket_id']}**\n"
            f"Priority: **{priority}**\n\n"
            f"I've immediately flagged this as a critical issue. "
            f"Our emergency support team will contact you within {policy.get('response_time', '1 hour')} "
            f"via phone and email.\n\n"
            f"**Issue:** {issue.get('description')}\n\n"
            f"If this is a safety emergency, please also contact:\n"
            f"• Emergency hotline: 1-800-SUPPORT\n"
            f"• Email: urgent@support.com"
        )
    else:
        category_display = (issue.get("category") or "other").replace("_", " ").title()
        response = (
            f"I've created a support ticket: **{ticket['ticket_id']}**\n\n"
            f"**Issue:** {issue.get('description')}\n"
            f"**Category:** {category_display}\n"
            f"**Priority:** {priority}\n"
            f"**Response Time:** {policy.get('response_time', '24 hours')}\n\n"
            f"Our support team will review this and contact you. "
            f"You'll receive email updates at your registered address."
        )
    
    return {"final_response": response}


def build_escalation_subgraph():
    """Build the escalation handler subgraph"""
    subgraph = StateGraph(AgentState)
    
    subgraph.add_node("check_history", check_history)
    subgraph.add_node("assign_priority", assign_priority)
    subgraph.add_node("create_ticket", create_ticket_node)
    
    subgraph.set_entry_point("check_history")
    
    subgraph.add_edge("check_history", "assign_priority")
    subgraph.add_edge("assign_priority", "create_ticket")
    subgraph.add_edge("create_ticket", END)
    
    return subgraph.compile()


# Export the compiled subgraph
escalation_handler_subgraph = build_escalation_subgraph()