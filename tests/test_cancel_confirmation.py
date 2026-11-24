"""Cancelling pauses the graph (interrupt); only the owner's Yes, while the order is processing, cancels it."""

from unittest.mock import patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import app.agents.router as router
import app.agents.support_agent as sa
from app.agents.router import RouteDecision

ORDER = {"order_id": "ORD-2005", "product_name": "Logitech M221 Wireless Mouse", "status": "processing"}
THREAD = {"configurable": {"thread_id": "cancel-test"}}


@pytest.fixture
def graph():
    return router.build_router_graph(InMemorySaver())


def ask_to_cancel(graph, message="cancel ORD-2005"):
    decision = RouteDecision(intent="support", order_id="ORD-2005", issue="cancel")
    with patch.object(router, "call_llm", return_value=decision), patch.object(
        router, "fetch_user_orders", return_value=[ORDER]
    ), patch.object(sa, "fetch_order_from_db", return_value=ORDER), patch.object(sa, "cancel_order_in_db") as cancel:
        out = graph.invoke(router.new_turn(message, "demo-user-1", "s1", []), THREAD)
    cancel.assert_not_called()
    return out


def answer(graph, confirm, user="demo-user-1", db_says=True):
    with patch.object(sa, "cancel_order_in_db", return_value=db_says) as cancel:
        out = graph.invoke(Command(resume={"confirm": confirm, "user_id": user}), THREAD)
    return out, cancel


class TestPause:
    def test_asking_pauses_and_cancels_nothing(self, graph):
        out = ask_to_cancel(graph)
        question = out["__interrupt__"][0].value
        assert (question["type"], question["order_id"]) == ("confirm_cancel", "ORD-2005")
        assert "Do you want to cancel it?" in question["question"]
        assert graph.get_state(THREAD).interrupts

    def test_yes_from_the_owner_cancels(self, graph):
        ask_to_cancel(graph)
        out, cancel = answer(graph, True)
        cancel.assert_called_once_with("ORD-2005", "demo-user-1")
        assert "has been cancelled" in out["final_response"]
        assert not graph.get_state(THREAD).interrupts

    def test_yes_from_another_user_is_refused(self, graph):
        ask_to_cancel(graph)
        out, cancel = answer(graph, True, user="test-user-99")
        cancel.assert_not_called()
        assert "couldn't cancel" in out["final_response"]

    def test_yes_after_the_order_shipped_is_refused(self, graph):
        ask_to_cancel(graph)
        out, cancel = answer(graph, True, db_says=False)  # the database re-check: no longer processing
        cancel.assert_called_once()
        assert "couldn't cancel" in out["final_response"]

    def test_no_keeps_the_order(self, graph):
        ask_to_cancel(graph)
        out, cancel = answer(graph, False)
        cancel.assert_not_called()
        assert "still active" in out["final_response"]

    def test_a_new_message_discards_the_pause(self, graph):
        ask_to_cancel(graph)
        with patch.object(router, "call_llm", return_value=RouteDecision(intent="unclear", reply="Hi!")):
            out = graph.invoke(router.new_turn("hello", "demo-user-1", "s1", []), THREAD)
        assert out["final_response"] == "Hi!"
        assert not graph.get_state(THREAD).interrupts


class TestResumeEndpoint:
    def test_confirm_with_nothing_pending_is_refused(self, client):
        with patch("app.agents.support_agent.cancel_order_in_db") as cancel:
            r = client.post("/chat", json={"message": "Yes", "confirm": True}, headers={"x-user-id": "demo-user-1"})
        assert r.status_code == 200 and "nothing waiting" in r.json()["response"]
        cancel.assert_not_called()

    def test_confirm_on_someone_elses_conversation_is_refused(self, client):
        with patch("app.main.router_graph.invoke", return_value={"final_response": "Hello!"}):
            session_id = client.post("/chat", json={"message": "hi"}, headers={"x-user-id": "demo-user-1"}).json()[
                "session_id"
            ]
        with patch("app.main.router_graph.invoke") as invoke:
            r = client.post(
                "/chat",
                json={"message": "Yes", "confirm": True, "session_id": session_id},
                headers={"x-user-id": "test-user-99"},
            )
        invoke.assert_not_called()
        assert "sign in to the account" in r.json()["response"]

    def test_anonymous_confirm_is_refused(self, client):
        with patch("app.main.router_graph.invoke") as invoke:
            r = client.post("/chat", json={"message": "Yes", "confirm": True})
        invoke.assert_not_called()
        assert "sign in" in r.json()["response"]
