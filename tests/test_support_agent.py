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
    def test_processing_asks_for_ui_confirmation_and_cancels_nothing(self):
        out = sa.handle_cancellation({"support_order": _order("processing")})
        assert out["action_required"] == {
            "type": "confirm_cancel",
            "order_id": "ORD-2005",
            "product_name": "Logitech M221 Wireless Mouse",
        }

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
        out = sa.handle_cancellation({"support_order": _order(status)})
        assert phrase in out["final_response"] and "action_required" not in out


class TestCreateTicket:
    def test_one_open_ticket_per_order(self):
        with patch.object(sa, "get_open_ticket_for_order", return_value={"ticket_id": "TKT-OLD"}), patch.object(
            sa, "create_support_ticket"
        ) as create:
            out = sa.create_ticket(_state("damaged_delivery", _order("delivered", "ORD-2004")))
        create.assert_not_called()
        assert "already have an open ticket **TKT-OLD**" in out["final_response"]

    def test_creates_medium_ticket(self):
        with patch.object(sa, "get_open_ticket_for_order", return_value=None), patch.object(
            sa, "create_support_ticket", return_value={"ticket_id": "TKT-NEW"}
        ) as create:
            out = sa.create_ticket(_state("wrong_item", _order("delivered", "ORD-2001")))
        kwargs = create.call_args.kwargs
        assert (kwargs["severity"], kwargs["category"], kwargs["order_id"]) == ("medium", "wrong_item", "ORD-2001")
        assert "TKT-NEW" in out["final_response"]

    def test_legal_threat_without_order_is_tagged(self):
        with patch.object(sa, "create_support_ticket", return_value={"ticket_id": "TKT-L"}) as create:
            sa.create_ticket(_state("account_data", risk="legal"))
        kwargs = create.call_args.kwargs
        assert kwargs["category"] == "other" and kwargs["order_id"] is None
        assert kwargs["description"].startswith("[P2] [LEGAL]")


def test_draft_resolution_sends_policy_and_order():
    with patch.object(sa, "call_llm", return_value="We'll send the missing part.") as call:
        out = sa.draft_resolution(_state("missing_parts", _order("delivered", "ORD-2004")))
    assert out["final_response"] == "We'll send the missing part."
    context = call.call_args.args[2][1].content
    assert "ORD-2004" in context and "Policy:" in context and "missing parts" in context


def test_graph_end_to_end_cancel():
    with patch.object(sa, "fetch_order_from_db", return_value=_order("processing")):
        out = sa.support_agent_graph.invoke(
            {"user_id": "demo-user-1", "order_id": "ORD-2005", "support_issue": {"category": "cancel"}}
        )
    assert out["action_required"]["type"] == "confirm_cancel"
