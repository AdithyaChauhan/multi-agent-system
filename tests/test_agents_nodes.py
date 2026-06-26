import pytest
from unittest.mock import MagicMock, patch
from app.agents.state import AgentState


class TestOrderAgentResponseGeneration:

    def _mock_order_llm(self, mock_llm, content="Your order has been shipped.", no_tool=True):
        """Set up llm.bind_tools(...).invoke() for response_generation."""
        mock_response = MagicMock()
        mock_response.content = content
        mock_response.response_metadata = {
            "token_usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}
        }
        mock_response.tool_calls = [] if no_tool else [{"id": "c1", "type": "function"}]
        mock_llm.bind_tools.return_value.invoke.return_value = mock_response
        mock_llm.invoke.return_value = mock_response
        return mock_response

    def test_response_generation_with_tracking(self):
        """response_generation creates natural language response (no tool call path)."""
        with patch("app.agents.order_agent.llm") as mock_llm:
            self._mock_order_llm(mock_llm, content="Your order has been shipped via FedEx and will arrive tomorrow.")
            from app.agents.order_agent import response_generation

            state = AgentState(
                user_message="Where is my order?",
                user_id="test-user",
                session_id="test-session",
                order_data={"order_id": "ORD-2001", "product_name": "AirPods", "status": "shipped"},
                tracking_data={"carrier": "FedEx", "current_location": "Mumbai", "estimated_delivery": "2026-05-25"},
                conversation_history=[],
            )
            result = response_generation(state)

        assert "final_response" in result
        assert len(result["final_response"]) > 0

    def test_response_generation_without_tracking(self):
        """response_generation works without tracking data"""
        with patch("app.agents.order_agent.llm") as mock_llm:
            self._mock_order_llm(mock_llm, content="Your order is being processed.")
            from app.agents.order_agent import response_generation

            state = AgentState(
                user_message="Where is my order?",
                user_id="test-user",
                session_id="test-session",
                order_data={"order_id": "ORD-2001", "product_name": "AirPods", "status": "processing"},
                tracking_data={},
                conversation_history=[],
            )
            result = response_generation(state)

        assert "final_response" in result


class TestOrderRouting:

    def test_route_after_check_has_id(self):
        """Routes to fetch when order_id exists"""
        from app.agents.order_agent import route_after_check

        state = AgentState(
            user_message="Where is ORD-2001?",
            user_id="test-user",
            session_id="test-session",
            order_id="ORD-2001",
            conversation_history=[],
        )
        result = route_after_check(state)
        assert result == "has_id"

    def test_route_after_check_no_orders(self):
        """Routes to no_orders when user has no orders"""
        from app.agents.order_agent import route_after_check

        state = AgentState(
            user_message="Where is my order?",
            user_id="test-user",
            session_id="test-session",
            order_id=None,
            user_orders=[],
            conversation_history=[],
        )
        result = route_after_check(state)
        assert result == "no_orders"

    def test_route_after_check_multiple_orders(self):
        """Routes to multiple_orders when user has several"""
        from app.agents.order_agent import route_after_check

        state = AgentState(
            user_message="Where is my order?",
            user_id="test-user",
            session_id="test-session",
            order_id=None,
            user_orders=[
                {"order_id": "ORD-2001"},
                {"order_id": "ORD-2002"},
            ],
            conversation_history=[],
        )
        result = route_after_check(state)
        assert result == "multiple_orders"

    def test_route_after_fetch_found(self):
        """Routes to found when order data exists"""
        from app.agents.order_agent import route_after_fetch

        state = AgentState(
            user_message="Where is my order?",
            user_id="test-user",
            session_id="test-session",
            order_data={"order_id": "ORD-2001"},
            conversation_history=[],
        )
        result = route_after_fetch(state)
        assert result == "found"

    def test_route_after_fetch_not_found(self):
        """Routes to not_found when order data is None"""
        from app.agents.order_agent import route_after_fetch

        state = AgentState(
            user_message="Where is my order?",
            user_id="test-user",
            session_id="test-session",
            order_data=None,
            conversation_history=[],
        )
        result = route_after_fetch(state)
        assert result == "not_found"


class TestSupportAgentDraftResolution:

    def test_draft_resolution_for_low_severity(self):
        """draft_resolution calls fetch_support_policy tool; falls back to final_response when no tool call."""
        mock_response = MagicMock()
        mock_response.content = "We apologize for the inconvenience. Your refund will be processed within 3-5 days."
        mock_response.response_metadata = {
            "token_usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80}
        }
        mock_response.tool_calls = []  # no tool call → returns final_response directly

        with patch("app.agents.support_agent.llm") as mock_llm:
            mock_llm.bind_tools.return_value.invoke.return_value = mock_response
            from app.agents.support_agent import draft_resolution

            state = AgentState(
                user_message="I want a refund",
                user_id="test-user",
                session_id="test-session",
                support_issue={"category": "refund_request", "description": "Want refund"},
                severity="low",
                conversation_history=[],
            )
            result = draft_resolution(state)

        assert "final_response" in result
        assert len(result["final_response"]) > 0


class TestSupportRouting:

    def test_route_by_severity_critical(self):
        """Routes critical issues to high priority"""
        from app.agents.support_agent import route_by_severity

        state = AgentState(
            user_message="urgent!",
            user_id="test-user",
            session_id="test-session",
            severity="critical",
            conversation_history=[],
        )
        result = route_by_severity(state)
        assert result == "high"

    def test_route_by_severity_medium(self):
        """Routes medium issues to high priority"""
        from app.agents.support_agent import route_by_severity

        state = AgentState(
            user_message="product broken",
            user_id="test-user",
            session_id="test-session",
            severity="medium",
            conversation_history=[],
        )
        result = route_by_severity(state)
        assert result == "high"

    def test_route_by_severity_low(self):
        """Routes low severity to direct resolution"""
        from app.agents.support_agent import route_by_severity

        state = AgentState(
            user_message="question",
            user_id="test-user",
            session_id="test-session",
            severity="low",
            conversation_history=[],
        )
        result = route_by_severity(state)
        assert result == "low"


class TestSupportSubgraphCreateTicket:

    def test_create_ticket_node_medium(self):
        """create_ticket_node creates ticket for medium severity"""
        mock_ticket = {"ticket_id": "TKT-ABCD1234"}

        with patch("app.agents.support_agent_subgraph.create_support_ticket", return_value=mock_ticket):
            from app.agents.support_agent_subgraph import create_ticket_node

            state = AgentState(
                user_message="product broken",
                user_id="test-user",
                session_id="test-session",
                support_issue={"category": "defective_product", "description": "Broken", "order_id": None},
                severity="medium",
                priority="P2",
                policy={"response_time": "24 hours"},
                conversation_history=[],
            )
            result = create_ticket_node(state)

        assert "final_response" in result
        assert "TKT-ABCD1234" in result["final_response"]

    def test_create_ticket_node_critical(self):
        """create_ticket_node creates urgent ticket for critical severity"""
        mock_ticket = {"ticket_id": "TKT-URGENT123"}

        with patch("app.agents.support_agent_subgraph.create_support_ticket", return_value=mock_ticket):
            from app.agents.support_agent_subgraph import create_ticket_node

            state = AgentState(
                user_message="urgent safety issue",
                user_id="test-user",
                session_id="test-session",
                support_issue={"category": "defective_product", "description": "Safety hazard", "order_id": None},
                severity="critical",
                priority="P0",
                policy={"response_time": "1 hour"},
                conversation_history=[],
            )
            result = create_ticket_node(state)

        assert "final_response" in result
        assert "URGENT" in result["final_response"].upper() or "TKT-URGENT123" in result["final_response"]


class TestRouterRouting:

    def test_route_after_classification_clarify(self):
        """Routes to clarify when confidence is low"""
        from app.agents.router import route_after_classification

        state = AgentState(
            user_message="hmm",
            user_id="test-user",
            session_id="test-session",
            confidence=0.3,
            intent="unclear",
            conversation_history=[],
        )
        result = route_after_classification(state)
        assert result == "clarify"

    def test_route_after_classification_auth_gate(self):
        """Routes to auth_gate when confidence is high"""
        from app.agents.router import route_after_classification

        state = AgentState(
            user_message="where is my order",
            user_id="test-user",
            session_id="test-session",
            confidence=0.9,
            intent="order",
            conversation_history=[],
        )
        result = route_after_classification(state)
        assert result == "auth_gate"
