from sqlalchemy.orm import Session as DBSession
from app.db.database import SessionLocal
from app.models.user import User
from app.models.order import Order
from app.core.logger import get_logger

logger = get_logger("app.db.seed")


DEMO_USERS = ["demo-user-1", "demo-user-2", "demo-user-3"]

DEMO_ORDERS = [
    {
        "order_id": "ORD-1001",
        "user_id": "demo-user-1",
        "product_name": "iPhone 15",
        "status": "shipped",
        "carrier": "FakeExpress",
        "tracking_id": "TRK-9001",
    },
    {
        "order_id": "ORD-1002",
        "user_id": "demo-user-1",
        "product_name": "AirPods Pro",
        "status": "delivered",
        "carrier": "FakeExpress",
        "tracking_id": "TRK-9002",
    },
    {
        "order_id": "ORD-1003",
        "user_id": "demo-user-2",
        "product_name": "Samsung Galaxy",
        "status": "in transit",
        "carrier": "FakeExpress",
        "tracking_id": "TRK-9003",
    },
    {
        "order_id": "ORD-1004",
        "user_id": "demo-user-2",
        "product_name": "Sony Headphones",
        "status": "shipped",
        "carrier": "FakeExpress",
        "tracking_id": "TRK-9004",
    },
    {
        "order_id": "ORD-1005",
        "user_id": "demo-user-3",
        "product_name": "MacBook Air",
        "status": "delivered",
        "carrier": "FakeExpress",
        "tracking_id": "TRK-9005",
    },
    {
        "order_id": "ORD-1006",
        "user_id": "demo-user-3",
        "product_name": "iPad",
        "status": "placed",
        "carrier": None,
        "tracking_id": None,
    },
]


# def seed_demo_data():
#     db: DBSession = SessionLocal()

#     try:
#         for user_id in DEMO_USERS:
#             existing = db.query(User).filter(User.user_id == user_id).first()
#             if not existing:
#                 db.add(User(user_id=user_id))
#                 logger.info(f"Seeded user | user_id={user_id}")

#         for order_data in DEMO_ORDERS:
#             existing = db.query(Order).filter(Order.order_id == order_data["order_id"]).first()
#             if not existing:
#                 db.add(Order(**order_data))
#                 logger.info(f"Seeded order | order_id={order_data['order_id']}")

#         db.commit()
#         logger.info("Seed data complete")

#     except Exception as e:
#         logger.error(f"Seed failed | {str(e)}")
#         db.rollback()
#         raise
#     finally:
#         db.close()
