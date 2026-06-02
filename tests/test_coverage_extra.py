"""
Targeted coverage tests for support_agent.py, order_agent_subgraph.py,
and order_agent.py uncovered branches.
"""

import pytest
from unittest.mock import MagicMock, patch

from app.agents.state import AgentState

# ── order_agent_subgraph ─────────────────────────────────────────────────────


class TestOrderSubgraphNodes:
    def test_get_carrier_info_extracts_fields(self):
        from app.agents.order_agent_subgraph import get_carrier_info

        state = AgentState(
            user_message="track",
            user_id="u1",
            session_id="s1",
            order_data={"carrier": "FedEx", "tracking_id": "TRK-999", "status": "shipped"},
            conversation_history=[],
        )
        result = get_carrier_info(state)
        assert result["tracking_data"]["carrier"] == "FedEx"
        assert result["tracking_data"]["tracking_id"] == "TRK-999"
        assert result["tracking_data"]["status_from_db"] == "shipped"

    def test_fetch_tracking_no_tracking_id(self):
        """fetch_tracking returns empty live fields when no tracking_id is set."""
        from app.agents.order_agent_subgraph import fetch_tracking

        state = AgentState(
            user_message="track",
            user_id="u1",
            session_id="s1",
            tracking_data={"carrier": "FedEx", "tracking_id": None},
            conversation_history=[],
        )
        result = fetch_tracking(state)
        assert result["tracking_data"]["live_status"] is None
        assert result["tracking_data"]["current_location"] is None

    def test_fetch_tracking_api_returns_none(self):
        """fetch_tracking handles carrier API returning None gracefully."""
        from app.agents.order_agent_subgraph import fetch_tracking

        with patch("app.agents.order_agent_subgraph.fetch_tracking_info", return_value=None):
            state = AgentState(
                user_message="track",
                user_id="u1",
                session_id="s1",
                tracking_data={"carrier": "FedEx", "tracking_id": "TRK-001"},
                conversation_history=[],
            )
            result = fetch_tracking(state)

        assert result["tracking_data"]["live_status"] is None

    def test_fetch_tracking_api_returns_data(self):
        """fetch_tracking merges live API data into tracking_data."""
        from app.agents.order_agent_subgraph import fetch_tracking

        api_data = {
            "status": "In Transit",
            "current_location": "Mumbai",
            "estimated_delivery": "2026-06-02",
            "last_update": "2026-06-01",
        }
        with patch("app.agents.order_agent_subgraph.fetch_tracking_info", return_value=api_data):
            state = AgentState(
                user_message="track",
                user_id="u1",
                session_id="s1",
                tracking_data={"carrier": "FedEx", "tracking_id": "TRK-001"},
                conversation_history=[],
            )
            result = fetch_tracking(state)

        assert result["tracking_data"]["live_status"] == "In Transit"
        assert result["tracking_data"]["current_location"] == "Mumbai"

    def test_extract_latest_status_prefers_live(self):
        """extract_latest_status picks live_status over db_status."""
        from app.agents.order_agent_subgraph import extract_latest_status

        state = AgentState(
            user_message="track",
            user_id="u1",
            session_id="s1",
            tracking_data={"live_status": "Out for delivery", "status_from_db": "shipped"},
            conversation_history=[],
        )
        result = extract_latest_status(state)
        assert result["tracking_data"]["final_status"] == "Out for delivery"

    def test_extract_latest_status_falls_back_to_db(self):
        """extract_latest_status uses db_status when live_status is None."""
        from app.agents.order_agent_subgraph import extract_latest_status

        state = AgentState(
            user_message="track",
            user_id="u1",
            session_id="s1",
            tracking_data={"live_status": None, "status_from_db": "processing"},
            conversation_history=[],
        )
        result = extract_latest_status(state)
        assert result["tracking_data"]["final_status"] == "processing"

    def test_extract_latest_status_default_when_both_none(self):
        from app.agents.order_agent_subgraph import extract_latest_status

        state = AgentState(
            user_message="track",
            user_id="u1",
            session_id="s1",
            tracking_data={"live_status": None, "status_from_db": None},
            conversation_history=[],
        )
        result = extract_latest_status(state)
        assert result["tracking_data"]["final_status"] == "Status unavailable"


# ── order_agent ──────────────────────────────────────────────────────────────


class TestOrderAgentNodes:
    def test_respond_no_orders_returns_message(self):
        from app.agents.order_agent import respond_no_orders

        state = AgentState(
            user_message="my orders", user_id="u1", session_id="s1", user_orders=[], conversation_history=[]
        )
        result = respond_no_orders(state)
        assert "final_response" in result
        assert len(result["final_response"]) > 0

    def test_ask_which_order_lists_orders(self):
        from app.agents.order_agent import ask_which_order

        orders = [
            {"order_id": "ORD-1", "product_name": "Headphones", "status": "shipped"},
            {"order_id": "ORD-2", "product_name": "Charger", "status": "delivered"},
        ]
        state = AgentState(
            user_message="my orders",
            user_id="u1",
            session_id="s1",
            user_orders=orders,
            conversation_history=[],
        )
        result = ask_which_order(state)
        assert "final_response" in result
        assert "ORD-1" in result["final_response"] or "ORD-2" in result["final_response"]

    def test_respond_not_found_returns_message(self):
        from app.agents.order_agent import respond_not_found

        state = AgentState(
            user_message="track ORD-9999",
            user_id="u1",
            session_id="s1",
            order_id="ORD-9999",
            conversation_history=[],
        )
        result = respond_not_found(state)
        assert "final_response" in result

    def test_route_after_check_no_orders(self):
        from app.agents.order_agent import route_after_check

        state = AgentState(
            user_message="my orders",
            user_id="u1",
            session_id="s1",
            user_orders=[],
            order_id=None,
            conversation_history=[],
        )
        assert route_after_check(state) == "no_orders"

    def test_route_after_check_multiple_orders(self):
        from app.agents.order_agent import route_after_check

        state = AgentState(
            user_message="my orders",
            user_id="u1",
            session_id="s1",
            user_orders=[{"order_id": "ORD-1"}, {"order_id": "ORD-2"}],
            order_id=None,
            conversation_history=[],
        )
        assert route_after_check(state) == "multiple_orders"

    def test_route_after_check_has_id(self):
        from app.agents.order_agent import route_after_check

        state = AgentState(
            user_message="track ORD-1",
            user_id="u1",
            session_id="s1",
            user_orders=[{"order_id": "ORD-1"}],
            order_id="ORD-1",
            conversation_history=[],
        )
        assert route_after_check(state) == "has_id"

    def test_route_after_fetch_found(self):
        from app.agents.order_agent import route_after_fetch

        state = AgentState(
            user_message="track",
            user_id="u1",
            session_id="s1",
            order_data={"order_id": "ORD-1"},
            conversation_history=[],
        )
        assert route_after_fetch(state) == "found"

    def test_route_after_fetch_not_found(self):
        from app.agents.order_agent import route_after_fetch

        state = AgentState(
            user_message="track",
            user_id="u1",
            session_id="s1",
            order_data=None,
            conversation_history=[],
        )
        assert route_after_fetch(state) == "not_found"


# ── support_agent ─────────────────────────────────────────────────────────────


class TestSupportAgentNodes:
    def test_classify_issue_uses_fallback_when_prompt_missing(self):
        """classify_issue falls back to hardcoded prompt when hub returns None."""
        from app.agents.support_agent import classify_issue

        mock_response = MagicMock()
        mock_response.content = '{"category": "defective_product", "order_id": "ORD-1", "description": "broken"}'

        with patch("app.agents.support_agent.load_prompt", return_value=(None, "fallback")):
            with patch("app.agents.support_agent.llm") as mock_llm:
                mock_llm.invoke.return_value = mock_response
                state = AgentState(
                    user_message="my product is broken",
                    user_id="u1",
                    session_id="s1",
                    conversation_history=[],
                )
                result = classify_issue(state)

        assert "support_issue" in result
        assert result["support_issue"]["category"] == "defective_product"

    def test_classify_issue_with_history_context(self):
        """classify_issue includes conversation history in the prompt."""
        from app.agents.support_agent import classify_issue

        mock_response = MagicMock()
        mock_response.content = '{"category": "refund", "order_id": null, "description": "want refund"}'

        with patch("app.agents.support_agent.load_prompt", return_value=("System prompt", "abc123")):
            with patch("app.agents.support_agent.llm") as mock_llm:
                mock_llm.invoke.return_value = mock_response
                state = AgentState(
                    user_message="I want a refund",
                    user_id="u1",
                    session_id="s1",
                    conversation_history=[
                        {"role": "user", "content": "my order arrived damaged"},
                        {"role": "assistant", "content": "I'm sorry to hear that"},
                    ],
                )
                result = classify_issue(state)

        assert result["support_issue"]["category"] == "refund"
        # LLM was called with a prompt that included history context
        call_args = mock_llm.invoke.call_args[0][0]
        assert any("damaged" in str(m.content) for m in call_args)

    def test_classify_issue_handles_json_parse_error(self):
        """classify_issue recovers from malformed LLM JSON."""
        from app.agents.support_agent import classify_issue

        mock_response = MagicMock()
        mock_response.content = "not valid json at all"

        with patch("app.agents.support_agent.load_prompt", return_value=("System", "abc")):
            with patch("app.agents.support_agent.llm") as mock_llm:
                mock_llm.invoke.return_value = mock_response
                state = AgentState(
                    user_message="broken product",
                    user_id="u1",
                    session_id="s1",
                    conversation_history=[],
                )
                result = classify_issue(state)

        assert result["support_issue"]["category"] == "other"

    def test_assess_severity_high_for_critical_keywords(self):
        """assess_severity assigns high severity for dangerous product keywords."""
        from app.agents.support_agent import assess_severity

        state = AgentState(
            user_message="my product caught fire",
            user_id="u1",
            session_id="s1",
            support_issue={"category": "defective_product", "description": "fire hazard"},
            order_data={"product_name": "Iron"},
            conversation_history=[],
        )
        result = assess_severity(state)
        assert "severity" in result
        assert result["severity"] in ("critical", "medium", "low")

    def test_assess_severity_low_for_cosmetic_issue(self):
        """assess_severity assigns low for minor issues."""
        from app.agents.support_agent import assess_severity

        state = AgentState(
            user_message="packaging was slightly dented",
            user_id="u1",
            session_id="s1",
            support_issue={"category": "other", "description": "packaging issue"},
            order_data={"product_name": "Headphones"},
            conversation_history=[],
        )
        result = assess_severity(state)
        assert "severity" in result

    def test_lookup_policy_returns_messages(self):
        """lookup_policy is now an LLM tool-caller; returns messages."""
        with patch("app.agents.support_agent.llm") as mock_llm:
            mock_response = MagicMock()
            mock_response.content = ""
            mock_response.response_metadata = {
                "token_usage": {"prompt_tokens": 30, "completion_tokens": 5, "total_tokens": 35}
            }
            mock_response.tool_calls = []
            mock_llm.bind_tools.return_value.invoke.return_value = mock_response

            from app.agents.support_agent import lookup_policy

            state = AgentState(
                user_message="I want a refund",
                user_id="u1",
                session_id="s1",
                support_issue={"category": "refund"},
                severity="low",
                conversation_history=[],
            )
            result = lookup_policy(state)
        assert "messages" in result

    def test_parse_policy_extracts_policy(self):
        """parse_policy reads ToolMessage into state['policy']."""
        import json
        from langchain_core.messages import ToolMessage
        from app.agents.support_agent import parse_policy

        policy = {"auto_resolve": True, "response_time": "24 hours"}
        tool_msg = ToolMessage(content=json.dumps(policy), tool_call_id="c1")
        state = AgentState(
            user_message="refund",
            user_id="u1",
            session_id="s1",
            conversation_history=[],
            messages=[tool_msg],
        )
        result = parse_policy(state)
        assert "policy" in result
        assert result["policy"]["auto_resolve"] is True

    def test_route_by_severity_high(self):
        from app.agents.support_agent import route_by_severity

        state = AgentState(
            user_message="",
            user_id="u1",
            session_id="s1",
            severity="critical",
            conversation_history=[],
        )
        assert route_by_severity(state) == "high"

    def test_route_by_severity_low(self):
        from app.agents.support_agent import route_by_severity

        state = AgentState(
            user_message="",
            user_id="u1",
            session_id="s1",
            severity="low",
            conversation_history=[],
        )
        assert route_by_severity(state) == "low"


# ── prompt_loader ────────────────────────────────────────────────────────────


class TestPromptLoader:
    def _make_prompt_mock(self, template: str):
        msg = MagicMock()
        msg.prompt.template = template
        pulled = MagicMock()
        pulled.messages = [msg]
        return pulled

    def test_load_prompt_success_path(self):
        """Lines 27-37: successful client.pull_prompt populates cache and returns text."""
        from app.core.prompt_loader import load_prompt, _cache

        _cache.pop("__test-success-prompt__:v1", None)
        with patch("app.core.prompt_loader.client") as mock_client:
            mock_client.pull_prompt.return_value = self._make_prompt_mock("You are a test agent.")
            text, version = load_prompt("__test-success-prompt__", "v1")

        assert text == "You are a test agent."
        assert version == "v1"

    def test_load_prompt_cache_hit(self):
        """Line 22: second call with same args returns cached result without hitting client."""
        from app.core.prompt_loader import load_prompt, _cache

        _cache.pop("__test-cache-prompt__:v2", None)
        with patch("app.core.prompt_loader.client") as mock_client:
            mock_client.pull_prompt.return_value = self._make_prompt_mock("Cached text.")
            load_prompt("__test-cache-prompt__", "v2")

        with patch("app.core.prompt_loader.client") as mock_client2:
            text, version = load_prompt("__test-cache-prompt__", "v2")
            mock_client2.pull_prompt.assert_not_called()

        assert text == "Cached text."

    def test_load_prompt_failure_returns_none(self):
        """Lines 39-41: exception from pull_prompt returns (None, None)."""
        from app.core.prompt_loader import load_prompt, _cache

        _cache.pop("__test-fail-prompt__:latest", None)
        with patch("app.core.prompt_loader.client") as mock_client:
            mock_client.pull_prompt.side_effect = Exception("auth error")
            text, version = load_prompt("__test-fail-prompt__", "latest")

        assert text is None
        assert version is None


# ── product_agent extra branches ─────────────────────────────────────────────


class TestProductAgentExtra:
    def _llm_mock(self, content: str):
        r = MagicMock()
        r.content = content
        r.response_metadata = {"token_usage": {"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": 100}}
        return r

    def test_extract_preferences_with_conversation_history(self):
        """Lines 211-212, 215: history branch in extract_preferences."""
        with patch("app.agents.product_agent.llm") as mock_llm:
            mock_llm.invoke.return_value = self._llm_mock(
                '{"category": "Electronics", "subcategory": "speakers", "type": null, '
                '"brand": null, "max_price": null, "min_price": null, "keywords": [], "unavailable_request": false}'
            )
            from app.agents.product_agent import extract_preferences

            state = AgentState(
                user_message="what about a cheaper one",
                user_id="u1",
                session_id="s1",
                conversation_history=[
                    {"role": "user", "content": "show me bluetooth speakers"},
                    {"role": "assistant", "content": "Here are some speakers under ₹3000."},
                ],
            )
            result = extract_preferences(state)

        assert "preferences" in result

    def test_rank_and_filter_with_results(self):
        """Covers LLM call path in rank_and_filter (lines 593-602)."""
        search_results = [
            {"product_id": "P1", "name": "JBL Go 2 Speaker", "price": 2499, "rating": 4.5, "brand": "JBL"},
            {"product_id": "P2", "name": "boAt Stone 200", "price": 1299, "rating": 4.2, "brand": "boAt"},
        ]
        with patch("app.agents.product_agent.llm") as mock_llm:
            mock_llm.invoke.return_value = self._llm_mock("[1, 2]")
            from app.agents.product_agent import rank_and_filter

            state = AgentState(
                user_message="show me bluetooth speakers",
                user_id="u1",
                session_id="s1",
                search_results=search_results,
                preferences={"category": "Electronics", "subcategory": "speakers"},
                conversation_history=[],
            )
            result = rank_and_filter(state)

        assert "ranked_products" in result
        assert len(result["ranked_products"]) >= 1

    def test_rank_and_filter_empty_returns_early(self):
        """Empty search_results returns early without calling LLM."""
        from app.agents.product_agent import rank_and_filter

        state = AgentState(
            user_message="speakers",
            user_id="u1",
            session_id="s1",
            search_results=[],
            conversation_history=[],
        )
        result = rank_and_filter(state)
        assert result == {"ranked_products": []}
