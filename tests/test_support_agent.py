"""Support agent: deterministic routing, owner-only orders, confirmed cancels, tickets for humans."""

from unittest.mock import patch

import pytest

import app.agents.support_agent as sa

ORDERS = [{"order_id": "ORD-2005", "product_name": "Logitech M221 Wireless Mouse", "status": "processing"}]


def _order(status, order_id="ORD-2005"):
    return {"order_id": order_id, "product_name": "Logitech M221 Wireless Mouse", "status": status}


def _state(issue, order=None, risk="none", **extra):
    return {
        "user_id": "demo-user-1",
        "user_message": "help",
        "support_issue": {"category": issue, "description": "help"},
        "support_order": order,
        "risk": risk,
        **extra,
    }


class TestFindOrder:
    def test_found_for_this_user(self):
        with patch.object(sa, "fetch_order_from_db", return_value=_order("processing")) as fetch:
            out = sa.find_order({"user_id": "demo-user-1", "order_id": "ORD-2005"})
        fetch.assert_called_once_with("ORD-2005", "demo-user-1")
        assert out == {"support_order": _order("processing"), "user_orders": None}

    def test_other_users_order_is_not_found(self):
        with patch.object(sa, "fetch_order_from_db", return_value=None), patch.object(
            sa, "fetch_user_orders", return_value=ORDERS
        ):
            out = sa.find_order({"user_id": "test-user-99", "order_id": "ORD-2005"})
        assert out["support_order"] is None and out["user_orders"] == ORDERS


class TestRouteSupport:
    @pytest.mark.parametrize(
        "state,expected",
        [
            (_state("policy_question"), "policy"),
            (_state("account_data"), "ticket"),
            (_state("other", risk="legal"), "ticket"),
            (_state("cancel"), "ask_order"),
            (_state("cancel", _order("processing")), "cancel"),
            (_state("damaged_delivery", _order("delivered")), "ticket"),
            (_state("refund_request", _order("delivered")), "ticket"),
            (_state("missing_parts", _order("delivered")), "draft"),
            (_state("other", _order("delivered")), "draft"),
        ],
    )
    def test_routes(self, state, expected):
        assert sa.route_support(state) == expected


class TestReplies:
    def test_policy(self):
        assert "30 days" in sa.answer_policy({})["final_response"]

    def test_ask_for_order_lists_orders(self):
        text = sa.ask_for_order({"user_orders": ORDERS, "order_id": None})["final_response"]
        assert "which order this is about" in text and "ORD-2005" in text

    def test_ask_for_order_named_order_not_found(self):
        text = sa.ask_for_order({"user_orders": ORDERS, "order_id": "ORD-9999"})["final_response"]
        assert "couldn't find order **ORD-9999**" in text

    def test_ask_for_order_without_orders(self):
        assert "couldn't find any orders" in sa.ask_for_order({"user_orders": []})["final_response"]


class TestCancellation:
    def test_processing_goes_on_to_ask_the_shopper(self):
        state = {"support_order": _order("processing")}
        assert sa.handle_cancellation(state) == {}
        assert sa.route_cancellation(state) == "confirm"  # the pause itself: tests/test_cancel_confirmation.py

    @pytest.mark.parametrize(
        "status,phrase",
        [
            ("shipped", "already shipped"),
            ("out_for_delivery", "already shipped"),
            ("delivered", "can't be cancelled"),
            ("cancelled", "already cancelled"),
            ("placed", "can't cancel it here"),
        ],
    )
    def test_other_statuses_cannot_be_cancelled(self, status, phrase):
        state = {"support_order": _order(status)}
        assert phrase in sa.handle_cancellation(state)["final_response"]
        assert sa.route_cancellation(state) == "done"


class TestCreateTicket:
    def test_one_open_ticket_per_order(self):
        with patch.object(sa, "get_open_ticket_for_order", return_value={"ticket_id": "TKT-OLD"}):
            out = sa.create_ticket(_state("damaged_delivery", _order("delivered", "ORD-2004")))
        assert out["escalation"] is None and sa.route_ticket(out) == "done"
        assert "already have an open ticket **TKT-OLD**" in out["final_response"]

    def test_hands_a_medium_ticket_to_the_escalation_subgraph(self):
        with patch.object(sa, "get_open_ticket_for_order", return_value=None):
            out = sa.create_ticket(_state("wrong_item", _order("delivered", "ORD-2001")))
        request = out["escalation"]
        assert (request["severity"], request["category"], request["order_id"]) == ("medium", "wrong_item", "ORD-2001")
        assert sa.route_ticket(out) == "escalate"

    def test_legal_threat_without_order_is_tagged(self):
        request = sa.create_ticket(_state("account_data", risk="legal"))["escalation"]
        assert request["category"] == "other" and request["order_id"] is None
        assert request["description"].startswith("[P2] [LEGAL]")

    def test_graph_opens_the_ticket_and_replies_with_its_id(self):
        import app.agents.escalation as esc

        with patch.object(sa, "fetch_order_from_db", return_value=_order("delivered", "ORD-2001")), patch.object(
            sa, "get_open_ticket_for_order", return_value=None
        ), patch.object(esc, "create_support_ticket", return_value={"ticket_id": "TKT-NEW"}) as create:
            out = sa.support_agent_graph.invoke(
                {**_state("wrong_item"), "order_id": "ORD-2001", "user_message": "wrong item arrived"}
            )
        assert create.call_args.kwargs["category"] == "wrong_item"
        assert "TKT-NEW" in out["final_response"] and "Wrong Item" in out["final_response"]


def test_draft_resolution_sends_policy_and_order():
    with patch.object(sa, "call_llm", return_value="We'll send the missing part.") as call:
        out = sa.draft_resolution(_state("missing_parts", _order("delivered", "ORD-2004")))
    assert out["final_response"] == "We'll send the missing part."
    context = call.call_args.args[2][1].content
    assert "ORD-2004" in context and "Policy:" in context and "missing parts" in context
