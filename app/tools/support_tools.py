import uuid
from typing import Optional, List
from app.db.database import SessionLocal
from app.models.support_ticket import SupportTicket, SeverityLevel, TicketStatus, IssueCategory

# Map agent category names → DB enum values
CATEGORY_MAP = {
    "damaged_product":  "defective_product",
    "wrong_item":       "wrong_item",
    "refund":           "refund_request",
    "cancellation":     "other",
    "general_query":    "other",
    # passthrough for existing values
    "defective_product": "defective_product",
    "damaged_delivery":  "damaged_delivery",
    "missing_parts":     "missing_parts",
    "refund_request":    "refund_request",
    "other":             "other",
}

# Map agent severity names → DB enum values
SEVERITY_MAP = {
    "high":     "critical",
    "medium":   "medium",
    "low":      "low",
    "critical": "critical",
}


def get_open_ticket_for_order(user_id: str, order_id: str) -> Optional[dict]:
    """Return the first open/in-progress ticket for this user+order, or None."""
    db = SessionLocal()
    try:
        ticket = (
            db.query(SupportTicket)
            .filter(
                SupportTicket.user_id == user_id,
                SupportTicket.order_id == order_id,
                SupportTicket.status.in_([TicketStatus.open, TicketStatus.in_progress]),
            )
            .order_by(SupportTicket.created_at.desc())
            .first()
        )
        if not ticket:
            return None
        return {
            "ticket_id": ticket.ticket_id,
            "severity":  ticket.severity.value,
            "category":  ticket.category.value,
            "status":    ticket.status.value,
            "priority":  ticket.priority,
            "created_at": ticket.created_at.isoformat(),
        }
    finally:
        db.close()


def create_support_ticket(
    user_id: str,
    severity: str,
    category: str,
    description: str,
    priority: str,
    order_id: Optional[str] = None,
) -> dict:
    db = SessionLocal()
    try:
        ticket_id = f"TKT-{str(uuid.uuid4())[:8].upper()}"

        db_severity = SEVERITY_MAP.get(severity.lower(), "medium")
        db_category = CATEGORY_MAP.get(category.lower(), "other")

        ticket = SupportTicket(
            ticket_id=ticket_id,
            user_id=user_id,
            order_id=order_id,
            severity=SeverityLevel[db_severity],
            status=TicketStatus.open,
            category=IssueCategory[db_category],
            description=description,
            priority=priority,
        )

        db.add(ticket)
        db.commit()
        db.refresh(ticket)

        return {
            "ticket_id":  ticket.ticket_id,
            "severity":   ticket.severity.value,
            "category":   ticket.category.value,
            "status":     ticket.status.value,
            "priority":   ticket.priority,
            "created_at": ticket.created_at.isoformat(),
        }

    finally:
        db.close()


def get_support_ticket(ticket_id: str) -> Optional[dict]:
    db = SessionLocal()
    try:
        ticket = db.query(SupportTicket).filter(
            SupportTicket.ticket_id == ticket_id
        ).first()

        if not ticket:
            return None

        return {
            "ticket_id":   ticket.ticket_id,
            "user_id":     ticket.user_id,
            "order_id":    ticket.order_id,
            "severity":    ticket.severity.value,
            "status":      ticket.status.value,
            "category":    ticket.category.value,
            "priority":    ticket.priority,
            "description": ticket.description,
            "resolution":  ticket.resolution,
            "created_at":  ticket.created_at.isoformat(),
            "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
        }

    finally:
        db.close()


def get_user_ticket_history(user_id: str, limit: int = 10) -> List[dict]:
    db = SessionLocal()
    try:
        tickets = (
            db.query(SupportTicket)
            .filter(SupportTicket.user_id == user_id)
            .order_by(SupportTicket.created_at.desc())
            .limit(limit)
            .all()
        )

        return [{
            "ticket_id": t.ticket_id,
            "order_id":  t.order_id,
            "severity":  t.severity.value,
            "category":  t.category.value,
            "status":    t.status.value,
            "priority":  t.priority,
            "created_at": t.created_at.isoformat(),
        } for t in tickets]

    finally:
        db.close()


def lookup_support_policy(category: str, severity: str) -> dict:
    policies = {
        "damaged_product": {
            "low":    {"response_time": "3-5 days",  "refund_eligible": True, "replacement_eligible": True},
            "medium": {"response_time": "24-48 hours", "refund_eligible": True, "replacement_eligible": True},
            "high":   {"response_time": "12-24 hours", "refund_eligible": True, "replacement_eligible": True},
        },
        "wrong_item": {
            "low":    {"response_time": "3-5 days",  "replacement_eligible": True},
            "medium": {"response_time": "24-48 hours", "replacement_eligible": True},
            "high":   {"response_time": "12-24 hours", "replacement_eligible": True},
        },
        "refund": {
            "low":    {"response_time": "5-7 days",  "refund_eligible": True},
            "medium": {"response_time": "3-5 days",  "refund_eligible": True},
            "high":   {"response_time": "24-48 hours", "refund_eligible": True},
        },
        "cancellation": {
            "low":    {"response_time": "24-48 hours"},
            "medium": {"response_time": "24-48 hours"},
            "high":   {"response_time": "12-24 hours"},
        },
        "general_query": {
            "low":    {"response_time": "48 hours"},
            "medium": {"response_time": "48 hours"},
            "high":   {"response_time": "24 hours"},
        },
    }

    # Normalize category name
    norm = category.lower()
    if norm in ("defective_product", "damaged_delivery", "missing_parts"):
        norm = "damaged_product"
    elif norm == "refund_request":
        norm = "refund"
    elif norm == "other":
        norm = "general_query"

    cat_policy = policies.get(norm, policies["general_query"])
    sev = severity.lower()
    if sev == "critical":
        sev = "high"
    return cat_policy.get(sev, cat_policy.get("medium", {}))
