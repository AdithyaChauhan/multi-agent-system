from sqlalchemy.orm import Session as DBSession
from app.db.database import SessionLocal
from app.models.user import User
from app.models.order import Order
from app.core.logger import get_logger

logger = get_logger("app.db.seed")


DEMO_USERS = ["demo-user-1", "demo-user-2", "demo-user-3", "test-user-99"]

DEMO_ORDERS = [
    # demo-user-1
    {"order_id": "ORD-2001", "user_id": "demo-user-1", "product_name": "boAt Rockerz 255 Pro+", "status": "delivered", "carrier": "BlueDart", "tracking_id": "TRK-2001"},
    {"order_id": "ORD-2002", "user_id": "demo-user-1", "product_name": "Mi 108cm Full HD Android LED TV", "status": "shipped", "carrier": "FakeExpress", "tracking_id": "TRK-2002"},
    {"order_id": "ORD-2003", "user_id": "demo-user-1", "product_name": "Fire-Boltt Phoenix Smartwatch", "status": "shipped", "carrier": "DTDC", "tracking_id": "TRK-2003"},
    {"order_id": "ORD-2004", "user_id": "demo-user-1", "product_name": "Croma 500W Mixer Grinder", "status": "delivered", "carrier": "BlueDart", "tracking_id": "TRK-2004"},
    {"order_id": "ORD-2005", "user_id": "demo-user-1", "product_name": "Logitech M221 Wireless Mouse", "status": "cancelled", "carrier": None, "tracking_id": None},
    # demo-user-2
    {"order_id": "ORD-4001", "user_id": "demo-user-2", "product_name": "boAt Rockerz 255 Pro+", "status": "delivered", "carrier": "BlueDart", "tracking_id": "TRK-4001"},
    {"order_id": "ORD-4002", "user_id": "demo-user-2", "product_name": "Mi 108cm Full HD Android LED TV", "status": "shipped", "carrier": "FakeExpress", "tracking_id": "TRK-4002"},
    {"order_id": "ORD-4003", "user_id": "demo-user-2", "product_name": "Fire-Boltt Phoenix Smartwatch", "status": "shipped", "carrier": "DTDC", "tracking_id": "TRK-4003"},
    {"order_id": "ORD-4004", "user_id": "demo-user-2", "product_name": "Croma 500W Mixer Grinder", "status": "delivered", "carrier": "BlueDart", "tracking_id": "TRK-4004"},
    {"order_id": "ORD-4005", "user_id": "demo-user-2", "product_name": "Logitech M221 Wireless Mouse", "status": "cancelled", "carrier": None, "tracking_id": None},
    # demo-user-3
    {"order_id": "ORD-5001", "user_id": "demo-user-3", "product_name": "JBL Go 2 Bluetooth Speaker", "status": "delivered", "carrier": "BlueDart", "tracking_id": "TRK-5001"},
    {"order_id": "ORD-5002", "user_id": "demo-user-3", "product_name": "Bajaj Deluxe Room Heater", "status": "processing", "carrier": None, "tracking_id": None},
    # test-user-99
    {"order_id": "ORD-9901", "user_id": "test-user-99", "product_name": "iPhone 15 Pro Max", "status": "shipped", "carrier": "FakeExpress", "tracking_id": "TRK-9901"},
    {"order_id": "ORD-9902", "user_id": "test-user-99", "product_name": "boAt Rockerz 450 Bluetooth Headphones", "status": "delivered", "carrier": "DTDC", "tracking_id": "TRK-9902"},
    {"order_id": "ORD-9903", "user_id": "test-user-99", "product_name": "Philips Air Purifier AC1215", "status": "delivered", "carrier": "BlueDart", "tracking_id": "TRK-9903"},
    {"order_id": "ORD-9904", "user_id": "test-user-99", "product_name": "Samsung 43 inch 4K Smart TV", "status": "out_for_delivery", "carrier": "FakeExpress", "tracking_id": "TRK-9904"},
    {"order_id": "ORD-9905", "user_id": "test-user-99", "product_name": "Bajaj Rex 500W Mixer Grinder", "status": "processing", "carrier": None, "tracking_id": None},
]


def seed_demo_data():
    db: DBSession = SessionLocal()

    try:
        for user_id in DEMO_USERS:
            existing = db.query(User).filter(User.user_id == user_id).first()
            if not existing:
                db.add(User(user_id=user_id))
                logger.info(f"Seeded user | user_id={user_id}")

        for order_data in DEMO_ORDERS:
            existing = db.query(Order).filter(Order.order_id == order_data["order_id"]).first()
            if not existing:
                db.add(Order(**order_data))
                logger.info(f"Seeded order | order_id={order_data['order_id']}")

        db.commit()
        logger.info("Seed data complete")

    except Exception as e:
        logger.error(f"Seed failed | {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()
