"""Personal data stays out of logs and traces (ADR 0015)."""

import logging

import pytest

from app.core import redact


@pytest.mark.parametrize(
    "text, expected",
    [
        ("mail me at priya.s@example.co.in please", "mail me at [email] please"),
        ("call 9876543210 or +91 98765 43210", "call [phone] or [phone]"),
        ("ORD-2002 for 29999 rupees, model SM-A5560", "ORD-2002 for 29999 rupees, model SM-A5560"),
        ("tracking 1234567890123", "tracking 1234567890123"),
    ],
)
def test_redact(text, expected):
    assert redact.redact(text) == expected


def test_log_lines_are_masked(caplog):
    logger = logging.getLogger("test.redaction")
    logger.addFilter(redact.RedactingFilter())
    with caplog.at_level(logging.INFO, logger="test.redaction"):
        logger.info("user message=%s", "my email is a.b@gmail.com and phone 9123456789")
    assert caplog.records[0].getMessage() == "user message=my email is [email] and phone [phone]"


def test_app_loggers_have_the_filter():
    from app.core.logger import get_logger

    assert any(isinstance(f, redact.RedactingFilter) for f in get_logger("app.test.redaction").filters)


def test_trace_anonymizer_only_when_tracing(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    assert redact.install_trace_anonymizer() is False
