import pytest
import json
from unittest.mock import MagicMock, patch
from app.agents.state import AgentState


class TestRouterClassification:

    def test_classify_order_intent(self):
        """Router correctly classifies order-related messages"""
        mock_response = MagicMock()
        mock_response.content = '{"intent": "order", "confidence": 0.95, "order_id": null}'

        with patch("app.agents.router.llm") as mock_llm:
            mock_llm.invoke.return_value = mock_response
            from app.agents.router import classify_intent_and_extract

            state = AgentState(
                user_message="Where is my order?",
                user_id="test-user",
                session_id="test-session",
                conversation_history=[]
            )
            result = classify_intent_and_extract(state)

        assert result["intent"] == "order"
        assert result["confidence"] == 0.95

    def test_classify_product_intent(self):
        """Router correctly classifies product-related messages"""
        mock_response = MagicMock()
        mock_response.content = '{"intent": "product", "confidence": 0.9, "order_id": null}'

        with patch("app.agents.router.llm") as mock_llm:
            mock_llm.invoke.return_value = mock_response
            from app.agents.router import classify_intent_and_extract

            state = AgentState(
                user_message="Show me toys",
                user_id="test-user",
                session_id="test-session",
                conversation_history=[]
            )
            result = classify_intent_and_extract(state)

        assert result["intent"] == "product"

    def test_classify_support_intent(self):
        """Router correctly classifies support-related messages"""
        mock_response = MagicMock()
        mock_response.content = '{"intent": "support", "confidence": 0.95, "order_id": null}'

        with patch("app.agents.router.llm") as mock_llm:
            mock_llm.invoke.return_value = mock_response
            from app.agents.router import classify_intent_and_extract

            state = AgentState(
                user_message="My product is broken",
                user_id="test-user",
                session_id="test-session",
                conversation_history=[]
            )
            result = classify_intent_and_extract(state)

        assert result["intent"] == "support"

    def test_classify_with_order_id_extraction(self):
        """Router extracts order ID from message"""
        mock_response = MagicMock()
        mock_response.content = '{"intent": "order", "confidence": 1.0, "order_id": "ORD-2001"}'

        with patch("app.agents.router.llm") as mock_llm:
            mock_llm.invoke.return_value = mock_response
            from app.agents.router import classify_intent_and_extract

            state = AgentState(
                user_message="Track order ORD-2001",
                user_id="test-user",
                session_id="test-session",
                conversation_history=[]
            )
            result = classify_intent_and_extract(state)

        assert result["order_id"] == "ORD-2001"

    def test_classify_invalid_json_returns_unclear(self):
        """Router handles invalid JSON gracefully"""
        mock_response = MagicMock()
        mock_response.content = "invalid json"

        with patch("app.agents.router.llm") as mock_llm:
            mock_llm.invoke.return_value = mock_response
            from app.agents.router import classify_intent_and_extract

            state = AgentState(
                user_message="Something",
                user_id="test-user",
                session_id="test-session",
                conversation_history=[]
            )
            result = classify_intent_and_extract(state)

        assert result["intent"] == "unclear"
        assert result["confidence"] == 0.0



class TestRouterAuthGate:

    def test_auth_gate_returns_empty_dict(self):
        """Auth gate is a pass-through that returns empty dict"""
        from app.agents.router import auth_gate

        state = AgentState(
            user_message="Where is my order?",
            user_id="anon-123",
            session_id="test-session",
            intent="order",
            conversation_history=[]
        )
        result = auth_gate(state)
        assert result == {}

    def test_auth_gate_allows_authenticated_user(self):
        """Auth gate passes through for authenticated users"""
        from app.agents.router import auth_gate

        state = AgentState(
            user_message="Where is my order?",
            user_id="demo-user-1",
            session_id="test-session",
            intent="order",
            conversation_history=[]
        )
        result = auth_gate(state)
        assert result == {}

    def test_route_after_auth_gate_blocks_anonymous(self):
        """Routing blocks anonymous users from order intent"""
        from app.agents.router import route_after_auth_gate

        state = AgentState(
            user_message="Where is my order?",
            user_id="anon-123",
            session_id="test-session",
            intent="order",
            conversation_history=[]
        )
        result = route_after_auth_gate(state)
        assert result == "sign_in"

    def test_route_after_auth_gate_allows_product_intent(self):
        """Anonymous users can browse products"""
        from app.agents.router import route_after_auth_gate

        state = AgentState(
            user_message="Show me toys",
            user_id="anon-123",
            session_id="test-session",
            intent="product",
            conversation_history=[]
        )
        result = route_after_auth_gate(state)
        assert result != "sign_in"