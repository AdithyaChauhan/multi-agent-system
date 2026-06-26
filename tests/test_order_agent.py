import pytest
from unittest.mock import MagicMock, patch
from app.agents.state import AgentState


class TestCheckOrderId:

    def test_auto_selects_single_order(self):
        """Auto-selects order when user has only one"""
        mock_orders = [
            {
                "order_id": "ORD-2001",
                "product_name": "AirPods",
                "status": "shipped",
                "tracking_id": "TRK-001",
                "created_at": None,
            }
        ]

        with patch("app.agents.order_agent.fetch_user_orders", return_value=mock_orders):
            from app.agents.order_agent import check_order_id

            state = AgentState(
                user_message="Where is my order?",
                user_id="test-user",
                session_id="test-session",
                conversation_history=[],
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
                conversation_history=[],
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
                conversation_history=[],
            )
            result = check_order_id(state)

        assert result["order_id"] == "ORD-2001"

    def test_multiple_orders_returns_none(self):
        """Returns None order_id when multiple orders exist"""
        mock_orders = [
            {
                "order_id": "ORD-2001",
                "product_name": "AirPods",
                "status": "shipped",
                "tracking_id": "TRK-001",
                "created_at": None,
            },
            {
                "order_id": "ORD-2002",
                "product_name": "Headphones",
                "status": "delivered",
                "tracking_id": "TRK-002",
                "created_at": None,
            },
        ]

        with patch("app.agents.order_agent.fetch_user_orders", return_value=mock_orders):
            from app.agents.order_agent import check_order_id

            state = AgentState(
                user_message="Where is my order?",
                user_id="test-user",
                session_id="test-session",
                conversation_history=[],
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
                conversation_history=[],
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
                conversation_history=[],
            )
            result = fetch_order(state)

        assert result["order_data"] is None


class TestFinalizeOrderResponse:

    def test_generates_response_post_tool(self):
        """finalize_order_response produces a final_response after tracking tool call."""
        mock_resp = MagicMock()
        mock_resp.content = "Your order has been delivered."

        with patch("app.agents.order_agent.load_prompt", return_value=(None, None)), patch(
            "app.agents.order_agent.llm"
        ) as mock_llm:
            mock_llm.invoke.return_value = mock_resp
            from app.agents.order_agent import finalize_order_response

            state = AgentState(
                user_message="Where is my order?",
                user_id="u1",
                session_id="s1",
                order_data={"order_id": "ORD-1", "product_name": "AirPods", "status": "delivered"},
                tracking_data={"carrier": "FedEx", "tracking_id": "TRK-001", "live_status": "delivered"},
                messages=[],
                conversation_history=[],
            )
            result = finalize_order_response(state)

        assert "final_response" in result
        assert result["final_response"] == "Your order has been delivered."

    def test_generates_response_with_tool_message(self):
        """finalize_order_response incorporates live tracking data from ToolMessage."""
        from langchain_core.messages import ToolMessage

        mock_resp = MagicMock()
        mock_resp.content = "FedEx shows your order is in transit."

        tool_msg = ToolMessage(
            content='{"carrier": "FedEx", "live_status": "in_transit"}',
            tool_call_id="call_1",
        )

        with patch("app.agents.order_agent.load_prompt", return_value=(None, None)), patch(
            "app.agents.order_agent.llm"
        ) as mock_llm:
            mock_llm.invoke.return_value = mock_resp
            from app.agents.order_agent import finalize_order_response

            state = AgentState(
                user_message="Is it on the way?",
                user_id="u1",
                session_id="s1",
                order_data={"order_id": "ORD-2", "product_name": "TV", "status": "shipped"},
                tracking_data={},
                messages=[tool_msg],
                conversation_history=[{"role": "user", "content": "hello"}],
            )
            result = finalize_order_response(state)

        assert "final_response" in result

    def test_uses_prompt_from_hub_when_available(self):
        """finalize_order_response uses hub prompt when load_prompt succeeds."""
        mock_resp = MagicMock()
        mock_resp.content = "Delivered yesterday."

        with patch("app.agents.order_agent.load_prompt", return_value=("Hub system prompt", "abc123")), patch(
            "app.agents.order_agent.llm"
        ) as mock_llm:
            mock_llm.invoke.return_value = mock_resp
            from app.agents.order_agent import finalize_order_response

            state = AgentState(
                user_message="status?",
                user_id="u1",
                session_id="s1",
                order_data={"order_id": "ORD-3", "product_name": "Phone", "status": "delivered"},
                tracking_data={},
                messages=[],
                conversation_history=[],
            )
            result = finalize_order_response(state)

        assert result["final_response"] == "Delivered yesterday."


class TestRouteToOrderTool:

    def test_routes_to_tools_when_tool_calls_present(self):
        from app.agents.order_agent import route_to_order_tool

        mock_msg = MagicMock()
        mock_msg.tool_calls = [{"name": "fetch_tracking_info", "id": "1", "args": {}}]
        state = AgentState(
            user_message="track",
            user_id="u1",
            session_id="s1",
            messages=[mock_msg],
            conversation_history=[],
        )
        assert route_to_order_tool(state) == "order_tools"

    def test_routes_to_end_when_no_tool_calls(self):
        from app.agents.order_agent import route_to_order_tool

        mock_msg = MagicMock()
        mock_msg.tool_calls = None
        state = AgentState(
            user_message="track",
            user_id="u1",
            session_id="s1",
            messages=[mock_msg],
            conversation_history=[],
        )
        assert route_to_order_tool(state) == "end"

    def test_routes_to_end_when_no_messages(self):
        from app.agents.order_agent import route_to_order_tool

        state = AgentState(
            user_message="track",
            user_id="u1",
            session_id="s1",
            messages=[],
            conversation_history=[],
        )
        assert route_to_order_tool(state) == "end"
