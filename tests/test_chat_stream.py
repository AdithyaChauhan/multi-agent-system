"""/chat/stream: step labels while the graph runs, then the same reply /chat gives."""

import json
from unittest.mock import patch

import app.agents.product_agent as pa
import app.agents.router as router
from app.agents.router import RouteDecision

MOUSE = {
    "product_id": "P1",
    "name": "Logitech Mouse",
    "brand": "Logitech",
    "price": 500,
    "rating": 4.2,
    "type": "mouse",
}


def _events(text: str) -> list:
    """Parse a server-sent-events body into (event, data) pairs."""
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def _product_turn(client, path):
    with patch.object(router, "call_llm", return_value=RouteDecision(intent="product")), patch.object(
        pa, "call_llm", side_effect=[pa.ProductSearch(product="mouse"), pa.Ranking(same_kind=[1], exact=[1])]
    ), patch.object(pa, "search_products", return_value=[MOUSE]):
        return client.post(path, json={"message": "mouse"}, headers={"x-user-id": "stream-user"})


def test_steps_then_the_same_reply_as_chat(client, yaml_catalog):
    streamed = _product_turn(client, "/chat/stream")
    assert streamed.status_code == 200 and streamed.headers["content-type"].startswith("text/event-stream")
    events = _events(streamed.text)
    labels = [data["label"] for name, data in events if name == "step"]
    assert labels == [
        "Understanding your message…",
        "Working out what you're looking for…",
        "Searching products…",
        "Picking the best matches…",
    ]
    name, reply = events[-1]
    assert name == "reply" and streamed.headers["x-session-id"] == reply["session_id"]

    plain = _product_turn(client, "/chat").json()
    assert reply["response"] == plain["response"] and "Logitech Mouse" in reply["response"]
    assert set(reply) == set(plain)


def test_a_failing_turn_ends_with_an_error_event(client):
    with patch.object(router, "call_llm", side_effect=RuntimeError("boom")):
        events = _events(client.post("/chat/stream", json={"message": "hi"}).text)
    assert events[-1][0] == "error" and "boom" not in events[-1][1]["detail"]


def test_a_refused_confirm_is_a_single_reply(client):
    events = _events(client.post("/chat/stream", json={"message": "Yes", "confirm": True}).text)
    assert [name for name, _ in events] == ["reply"] and "sign in" in events[0][1]["response"]


def test_chips_come_back_and_removing_one_skips_every_model_call(client, yaml_catalog):
    with patch.object(router, "call_llm", return_value=RouteDecision(intent="product")), patch.object(
        pa, "call_llm", side_effect=[pa.ProductSearch(product="mouse", brand="Logitech"), pa.Ranking(same_kind=[1])]
    ), patch.object(pa, "search_products", return_value=[MOUSE]):
        first = client.post("/chat", json={"message": "logitech mouse"}, headers={"x-user-id": "chip-user"}).json()
    assert [c["label"] for c in first["active_filters"]] == ["mouse", "Logitech"]

    with patch.object(router, "call_llm") as router_model, patch.object(pa, "call_llm") as product_model, patch.object(
        pa, "search_products", return_value=[MOUSE]
    ) as search:
        second = client.post(
            "/chat",
            json={"message": "Remove Logitech", "remove_filter": {"field": "brand"}, "session_id": first["session_id"]},
            headers={"x-user-id": "chip-user"},
        ).json()
    router_model.assert_not_called()
    product_model.assert_not_called()
    assert search.call_args.kwargs["brand"] is None and search.call_args.kwargs["product_type"] == "mouse"
    assert [c["label"] for c in second["active_filters"]] == ["mouse"]
