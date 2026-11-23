"""Fallback chain, answer cache and limits (ADR 0015): the demo answers even when a model can't."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from groq import APIConnectionError, BadRequestError, InternalServerError, NotFoundError, RateLimitError

import app.core.llm as llm_module
from app.core import config, limits

REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def _error(cls, status, message="error", headers=None):
    return cls(message, response=httpx.Response(status, request=REQUEST, headers=headers or {}), body=None)


def _client(name, answer="hello", error=None):
    fake = MagicMock()
    fake.model_name = name
    if error is not None:
        fake.invoke.side_effect = error
    else:
        msg = MagicMock()
        msg.content = answer
        msg.response_metadata = {"token_usage": {"total_tokens": 5}}
        fake.invoke.return_value = msg
    return fake


@pytest.fixture
def chain(monkeypatch):
    """Primary 'm1' plus fallbacks 'm2' and 'm3'; no cassette mode, so the chain is live."""
    monkeypatch.delenv("LLM_CASSETTE_MODE", raising=False)
    monkeypatch.setattr(config, "LLM_FALLBACK", True)
    monkeypatch.setattr(config, "GROQ_FALLBACK_MODELS", ["m2", "m3"])
    monkeypatch.setattr(llm_module, "_cooling", {})

    def install(primary, *fallbacks):
        monkeypatch.setattr(llm_module, "llm", primary)
        monkeypatch.setattr(llm_module, "_fallback_clients", {c.model_name: c for c in fallbacks})

    return install


class TestFallbackChain:
    @pytest.mark.parametrize(
        "error",
        [
            _error(RateLimitError, 429, "Rate limit reached: tokens per minute"),
            _error(InternalServerError, 500),
            _error(NotFoundError, 404, "The model `old-model` does not exist"),
            APIConnectionError(request=REQUEST),
        ],
        ids=["rate_limit", "server_error", "model_retired", "unreachable"],
    )
    def test_next_model_answers(self, chain, error):
        m1, m2 = _client("m1", error=error), _client("m2", answer="from m2")
        chain(m1, m2, _client("m3"))
        assert llm_module.call_llm("router", "classify", ["hi"]) == "from m2"
        assert m1.invoke.called and m2.invoke.called

    def test_all_models_down_raises_models_unavailable(self, chain):
        down = _error(InternalServerError, 503)
        chain(_client("m1", error=down), _client("m2", error=down), _client("m3", error=down))
        with pytest.raises(llm_module.ModelsUnavailable):
            llm_module.call_llm("router", "classify", ["hi"])

    def test_other_errors_are_not_hidden(self, chain):
        bad = _error(BadRequestError, 400, "invalid request")
        m2 = _client("m2")
        chain(_client("m1", error=bad), m2, _client("m3"))
        with pytest.raises(BadRequestError):
            llm_module.call_llm("router", "classify", ["hi"])
        m2.invoke.assert_not_called()

    def test_rate_limited_model_cools_down(self, chain):
        daily = _error(RateLimitError, 429, "Rate limit reached for model: tokens per day (TPD)")
        m1, m2 = _client("m1", error=daily), _client("m2", answer="ok")
        chain(m1, m2, _client("m3"))
        llm_module.call_llm("router", "classify", ["one"])
        llm_module.call_llm("router", "classify", ["two"])
        assert m1.invoke.call_count == 1  # skipped on the second call
        assert llm_module._cooldown_seconds(daily) == 600.0

    def test_retry_after_header_sets_the_cooldown(self):
        assert llm_module._cooldown_seconds(_error(RateLimitError, 429, "tpm", {"retry-after": "7"})) == 7.0

    def test_evals_pin_one_model(self, chain, monkeypatch):
        m1, m2 = _client("m1", error=_error(InternalServerError, 500)), _client("m2")
        chain(m1, m2)
        monkeypatch.setattr(config, "LLM_FALLBACK", False)
        with pytest.raises(llm_module.ModelsUnavailable):
            llm_module.call_llm("router", "classify", ["hi"])
        m2.invoke.assert_not_called()


class TestAnswerCache:
    def test_same_call_is_answered_once(self, chain):
        m1 = _client("m1", answer="hello")
        chain(m1)
        assert llm_module.call_llm("router", "classify", ["same"]) == "hello"
        assert llm_module.call_llm("router", "classify", ["same"]) == "hello"
        assert m1.invoke.call_count == 1
        llm_module.call_llm("router", "classify", ["different"])
        assert m1.invoke.call_count == 2

    def test_expired_entries_are_not_used(self, chain, monkeypatch):
        m1 = _client("m1")
        chain(m1)
        monkeypatch.setattr(config, "LLM_CACHE_SECONDS", 0)
        llm_module.call_llm("router", "classify", ["x"])
        llm_module.call_llm("router", "classify", ["x"])
        assert m1.invoke.call_count == 2


class TestLimits:
    def test_rate_per_minute(self, monkeypatch):
        monkeypatch.setattr(config, "CHAT_RATE_PER_MINUTE", 3)
        key = limits.caller_key("demo-user-1", "1.2.3.4")
        assert [limits.check_turn(key) for _ in range(3)] == [None, None, None]
        assert limits.check_turn(key) == limits.RATE_LIMITED
        assert limits.check_turn(limits.caller_key("demo-user-2", "1.2.3.4")) is None  # per caller

    def test_daily_budget(self, monkeypatch):
        monkeypatch.setattr(config, "CHAT_TURNS_PER_DAY", 2)
        key = limits.caller_key("anon-abc", "5.6.7.8")
        assert key == "ip:5.6.7.8"  # anonymous callers are counted by IP, not by session
        limits.check_turn(key)
        limits.check_turn(key)
        assert limits.check_turn(key) == limits.DAILY_LIMIT


class TestChatEndpoint:
    def test_busy_reply_instead_of_an_error_page(self, client):
        with patch("app.main.router_graph") as graph:
            graph.invoke.side_effect = llm_module.ModelsUnavailable("all down")
            r = client.post("/chat", json={"message": "tv under 30000"})
        assert r.status_code == 200
        assert (
            r.json()["response"]
            == "I'm getting a lot of questions right now and couldn't answer this one. Please try again in a minute."
        )

    def test_rate_limited_reply(self, client, monkeypatch):
        monkeypatch.setattr(config, "CHAT_RATE_PER_MINUTE", 1)
        with patch("app.main.router_graph") as graph:
            graph.invoke.return_value = {"final_response": "ok"}
            first = client.post("/chat", json={"message": "hi"})
            second = client.post("/chat", json={"message": "hi again"})
        assert first.json()["response"] == "ok"
        assert second.status_code == 200 and second.json()["response"] == limits.RATE_LIMITED
        assert graph.invoke.call_count == 1


class TestIdentity:
    def test_x_user_id_is_ignored_unless_enabled(self, client, monkeypatch):
        monkeypatch.setenv("ALLOW_X_USER_ID", "false")
        with patch("app.main.router_graph") as graph:
            graph.invoke.return_value = {"final_response": "ok"}
            r = client.post("/chat", json={"message": "where is my order"}, headers={"X-User-ID": "demo-user-2"})
        assert r.headers["X-User-ID"].startswith("anon-")  # treated as an anonymous caller

    def test_demo_login_only_for_seeded_demo_accounts(self, client):
        assert client.post("/auth/demo-login", json={"user_id": "someone@gmail.com"}).status_code == 403
        assert client.post("/auth/demo-login", json={"user_id": "demo-user-999"}).status_code == 403


def test_retired_model_is_skipped_after_the_first_failure(chain):
    m1 = _client("m1", error=_error(NotFoundError, 404, "The model `m1` does not exist"))
    m2 = _client("m2", answer="ok")
    chain(m1, m2, _client("m3"))
    llm_module.call_llm("router", "classify", ["one"])
    llm_module.call_llm("router", "classify", ["two"])
    assert m1.invoke.call_count == 1
