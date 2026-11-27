"""Order agent: deterministic lookup (owner-only) and status replies."""

from unittest.mock import patch

import pytest

import app.agents.order_agent as oa

ORDERS = [
    {"order_id": "ORD-2004", "product_name": "Croma 500W Mixer Grinder", "status": "delivered"},
    {"order_id": "ORD-2003", "product_name": "Fire-Boltt Phoenix Smartwatch", "status": "shipped"},
]


def _order(status, **extra):
    return {
        "order_id": "ORD-1",
        "product_name": "Mixer",
        "status": status,
        "carrier": None,
        "tracking_id": None,
        **extra,
    }


class TestFindOrder:
    def test_lookup_is_scoped_to_the_user(self):
        with patch.object(oa, "fetch_user_orders", return_value=ORDERS), patch.object(
            oa, "fetch_order_from_db", return_value=None
        ) as fetch:
            out = oa.find_order({"user_id": "demo-user-1", "order_id": "ORD-9901"})
        fetch.assert_called_once_with("ORD-9901", "demo-user-1")
        assert out["order_data"] is None
        assert oa.route_after_find(out) == "not_found"

    def test_single_order_is_used_when_none_named(self):
        with patch.object(oa, "fetch_user_orders", return_value=ORDERS[:1]), patch.object(
            oa, "fetch_order_from_db", return_value=_order("delivered")
        ):
            out = oa.find_order({"user_id": "u1", "order_id": None})
        assert out["order_id"] == "ORD-2004"
        assert oa.route_after_find(out) == "status"

    def test_several_orders_and_none_named_lists_them(self):
        with patch.object(oa, "fetch_user_orders", return_value=ORDERS):
            out = oa.find_order({"user_id": "u1", "order_id": None})
        assert oa.route_after_find(out) == "list"

    def test_no_orders(self):
        with patch.object(oa, "fetch_user_orders", return_value=[]):
            out = oa.find_order({"user_id": "u1", "order_id": None})
        assert oa.route_after_find(out) == "no_orders"


class TestReplies:
    def test_list(self):
        text = oa.list_orders({"user_orders": ORDERS})["final_response"]
        assert "ORD-2004" in text and "ORD-2003" in text and "Please provide the order ID" in text

    def test_list_footer_when_more_than_five(self):
        many = [dict(ORDERS[0], order_id=f"ORD-{i}") for i in range(7)]
        assert "showing 5 most recent of 7 orders" in oa.list_orders({"user_orders": many})["final_response"]

    def test_not_found_lists_own_orders(self):
        text = oa.respond_not_found({"order_id": "ORD-7777", "user_orders": ORDERS})["final_response"]
        assert "couldn't find order **ORD-7777**" in text and "1. **ORD-2004**" in text

    def test_not_found_without_orders(self):
        assert "double-check" in oa.respond_not_found({"order_id": "ORD-7777", "user_orders": []})["final_response"]

    def test_no_orders(self):
        assert "couldn't find any orders" in oa.respond_no_orders({})["final_response"]


class TestOrderStatus:
    @pytest.mark.parametrize(
        "status,phrase",
        [
            ("delivered", "has been delivered"),
            ("shipped", "has shipped"),
            ("out_for_delivery", "is out for delivery"),
            ("processing", "being prepared"),
            ("cancelled", "was cancelled"),
            ("lost", "has status: lost"),
        ],
    )
    def test_each_status(self, status, phrase):
        with patch.object(oa, "fetch_tracking_info", return_value=None):
            assert phrase in oa.order_status({"order_data": _order(status)})["final_response"]

    def test_shipped_with_carrier_and_live_tracking(self):
        live = {"status": "In Transit", "current_location": "Mumbai Hub", "estimated_delivery": "2026-06-06"}
        order = _order("shipped", carrier="DTDC", tracking_id="TRK-1")
        with patch.object(oa, "fetch_tracking_info", return_value=live) as track:
            out = oa.order_status({"order_data": order})
        track.assert_called_once_with("TRK-1")
        text = out["final_response"]
        assert "with DTDC" in text and "In Transit at Mumbai Hub" in text
        assert "Expected delivery: 2026-06-06" in text and "Tracking ID: TRK-1" in text


def test_graph_end_to_end():
    with patch.object(oa, "fetch_user_orders", return_value=ORDERS), patch.object(
        oa, "fetch_order_from_db", return_value=dict(ORDERS[0], carrier="BlueDart", tracking_id="TRK-2004")
    ), patch.object(oa, "fetch_tracking_info", return_value=None):
        out = oa.order_agent_graph.invoke({"user_id": "demo-user-1", "order_id": "ORD-2004"})
    assert out["final_response"].startswith(
        "**Croma 500W Mixer Grinder** (order ORD-2004) has been delivered."  # neutral: no "Good news!"
    )
