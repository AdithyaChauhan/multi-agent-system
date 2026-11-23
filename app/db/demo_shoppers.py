"""One-click demo shoppers (Phase 5, ADR 0016): a fresh account with its own orders per visitor.

A judge who presses "Try as a demo shopper" gets `demo-<8 hex>` with five orders in different states,
so tracking, damage reports and cancelling all work, and two visitors never touch each other's orders.
Visitors are deleted after DEMO_SHOPPER_DAYS. They are ordinary users to the rest of the app: every
ownership check (ADR 0002) applies.
"""

import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.logger import get_logger
from app.models.message import Message
from app.models.order import Order
from app.models.session import Session
from app.models.support_ticket import SupportTicket
from app.models.user import User

logger = get_logger("app.db.demo_shoppers")

PREFIX = "demo-"
DEMO_SHOPPER_DAYS = 2
PER_IP_PER_HOUR = 5

# (product name, status, carrier, tracking id): tracking ids the mock carrier API knows.
ORDERS = (
    ("Philips GC1920/28 1440W Steam Iron", "delivered", "FakeExpress", "TRK-9002"),
    ("boAt Rockerz 255 Pro+ Bluetooth Neckband", "in transit", "FakeExpress", "TRK-9001"),
    ("Mi 108cm Full HD Android LED TV", "shipped", "FakeExpress", "TRK-9003"),
    ("Logitech M221 Wireless Mouse", "processing", None, None),
    ("Havells Aqua Plus 1.2L Electric Kettle", "processing", None, None),
)

_lock = threading.Lock()
_created_by_ip: dict = defaultdict(deque)


def is_demo_shopper(user_id: str) -> bool:
    return user_id.startswith(PREFIX) and not user_id.startswith("demo-user-")


def allow_new_shopper(client_ip: Optional[str]) -> bool:
    """At most PER_IP_PER_HOUR new shoppers per address, so the button can't fill the database."""
    now = time.monotonic()
    with _lock:
        recent = _created_by_ip[client_ip or "unknown"]
        while recent and now - recent[0] > 3600:
            recent.popleft()
        if len(recent) >= PER_IP_PER_HOUR:
            return False
        recent.append(now)
        return True


def _new_order_id(db) -> str:
    for _ in range(20):
        candidate = f"ORD-{secrets.randbelow(90000) + 10000}"
        if not db.query(Order).filter(Order.order_id == candidate).first():
            return candidate
    raise RuntimeError("could not find a free order id")


def create_demo_shopper(db) -> tuple:
    """A new demo user with its five orders. Returns (user_id, [order ids])."""
    user_id = f"{PREFIX}{secrets.token_hex(4)}"
    db.add(User(user_id=user_id, auth_provider="demo", name="Demo shopper"))
    order_ids = []
    for product, status, carrier, tracking in ORDERS:
        order_id = _new_order_id(db)
        db.add(
            Order(
                order_id=order_id,
                user_id=user_id,
                product_name=product,
                status=status,
                carrier=carrier,
                tracking_id=tracking,
            )
        )
        db.flush()
        order_ids.append(order_id)
    db.commit()
    logger.info(f"demo shopper created | user_id={user_id} | orders={order_ids}")
    return user_id, order_ids


def purge_old_demo_shoppers(db, days: int = DEMO_SHOPPER_DAYS) -> int:
    """Delete demo shoppers older than `days`, with their orders, tickets, chats and sessions."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    old = [
        u.user_id
        for u in db.query(User).filter(User.user_id.like(f"{PREFIX}%"), User.created_at < cutoff).all()
        if is_demo_shopper(u.user_id)
    ]
    if not old:
        return 0
    sessions = [s.session_id for s in db.query(Session).filter(Session.user_id.in_(old)).all()]
    if sessions:
        db.query(Message).filter(Message.session_id.in_(sessions)).delete(synchronize_session=False)
        db.query(Session).filter(Session.session_id.in_(sessions)).delete(synchronize_session=False)
    db.query(SupportTicket).filter(SupportTicket.user_id.in_(old)).delete(synchronize_session=False)
    db.query(Order).filter(Order.user_id.in_(old)).delete(synchronize_session=False)
    db.query(User).filter(User.user_id.in_(old)).delete(synchronize_session=False)
    db.commit()
    logger.info(f"purged {len(old)} demo shoppers older than {days} days")
    return len(old)
