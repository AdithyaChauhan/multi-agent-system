"""One-click demo shoppers (ADR 0016): each visitor gets their own account and orders."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.jwt_utils import verify_access_token
from app.db import demo_shoppers
from app.db.database import SessionLocal
from app.models.order import Order
from app.models.user import User


@pytest.fixture(autouse=True)
def _fresh_ip_counts():
    demo_shoppers._created_by_ip.clear()
    yield
    demo_shoppers._created_by_ip.clear()


def test_each_click_gets_its_own_shopper_and_orders(client):
    first = client.post("/auth/demo-shopper").json()
    second = client.post("/auth/demo-shopper").json()
    assert first["user_id"] != second["user_id"]
    assert first["user_id"].startswith("demo-") and demo_shoppers.is_demo_shopper(first["user_id"])
    assert verify_access_token(first["access_token"])["sub"] == first["user_id"]
    assert len(first["orders"]) == 5 and not set(first["orders"]) & set(second["orders"])

    db = SessionLocal()
    statuses = sorted(o.status for o in db.query(Order).filter(Order.user_id == first["user_id"]))
    db.close()
    assert statuses == ["delivered", "in transit", "processing", "processing", "shipped"]


def test_limit_per_address(client):
    codes = [client.post("/auth/demo-shopper").status_code for _ in range(demo_shoppers.PER_IP_PER_HOUR + 1)]
    assert codes[:-1] == [200] * demo_shoppers.PER_IP_PER_HOUR and codes[-1] == 429


def test_old_shoppers_are_purged_with_their_orders(client):
    db = SessionLocal()
    db.add(
        User(user_id="demo-0ldv1s1t", auth_provider="demo", created_at=datetime.now(timezone.utc) - timedelta(days=5))
    )
    db.add(Order(order_id="ORD-99901", user_id="demo-0ldv1s1t", product_name="x", status="processing"))
    db.commit()
    assert demo_shoppers.purge_old_demo_shoppers(db) >= 1
    assert db.query(User).filter(User.user_id == "demo-0ldv1s1t").first() is None
    assert db.query(Order).filter(Order.order_id == "ORD-99901").first() is None
    db.close()


def test_seeded_demo_users_are_never_purged():
    assert not demo_shoppers.is_demo_shopper("demo-user-1")
