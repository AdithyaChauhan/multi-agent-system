"""Escalation subgraph: open a ticket, then alert a person (webhook, or the log when unset)."""

from unittest.mock import MagicMock, patch

import app.agents.escalation as esc

REQUEST = {"user_id": "u1", "severity": "critical", "category": "other", "description": "[SAFETY_ALERT] fire"}
TICKET = {"ticket_id": "TKT-1", "severity": "critical"}


def test_opens_the_ticket_then_notifies():
    with patch.object(esc, "create_support_ticket", return_value=TICKET) as create, patch.object(
        esc, "ESCALATION_WEBHOOK_URL", ""
    ), patch.object(esc.logger, "warning") as warn:
        out = esc.escalation_graph.invoke({"escalation": REQUEST})
    create.assert_called_once_with(**REQUEST)
    assert out == {"ticket": TICKET}
    assert "TKT-1" in warn.call_args.args[0] and "[CRITICAL]" in warn.call_args.args[0]


def test_webhook_gets_the_alert():
    ok = MagicMock()
    with patch.object(esc, "ESCALATION_WEBHOOK_URL", "https://hooks.example/abc"), patch.object(
        esc.httpx, "post", return_value=ok
    ) as post:
        esc.notify({"escalation": {**REQUEST, "order_id": "ORD-1"}, "ticket": TICKET})
    url, body = post.call_args.args[0], post.call_args.kwargs["json"]
    assert url == "https://hooks.example/abc"
    assert body["text"] == body["content"] and "TKT-1" in body["text"] and "order ORD-1" in body["text"]
    ok.raise_for_status.assert_called_once()


def test_a_failed_alert_does_not_break_the_reply():
    with patch.object(esc, "ESCALATION_WEBHOOK_URL", "https://hooks.example/abc"), patch.object(
        esc.httpx, "post", side_effect=esc.httpx.ConnectError("down")
    ), patch.object(esc.logger, "error") as error:
        assert esc.notify({"escalation": REQUEST, "ticket": TICKET}) == {}
    assert "alert failed" in error.call_args.args[0]
