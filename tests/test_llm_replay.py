"""Record / replay of model calls: reruns cost nothing and give the same answers."""

import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

import app.core.llm as llm_module


class Answer(BaseModel):
    value: int


MESSAGES = [SystemMessage(content="You answer with a number."), HumanMessage(content="two plus one")]


def _fake_model(parsed=None, text="hello"):
    fake = MagicMock()
    fake.model_name = "test-model"
    raw = MagicMock()
    raw.content = text
    raw.response_metadata = {"token_usage": {"total_tokens": 42}}
    fake.invoke.return_value = raw
    fake.with_structured_output.return_value.invoke.return_value = {"raw": raw, "parsed": parsed, "parsing_error": None}
    return fake


def _offline_model():
    """A model that fails if anything tries to call it."""
    fake = MagicMock()
    fake.model_name = "test-model"
    fake.invoke.side_effect = AssertionError("replay must not call the model")
    fake.with_structured_output.side_effect = AssertionError("replay must not call the model")
    return fake


@pytest.fixture
def cassette(tmp_path, monkeypatch):
    path = tmp_path / "cassette.json"
    monkeypatch.setenv("LLM_CASSETTE_PATH", str(path))
    monkeypatch.setattr(llm_module, "_cassette", None)
    return path


def _replay_mode(monkeypatch):
    monkeypatch.setenv("LLM_CASSETTE_MODE", "replay")
    monkeypatch.setattr(llm_module, "_cassette", None)  # force a fresh read from disk


def test_structured_answer_is_recorded_and_replayed_without_the_model(cassette, monkeypatch):
    monkeypatch.setenv("LLM_CASSETTE_MODE", "record")
    with patch.object(llm_module, "llm", _fake_model(parsed=Answer(value=3))):
        assert llm_module.call_llm("product", "extract", MESSAGES, schema=Answer) == Answer(value=3)
    entry = next(iter(json.loads(cassette.read_text(encoding="utf-8")).values()))
    assert entry["value"] == {"value": 3} and entry["total_tokens"] == 42 and entry["node"] == "extract"

    _replay_mode(monkeypatch)
    with patch.object(llm_module, "llm", _offline_model()):
        assert llm_module.call_llm("product", "extract", MESSAGES, schema=Answer) == Answer(value=3)


def test_text_answer_round_trips(cassette, monkeypatch):
    monkeypatch.setenv("LLM_CASSETTE_MODE", "record")
    with patch.object(llm_module, "llm", _fake_model(text="  four  ")):
        assert llm_module.call_llm("support", "draft", MESSAGES) == "four"
    _replay_mode(monkeypatch)
    with patch.object(llm_module, "llm", _offline_model()):
        assert llm_module.call_llm("support", "draft", MESSAGES) == "four"


def test_unusable_answer_replays_as_none(cassette, monkeypatch):
    monkeypatch.setenv("LLM_CASSETTE_MODE", "record")
    with patch.object(llm_module, "llm", _fake_model(parsed=None)):
        assert llm_module.call_llm("product", "extract", MESSAGES, schema=Answer) is None
    _replay_mode(monkeypatch)
    with patch.object(llm_module, "llm", _offline_model()):
        assert llm_module.call_llm("product", "extract", MESSAGES, schema=Answer) is None


def test_replay_of_an_unrecorded_call_fails_loudly(cassette, monkeypatch):
    _replay_mode(monkeypatch)
    with patch.object(llm_module, "llm", _offline_model()):
        with pytest.raises(llm_module.CassetteMiss):
            llm_module.call_llm("product", "extract", MESSAGES, schema=Answer)


def test_key_depends_on_messages_schema_and_model():
    with patch.object(llm_module, "llm", _fake_model()):
        base = llm_module.cassette_key(MESSAGES, Answer)
        assert base == llm_module.cassette_key(list(MESSAGES), Answer)
        assert base != llm_module.cassette_key([MESSAGES[0], HumanMessage(content="two plus two")], Answer)
        assert base != llm_module.cassette_key(MESSAGES, None)
    other = _fake_model()
    other.model_name = "another-model"
    with patch.object(llm_module, "llm", other):
        assert base != llm_module.cassette_key(MESSAGES, Answer)


def test_unknown_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("LLM_CASSETTE_MODE", "replya")
    with pytest.raises(ValueError):
        llm_module.call_llm("router", "classify", MESSAGES)


def test_no_mode_calls_the_model_and_writes_nothing(cassette, monkeypatch):
    monkeypatch.delenv("LLM_CASSETTE_MODE", raising=False)
    with patch.object(llm_module, "llm", _fake_model(text="live")):
        assert llm_module.call_llm("router", "classify", MESSAGES) == "live"
    assert not cassette.exists()
