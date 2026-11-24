"""The shared LLM wrapper: one model, usage recorded, structured replies parsed."""

from unittest.mock import MagicMock, patch

from pydantic import BaseModel

import app.core.llm as llm_module


class Answer(BaseModel):
    value: int


def _message(content="hi", tokens=12):
    m = MagicMock()
    m.content = content
    m.response_metadata = {"token_usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": tokens}}
    return m


def test_text_call_returns_stripped_content():
    fake = MagicMock()
    fake.invoke.return_value = _message("  hello  ")
    with patch.object(llm_module, "llm", fake):
        assert llm_module.call_llm("router", "classify", ["msg"]) == "hello"
    metadata = fake.invoke.call_args.kwargs["config"]["metadata"]
    assert (metadata["agent"], metadata["node"]) == ("router", "classify")


def test_structured_call_returns_parsed_object():
    fake = MagicMock()
    fake.with_structured_output.return_value.invoke.return_value = {
        "raw": _message(),
        "parsed": Answer(value=3),
        "parsing_error": None,
    }
    with patch.object(llm_module, "llm", fake):
        assert llm_module.call_llm("product", "extract", ["msg"], schema=Answer) == Answer(value=3)
    fake.with_structured_output.assert_called_once_with(Answer, include_raw=True)


def test_structured_parse_error_returns_none():
    fake = MagicMock()
    fake.with_structured_output.return_value.invoke.return_value = {
        "raw": _message(),
        "parsed": None,
        "parsing_error": ValueError("bad enum"),
    }
    with patch.object(llm_module, "llm", fake):
        assert llm_module.call_llm("product", "extract", ["msg"], schema=Answer) is None


def test_missing_usage_metadata_is_tolerated():
    fake = MagicMock()
    msg = MagicMock()
    msg.content = "ok"
    msg.response_metadata = None
    fake.invoke.return_value = msg
    with patch.object(llm_module, "llm", fake):
        assert llm_module.call_llm("order", "reply", ["msg"]) == "ok"
