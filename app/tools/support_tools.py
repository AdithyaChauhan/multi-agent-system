import uuid
from typing import Optional, List
from app.db.database import SessionLocal
from app.models.support_ticket import SupportTicket, SeverityLevel, TicketStatus, IssueCategory


def create_support_ticket(
    user_id: str,
    severity: str,
    category: str,
    description: str,
    order_id: Optional[str] = None,
) -> dict:
    """
    Create a support ticket in the database.

    Args:
        user_id: User ID
        severity: "low", "medium", or "critical"
        category: Issue category
        description: Problem description
        order_id: Optional order ID if issue is order-related

    Returns:
        Dict with ticket details
    """
    db = SessionLocal()
    try:
        ticket_id = f"TKT-{str(uuid.uuid4())[:8].upper()}"

        ticket = SupportTicket(
            ticket_id=ticket_id,
            user_id=user_id,
            order_id=order_id,
            severity=SeverityLevel[severity.lower()],
            status=TicketStatus.open,
            category=IssueCategory[category.lower()],
            description=description,
        )

        db.add(ticket)
        db.commit()
        db.refresh(ticket)

        return {
            "ticket_id": ticket.ticket_id,
            "severity": ticket.severity.value,
            "category": ticket.category.value,
            "status": ticket.status.value,
            "created_at": ticket.created_at.isoformat(),
        }

    finally:
        db.close()


def get_support_ticket(ticket_id: str) -> Optional[dict]:
    """Get support ticket by ID"""
    db = SessionLocal()
    try:
        ticket = db.query(SupportTicket).filter(SupportTicket.ticket_id == ticket_id).first()

        if not ticket:
            return None

        return {
            "ticket_id": ticket.ticket_id,
            "user_id": ticket.user_id,
            "order_id": ticket.order_id,
            "severity": ticket.severity.value,
            "status": ticket.status.value,
            "category": ticket.category.value,
            "description": ticket.description,
            "resolution": ticket.resolution,
            "created_at": ticket.created_at.isoformat(),
            "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
        }

    finally:
        db.close()


def get_user_ticket_history(user_id: str, limit: int = 10) -> List[dict]:
    """
    Get user's support ticket history.

    Args:
        user_id: User ID
        limit: Maximum number of tickets to return

    Returns:
        List of ticket dictionaries
    """
    db = SessionLocal()
    try:
        tickets = (
            db.query(SupportTicket)
            .filter(SupportTicket.user_id == user_id)
            .order_by(SupportTicket.created_at.desc())
            .limit(limit)
            .all()
        )

        return [
            {
                "ticket_id": t.ticket_id,
                "severity": t.severity.value,
                "category": t.category.value,
                "status": t.status.value,
                "created_at": t.created_at.isoformat(),
            }
            for t in tickets
        ]

    finally:
        db.close()


def lookup_support_policy(category: str, severity: str) -> dict:
    """
    Look up company policy for handling this type of issue.

    Args:
        category: Issue category
        severity: Severity level

    Returns:
        Policy details (response time, escalation rules, etc.)
    """
    policies = {
        "defective_product": {
            "low": {
                "response_time": "24-48 hours",
                "auto_resolve": True,
                "replacement_eligible": True,
                "refund_eligible": True,
            },
            "medium": {
                "response_time": "12-24 hours",
                "auto_resolve": False,
                "replacement_eligible": True,
                "refund_eligible": True,
            },
            "critical": {
                "response_time": "1 hour",
                "auto_resolve": False,
                "escalate_immediately": True,
                "replacement_eligible": True,
                "refund_eligible": True,
            },
        },
        "damaged_delivery": {
            "low": {"response_time": "48 hours", "auto_resolve": True, "refund_eligible": True},
            "medium": {"response_time": "24 hours", "auto_resolve": False, "refund_eligible": True},
            "critical": {"response_time": "1 hour", "escalate_immediately": True, "refund_eligible": True},
        },
        "wrong_item": {
            "low": {"response_time": "48 hours", "auto_resolve": True, "replacement_eligible": True},
            "medium": {"response_time": "24 hours", "auto_resolve": False, "replacement_eligible": True},
            "critical": {"response_time": "2 hours", "escalate_immediately": True, "replacement_eligible": True},
        },
        "refund_request": {
            "low": {"response_time": "3-5 days", "auto_resolve": False, "refund_eligible": True},
            "medium": {"response_time": "2-3 days", "auto_resolve": False, "refund_eligible": True},
            "critical": {"response_time": "24 hours", "escalate_immediately": False, "refund_eligible": True},
        },
        "missing_parts": {
            "low": {"response_time": "48 hours", "auto_resolve": True, "replacement_eligible": True},
            "medium": {"response_time": "24 hours", "auto_resolve": False, "replacement_eligible": True},
            "critical": {"response_time": "4 hours", "escalate_immediately": True, "replacement_eligible": True},
        },
        "other": {
            "low": {"response_time": "48 hours", "auto_resolve": True},
            "medium": {"response_time": "24 hours", "auto_resolve": False},
            "critical": {"response_time": "4 hours", "escalate_immediately": True},
        },
    }

    category_policy = policies.get(category, policies["other"])
    return category_policy.get(severity, category_policy.get("medium", {}))
