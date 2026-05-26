from typing import Optional
from app.db.database import SessionLocal
from app.models.order import Order
from app.core.logger import get_logger, get_request_id

from typing import List

logger = get_logger("app.tools.order_tools")


def fetch_order_from_db(order_id: str, user_id: str) -> Optional[dict]:
    """
    Fetch an order from the DB, filtered by BOTH order_id AND user_id.
    Returns the order as a dict, or None if not found.
    """
    db = SessionLocal()

    try:
        order = (
            db.query(Order)
            .filter(Order.order_id == order_id, Order.user_id == user_id)
            .first()
        )

        if not order:
            logger.info(f"request_id={get_request_id()} | Order not found | order_id={order_id} | user_id={user_id}")
            return None

        logger.info(f"request_id={get_request_id()} | Order fetched | order_id={order_id}")
        return {
            "order_id": order.order_id,
            "user_id": order.user_id,
            "product_name": order.product_name,
            "status": order.status,
            "carrier": order.carrier,
            "tracking_id": order.tracking_id,
        }

    finally:
        db.close()



def fetch_user_orders(user_id: str) -> List[dict]:
    """Fetch all orders for a given user"""
    from app.models.order import Order
    
    db = SessionLocal()
    try:
        orders = db.query(Order).filter(
            Order.user_id == user_id
        ).order_by(Order.created_at.desc()).all()
        
        return [{
            "order_id": o.order_id,
            "product_name": o.product_name,
            "status": o.status,
            "tracking_id": o.tracking_id,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        } for o in orders]
        
    finally:
        db.close()