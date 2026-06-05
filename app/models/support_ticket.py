from sqlalchemy import Boolean, Column, String, DateTime, Enum as SQLEnum, ForeignKey
from sqlalchemy.sql import func
from app.db.database import Base
import enum


class SeverityLevel(enum.Enum):
    low = "low"
    medium = "medium"
    critical = "critical"


class TicketStatus(enum.Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    closed = "closed"


class IssueCategory(enum.Enum):
    defective_product = "defective_product"
    wrong_item = "wrong_item"
    damaged_delivery = "damaged_delivery"
    missing_parts = "missing_parts"
    refund_request = "refund_request"
    other = "other"


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    ticket_id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    order_id = Column(String, ForeignKey("orders.order_id"), nullable=True, index=True)

    severity = Column(SQLEnum(SeverityLevel, values_callable=lambda x: [e.value for e in x]), nullable=False)
    status = Column(
        SQLEnum(TicketStatus, values_callable=lambda x: [e.value for e in x]), default=TicketStatus.open, nullable=False
    )
    category = Column(SQLEnum(IssueCategory, values_callable=lambda x: [e.value for e in x]), nullable=False)

    description = Column(String, nullable=False)
    resolution = Column(String, nullable=True)
    safety_alert = Column(Boolean, nullable=True, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)
