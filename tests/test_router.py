"""Router: one structured LLM decision, deterministic routing and guardrails."""

from unittest.mock import patch

import pytest

import app.agents.router as router
from app.agents.router import RouteDecision

ORDERS = [
    {"order_id": "ORD-2002", "product_name": "Mi 108cm Full HD Android LED TV", "status": "shipped"},
    {"order_id": "ORD-2005", "product_name": "Logitech M221 Wireless Mouse", "status": "processing"},
]


def _classify(decision, **state):
    state.setdefault("user_message", "hello")
    state.setdefault("user_id", "anon-1")
    with patch.object(router, "call_llm", return_value=decision) as call, patch.object(
        router, "fetch_user_orders", return_value=ORDERS
    ):
        return router.classify(state), call


class TestNormalizeOrderId:
    @pytest.mark.parametrize(
        "raw,expected",
        [("2002", "ORD-2002"), ("ord 2002", "ORD-2002"), ("ORD-9901", "ORD-9901"), ("the tv one", None), (None, None)],
    )
    def test_formats(self, raw, expected):
        assert router.normalize_order_id(raw) == expected


class TestClassify:
    def test_signed_in_user_orders_and_history_are_given_to_the_model(self):
        history = [{"role": "assistant", "content": "Which order? ORD-2002 ..."}]
        _, call = _classify(
            RouteDecision(intent="order", order_id="2002"),
            user_id="demo-user-1",
            user_message="2002 status",
            conversation_history=history,
        )
        human = call.call_args.args[2][1].content
        assert "ORD-2005 Logitech M221 Wireless Mouse (processing)" in human
        assert "Which order? ORD-2002" in human
        assert human.endswith("Message: 2002 status")

    def test_anonymous_user_orders_are_not_looked_up(self):
        _, call = _classify(RouteDecision(intent="product"))
        assert "not signed in" in call.call_args.args[2][1].content

    def test_decision_fields_are_copied_to_state(self):
        result, _ = _classify(
            RouteDecision(intent="support", order_id="ord-2004", issue="damaged_delivery", risk="legal"),
            user_message="the mixer broke, I'll sue",
        )
        assert result["intent"] == "support"
        assert result["order_id"] == "ORD-2004"
        assert result["support_issue"] == {"category": "damaged_delivery", "description": "the mixer broke, I'll sue"}
        assert result["risk"] == "legal"
        assert result["final_response"] is None

    def test_unclear_carries_the_model_reply(self):
        result, _ = _classify(RouteDecision(intent="unclear", reply="Hi! What do you need?"))
        assert result["final_response"] == "Hi! What do you need?"

    def test_unparseable_reply_is_unclear(self):
        result, _ = _classify(None)
        assert result["intent"] == "unclear"


class TestRoute:
    def test_safety_wins_over_intent_and_sign_in(self):
        assert router.route({"risk": "safety", "intent": "support", "user_id": "anon-1"}) == "safety"

    def test_unclear_goes_to_clarify(self):
        assert router.route({"intent": "unclear", "user_id": "u1"}) == "clarify"

    @pytest.mark.parametrize("intent", ["order", "support"])
    def test_orders_and_support_need_sign_in(self, intent):
        assert router.route({"intent": intent, "user_id": "anon-123"}) == "sign_in"
        assert router.route({"intent": intent, "user_id": "demo-user-1"}) == intent

    def test_products_need_no_sign_in(self):
        assert router.route({"intent": "product", "user_id": "anon-123"}) == "product"


class TestTerminalNodes:
    def test_clarify_uses_reply_or_fallback(self):
        assert router.clarify({"final_response": "Hello!"})["final_response"] == "Hello!"
        assert router.clarify({})["final_response"] == router.CLARIFY_FALLBACK

    def test_sign_in_mentions_sign_in(self):
        assert "Sign In" in router.respond_sign_in({"intent": "order"})["final_response"]
        assert "support ticket" in router.respond_sign_in({"intent": "support"})["final_response"]

    def test_safety_hands_a_critical_ticket_to_a_person(self):
        result = router.safety_escalation({"user_id": "u1", "user_message": "the heater caught fire"})
        request = result["escalation"]
        assert (request["severity"], request["safety_alert"], request["user_id"]) == ("critical", True, "u1")
        assert router.safety_reply({})["final_response"] == router.SAFETY_RESPONSE

    def test_safety_end_to_end_opens_the_ticket_and_alerts(self):
        import app.agents.escalation as esc

        decision = RouteDecision(intent="support", risk="safety")
        with patch.object(router, "call_llm", return_value=decision), patch.object(
            esc, "create_support_ticket", return_value={"ticket_id": "TKT-S", "severity": "critical"}
        ) as create, patch.object(esc.logger, "warning") as alert:
            out = router.router_graph.invoke(
                router.new_turn("the heater caught fire", "anon-1", "s-safety", []), _thread("safety")
            )
        assert out["route"] == "safety" and out["final_response"] == router.SAFETY_RESPONSE
        assert create.call_args.kwargs["safety_alert"] is True
        assert "TKT-S" in alert.call_args.args[0]  # no webhook configured: the alert goes to the log


def _thread(name: str) -> dict:
    return {"configurable": {"thread_id": f"test-{name}"}}


class TestGraph:
    def test_greeting_end_to_end(self):
        with patch.object(router, "call_llm", return_value=RouteDecision(intent="unclear", reply="Hi there!")):
            out = router.router_graph.invoke(
                {"user_message": "hi", "user_id": "anon-1", "conversation_history": []}, _thread("greeting")
            )
        assert out["final_response"] == "Hi there!"
        assert out["route"] == "clarify"

    def test_anonymous_order_request_asks_to_sign_in(self):
        with patch.object(router, "call_llm", return_value=RouteDecision(intent="order")):
            out = router.router_graph.invoke(
                {"user_message": "track my order", "user_id": "anon-1"}, _thread("sign-in")
            )
        assert out["route"] == "sign_in"

    def test_agent_internals_stay_inside_the_subgraph(self, yaml_catalog):
        import app.agents.product_agent as pa

        mouse = {"product_id": "P1", "name": "Mouse", "brand": "X", "price": 500, "rating": 4.0, "type": "mouse"}
        with patch.object(router, "call_llm", return_value=RouteDecision(intent="product")), patch.object(
            pa, "call_llm", side_effect=[pa.ProductSearch(product="mouse"), pa.Ranking(same_kind=[1])]
        ), patch.object(pa, "search_products", return_value=[mouse]):
            out = router.router_graph.invoke({"user_message": "mouse", "user_id": "anon-1"}, _thread("internals"))
        assert out["ranked_products"][0]["product_id"] == "P1"
        assert not {"search_results", "search_filters", "not_carried"} & set(out)


def test_current_message_is_not_repeated_in_history():
    history = [{"role": "user", "content": "4k monitor"}]
    _, call = _classify(RouteDecision(intent="product"), user_message="4k monitor", conversation_history=history)
    assert "Recent conversation" not in call.call_args.args[2][1].content


class TestCheckpointedThread:
    """One graph thread per chat session: filters carry over, a turn's answer doesn't."""

    TV = {"product_id": "T1", "name": "TV", "brand": "Samsung", "price": 20000, "rating": 4.0, "type": "tv"}

    def _turn(self, graph, message, decision, extracted=None):
        import app.agents.product_agent as pa

        replies = [extracted, pa.Ranking(same_kind=[1])] if extracted else []
        with patch.object(router, "call_llm", return_value=decision), patch.object(
            pa, "call_llm", side_effect=replies
        ) as call, patch.object(pa, "search_products", return_value=[self.TV]):
            out = graph.invoke(router.new_turn(message, "anon-1", "s1", []), {"configurable": {"thread_id": "s1"}})
        return out, call

    def test_filters_survive_a_restart(self, yaml_catalog):
        import app.agents.product_agent as pa
        from langgraph.checkpoint.memory import InMemorySaver

        saver = InMemorySaver()  # stands in for Postgres: shared by both "processes"
        product = RouteDecision(intent="product")
        self._turn(router.build_router_graph(saver), "tv", product, pa.ProductSearch(product="tv"))
        restarted = router.build_router_graph(saver)  # a new graph object, as after an app restart
        _, call = self._turn(restarted, "what about Samsung", product, pa.ProductSearch(product="tv", brand="Samsung"))
        assert '"product": "tv"' in call.call_args_list[0].args[2][1].content

    def test_last_turns_answer_is_cleared(self, yaml_catalog):
        import app.agents.product_agent as pa
        from langgraph.checkpoint.memory import InMemorySaver

        graph = router.build_router_graph(InMemorySaver())
        first, _ = self._turn(graph, "hi", RouteDecision(intent="unclear", reply="Hello!"))
        assert first["route"] == "clarify"
        second, _ = self._turn(graph, "tv", RouteDecision(intent="product"), pa.ProductSearch(product="tv"))
        assert second["route"] is None and second["ranked_products"][0]["product_id"] == "T1"
