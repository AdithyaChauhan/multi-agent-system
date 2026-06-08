"""
Unit tests for support_agent.py node functions.
Covers _is_bare_order_lookup, fetch_order_for_support, ask_for_order,
lookup_policy, answer_policy_question, finalize_draft, classify_issue
branches, and all routing helpers.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.state import AgentState


def _state(**kwargs):
    defaults = dict(
        user_message="my item is broken",
        user_id="u1",
        session_id="s1",
        conversation_history=[],
        support_issue={"category": "defective", "order_id": None, "description": "broken item"},
        support_order={},
    )
    defaults.update(kwargs)
    return AgentState(**defaults)


def _mock_llm(content: str):
    m = MagicMock()
    resp = MagicMock(
        content=content,
        response_metadata={"token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
        tool_calls=None,
    )
    m.invoke.return_value = resp
    m.bind_tools.return_value = m
    return m


# ── _is_bare_order_lookup ─────────────────────────────────────────────────────


class TestIsBareOrderLookup:
    def _call(self, msg):
        from app.agents.support_agent import _is_bare_order_lookup

        return _is_bare_order_lookup(msg)

    def test_bare_digit_is_bare(self):
        assert self._call("9903") is True

    def test_ord_pattern_is_bare(self):
        assert self._call("ORD-2002") is True

    def test_short_no_keywords_is_bare(self):
        assert self._call("show my order") is True

    def test_with_complaint_keyword_not_bare(self):
        assert self._call("ORD-2002 is broken") is False

    def test_long_message_not_bare(self):
        assert self._call("I ordered something and it never arrived and I am very unhappy") is False


# ── classify_issue branches ───────────────────────────────────────────────────


class TestClassifyIssueBranches:
    def _run(self, llm_json, user_message="my order broke", state_order_id=None):
        from app.agents.support_agent import classify_issue

        state = _state(user_message=user_message, order_id=state_order_id)
        mock_llm = _mock_llm(json.dumps(llm_json))
        with patch("app.agents.support_agent.load_prompt", return_value=(None, None)), patch(
            "app.agents.support_agent.llm", mock_llm
        ):
            return classify_issue(state)

    def test_order_id_not_in_message_gets_cleared(self):
        # LLM extracts an order_id that is not in the user message → must be cleared
        result = self._run(
            llm_json={"category": "defective", "order_id": "ORD-9999", "description": "broken"},
            user_message="my headphones are broken",
        )
        assert result["support_issue"]["order_id"] is None

    def test_state_order_id_used_as_fallback(self):
        # LLM returns null order_id, but state carries one from router → use it
        result = self._run(
            llm_json={"category": "defective", "order_id": None, "description": "broken"},
            user_message="my item is broken",
            state_order_id="ORD-1234",
        )
        assert result["support_issue"]["order_id"] == "ORD-1234"


# ── fetch_order_for_support ───────────────────────────────────────────────────


class TestFetchOrderForSupport:
    def test_fetches_order_by_id(self):
        from app.agents.support_agent import fetch_order_for_support

        order = {"order_id": "ORD-1001", "product_name": "Headphones", "status": "delivered"}
        state = _state(
            user_message="my order is damaged",
            support_issue={"category": "defective", "order_id": "ORD-1001"},
        )
        with patch("app.agents.support_agent.fetch_order_from_db", return_value=order), patch(
            "app.agents.support_agent.get_open_ticket_for_order", return_value=None
        ):
            result = fetch_order_for_support(state)
        assert result["support_order"]["order_id"] == "ORD-1001"

    def test_normalises_bare_digit_order_id(self):
        from app.agents.support_agent import fetch_order_for_support

        order = {"order_id": "ORD-9903", "product_name": "TV", "status": "delivered"}
        state = _state(
            user_message="9903 is broken",
            support_issue={"category": "defective", "order_id": "9903"},
        )
        with patch("app.agents.support_agent.fetch_order_from_db", return_value=order), patch(
            "app.agents.support_agent.get_open_ticket_for_order", return_value=None
        ):
            result = fetch_order_for_support(state)
        assert result["support_order"] is not None

    def test_reroutes_bare_order_lookup(self):
        from app.agents.support_agent import fetch_order_for_support

        order = {"order_id": "ORD-2001", "product_name": "Mouse", "status": "delivered"}
        state = _state(
            user_message="ORD-2001",  # bare lookup — no complaint
            support_issue={"category": "other", "order_id": "ORD-2001"},
        )
        with patch("app.agents.support_agent.fetch_order_from_db", return_value=order), patch(
            "app.agents.support_agent.get_open_ticket_for_order", return_value=None
        ):
            result = fetch_order_for_support(state)
        assert result.get("reroute_to_order") is True

    def test_no_order_id_returns_user_orders(self):
        from app.agents.support_agent import fetch_order_for_support

        orders = [{"order_id": "ORD-0001", "product_name": "Keyboard", "status": "delivered"}]
        state = _state(user_message="my item is broken", support_issue={"category": "defective", "order_id": None})
        with patch("app.agents.support_agent.fetch_user_orders", return_value=orders):
            result = fetch_order_for_support(state)
        assert result["support_order"] is None
        assert result["user_orders"] == orders


# ── ask_for_order ─────────────────────────────────────────────────────────────


class TestAskForOrder:
    def test_no_orders_message(self):
        from app.agents.support_agent import ask_for_order

        result = ask_for_order(_state(user_orders=[]))
        assert "couldn't find" in result["final_response"].lower() or "no orders" in result["final_response"].lower()

    def test_with_orders_no_prior_id(self):
        from app.agents.support_agent import ask_for_order

        orders = [{"order_id": "ORD-1001", "product_name": "Headphones", "status": "delivered"}]
        state = _state(
            user_orders=orders,
            support_issue={"category": "defective", "order_id": None},
        )
        result = ask_for_order(state)
        assert "ORD-1001" in result["final_response"]
        assert "support ticket" in result["final_response"].lower()

    def test_with_orders_invalid_prior_id_shows_prefix(self):
        from app.agents.support_agent import ask_for_order

        orders = [{"order_id": "ORD-1001", "product_name": "Headphones", "status": "delivered"}]
        state = _state(
            user_orders=orders,
            support_issue={"category": "defective", "order_id": "ORD-9999"},
        )
        result = ask_for_order(state)
        assert "ORD-9999" in result["final_response"]

    def test_more_than_five_orders_shows_footer(self):
        from app.agents.support_agent import ask_for_order

        orders = [{"order_id": f"ORD-{100+i}", "product_name": f"Item {i}", "status": "delivered"} for i in range(8)]
        state = _state(user_orders=orders, support_issue={"category": "defective", "order_id": None})
        result = ask_for_order(state)
        assert "8" in result["final_response"]


# ── lookup_policy ─────────────────────────────────────────────────────────────


class TestLookupPolicy:
    def test_fetches_and_stores_policy(self):
        from app.agents.support_agent import lookup_policy

        mock_policy = {"auto_resolve": False, "response_time": "2 hours", "escalation_path": "tier-2"}
        state = _state(severity="medium", support_issue={"category": "defective", "order_id": None})
        with patch("app.agents.support_agent.lookup_support_policy", return_value=mock_policy):
            result = lookup_policy(state)
        assert result["policy"] == mock_policy


# ── finalize_draft ────────────────────────────────────────────────────────────


class TestFinalizeDraft:
    def test_generates_resolution_from_messages(self):
        from app.agents.support_agent import finalize_draft

        state = _state(
            severity="low",
            support_issue={"category": "defective", "order_id": "ORD-1001", "description": "broken"},
            support_order={"order_id": "ORD-1001", "product_name": "Mouse", "status": "delivered"},
            policy={"response_time": "24 hours"},
            messages=[],
        )
        mock_llm = _mock_llm("We're sorry to hear about the issue with your order. A replacement will be arranged.")
        with patch("app.agents.support_agent.load_prompt", return_value=(None, None)), patch(
            "app.agents.support_agent.llm", mock_llm
        ):
            result = finalize_draft(state)
        assert "final_response" in result
        assert len(result["final_response"]) > 0


# ── answer_policy_question ────────────────────────────────────────────────────


class TestAnswerPolicyQuestion:
    def test_returns_policy_response(self):
        from app.agents.support_agent import answer_policy_question

        result = answer_policy_question(_state())
        assert "final_response" in result
        assert len(result["final_response"]) > 0


# ── routing functions ─────────────────────────────────────────────────────────


class TestSupportRoutingFunctions:
    def test_route_after_classify_policy_question(self):
        from app.agents.support_agent import route_after_classify

        state = _state(support_issue={"category": "other", "order_id": None, "is_policy_question": True})
        assert route_after_classify(state) == "answer_policy"

    def test_route_after_classify_fetch_order(self):
        from app.agents.support_agent import route_after_classify

        state = _state(support_issue={"category": "defective", "order_id": None, "is_policy_question": False})
        assert route_after_classify(state) == "fetch_order"

    def test_route_after_order_fetch_reroute(self):
        from app.agents.support_agent import route_after_order_fetch

        assert route_after_order_fetch(_state(reroute_to_order=True)) == "reroute"

    def test_route_after_order_fetch_found(self):
        from app.agents.support_agent import route_after_order_fetch

        state = _state(support_order={"order_id": "ORD-1001"}, reroute_to_order=False)
        assert route_after_order_fetch(state) == "found"

    def test_route_after_order_fetch_legal_threat_escalates(self):
        from app.agents.support_agent import route_after_order_fetch

        state = _state(user_message="I will sue you", support_order=None, reroute_to_order=False)
        assert route_after_order_fetch(state) == "found"

    def test_route_after_order_fetch_not_found(self):
        from app.agents.support_agent import route_after_order_fetch

        state = _state(user_message="my item is damaged", support_order=None, reroute_to_order=False)
        assert route_after_order_fetch(state) == "not_found"

    def test_reroute_exit_returns_empty(self):
        from app.agents.support_agent import reroute_exit

        assert reroute_exit(_state()) == {}

    def test_route_by_severity_critical(self):
        from app.agents.support_agent import route_by_severity

        assert route_by_severity(_state(severity="critical")) == "high"

    def test_route_by_severity_medium(self):
        from app.agents.support_agent import route_by_severity

        assert route_by_severity(_state(severity="medium")) == "high"

    def test_route_by_severity_low(self):
        from app.agents.support_agent import route_by_severity

        assert route_by_severity(_state(severity="low")) == "low"
