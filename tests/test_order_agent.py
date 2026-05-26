import pytest
from unittest.mock import MagicMock, patch
from app.agents.state import AgentState


class TestCheckOrderId:

    def test_auto_selects_single_order(self):
        """Auto-selects order when user has only one"""
        mock_orders = [{"order_id": "ORD-2001", "product_name": "AirPods", "status": "shipped", "tracking_id": "TRK-001", "created_at": None}]

        with patch("app.agents.order_agent.fetch_user_orders", return_value=mock_orders):
            from app.agents.order_agent import check_order_id

            state = AgentState(
                user_message="Where is my order?",
                user_id="test-user",
                session_id="test-session",
                conversation_history=[]
            )
            result = check_order_id(state)

        assert result["order_id"] == "ORD-2001"

    def test_returns_none_when_no_orders(self):
        """Returns no order_id when user has no orders"""
        with patch("app.agents.order_agent.fetch_user_orders", return_value=[]):
            from app.agents.order_agent import check_order_id

            state = AgentState(
                user_message="Where is my order?",
                user_id="test-user",
                session_id="test-session",
                conversation_history=[]
            )
            result = check_order_id(state)

        assert result["order_id"] is None
        assert result["user_orders"] == []

    def test_extracts_order_id_from_message(self):
        """Extracts order ID directly from message"""
        with patch("app.agents.order_agent.fetch_user_orders", return_value=[]):
            from app.agents.order_agent import check_order_id

            state = AgentState(
                user_message="Track order ORD-2001",
                user_id="test-user",
                session_id="test-session",
                conversation_history=[]
            )
            result = check_order_id(state)

        assert result["order_id"] == "ORD-2001"

    def test_multiple_orders_returns_none(self):
        """Returns None order_id when multiple orders exist"""
        mock_orders = [
            {"order_id": "ORD-2001", "product_name": "AirPods", "status": "shipped", "tracking_id": "TRK-001", "created_at": None},
            {"order_id": "ORD-2002", "product_name": "Headphones", "status": "delivered", "tracking_id": "TRK-002", "created_at": None},
        ]

        with patch("app.agents.order_agent.fetch_user_orders", return_value=mock_orders):
            from app.agents.order_agent import check_order_id

            state = AgentState(
                user_message="Where is my order?",
                user_id="test-user",
                session_id="test-session",
                conversation_history=[]
            )
            result = check_order_id(state)

        assert result["order_id"] is None
        assert len(result["user_orders"]) == 2


class TestFetchOrder:

    def test_fetch_existing_order(self):
        """Fetches order that exists"""
        mock_order = {"order_id": "ORD-2001", "product_name": "AirPods", "status": "shipped"}

        with patch("app.agents.order_agent.fetch_order_from_db", return_value=mock_order):
            from app.agents.order_agent import fetch_order

            state = AgentState(
                user_message="Track my order",
                user_id="test-user",
                session_id="test-session",
                order_id="ORD-2001",
                conversation_history=[]
            )
            result = fetch_order(state)

        assert result["order_data"]["order_id"] == "ORD-2001"

    def test_fetch_nonexistent_order(self):
        """Returns None for non-existent order"""
        with patch("app.agents.order_agent.fetch_order_from_db", return_value=None):
            from app.agents.order_agent import fetch_order

            state = AgentState(
                user_message="Track my order",
                user_id="test-user",
                session_id="test-session",
                order_id="ORD-9999",
                conversation_history=[]
            )
            result = fetch_order(state)

        assert result["order_data"] is None
