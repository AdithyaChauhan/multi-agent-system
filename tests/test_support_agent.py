import pytest
from unittest.mock import MagicMock, patch
from app.agents.state import AgentState


class TestClassifyIssue:

    def test_classifies_defective_product(self):
        """Correctly classifies defective product issue"""
        mock_response = MagicMock()
        mock_response.content = '{"category": "defective_product", "order_id": null, "description": "Product is broken"}'

        with patch("app.agents.support_agent.llm") as mock_llm, \
             patch("app.agents.support_agent.load_prompt", return_value=("system prompt", "latest")):
            mock_llm.invoke.return_value = mock_response
            from app.agents.support_agent import classify_issue

            state = AgentState(
                user_message="My product is broken",
                user_id="test-user",
                session_id="test-session",
                conversation_history=[]
            )
            result = classify_issue(state)

        assert result["support_issue"]["category"] == "defective_product"

    def test_classifies_refund_request(self):
        """Correctly classifies refund request"""
        mock_response = MagicMock()
        mock_response.content = '{"category": "refund_request", "order_id": "ORD-2001", "description": "Want refund"}'

        with patch("app.agents.support_agent.llm") as mock_llm, \
             patch("app.agents.support_agent.load_prompt", return_value=("system prompt", "latest")):
            mock_llm.invoke.return_value = mock_response
            from app.agents.support_agent import classify_issue

            state = AgentState(
                user_message="I want a refund for ORD-2001",
                user_id="test-user",
                session_id="test-session",
                conversation_history=[]
            )
            result = classify_issue(state)

        assert result["support_issue"]["category"] == "refund_request"

    def test_handles_invalid_json(self):
        """Falls back gracefully on invalid JSON"""
        mock_response = MagicMock()
        mock_response.content = "invalid json"

        with patch("app.agents.support_agent.llm") as mock_llm, \
             patch("app.agents.support_agent.load_prompt", return_value=("system prompt", "latest")):
            mock_llm.invoke.return_value = mock_response
            from app.agents.support_agent import classify_issue

            state = AgentState(
                user_message="Something is wrong",
                user_id="test-user",
                session_id="test-session",
                conversation_history=[]
            )
            result = classify_issue(state)

        assert result["support_issue"]["category"] == "general_query"


class TestAssessSeverity:

    def test_critical_severity_with_child_keyword(self):
        """High severity for high-value damaged product (>=10000)"""
        from app.agents.support_agent import assess_severity

        state = AgentState(
            user_message="My baby got hurt by this toy",
            user_id="test-user",
            session_id="test-session",
            support_issue={"category": "damaged_product"},
            support_order={"order_value": 15000},
            conversation_history=[]
        )
        result = assess_severity(state)
        assert result["severity"] == "high"

    def test_medium_severity_for_defective_product(self):
        """Medium severity for damaged product with order value below threshold"""
        from app.agents.support_agent import assess_severity

        state = AgentState(
            user_message="My product stopped working",
            user_id="test-user",
            session_id="test-session",
            support_issue={"category": "damaged_product"},
            support_order={"order_value": 5000},
            conversation_history=[]
        )
        result = assess_severity(state)
        assert result["severity"] == "medium"

    def test_low_severity_for_general_complaint(self):
        """Detects low severity for general complaints"""
        from app.agents.support_agent import assess_severity

        state = AgentState(
            user_message="I want a refund",
            user_id="test-user",
            session_id="test-session",
            support_issue={"category": "refund_request"},
            conversation_history=[]
        )
        result = assess_severity(state)
        assert result["severity"] == "low"
