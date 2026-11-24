"""Keep personal data out of logs and LangSmith traces (ADR 0015): emails and phone numbers.

Order ids (ORD-2002), prices and model numbers are left alone: only an email address or a
10-digit Indian mobile number (optionally +91) is masked.
"""

import logging
import os
import re

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<![\w+])(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\w)")
EMAIL_MASK = "[email]"
PHONE_MASK = "[phone]"


def redact(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text
    return PHONE.sub(PHONE_MASK, EMAIL.sub(EMAIL_MASK, text))


class RedactingFilter(logging.Filter):
    """Masks emails and phone numbers in every log line before any handler writes it."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        return True


def install_trace_anonymizer() -> bool:
    """Make every LangSmith trace pass through the same masking. Returns whether it was installed."""
    if os.getenv("LANGCHAIN_TRACING_V2", "").lower() != "true" and os.getenv("LANGSMITH_TRACING", "").lower() != "true":
        return False
    try:
        import langsmith.run_trees as run_trees
        from langsmith import Client
        from langsmith.anonymizer import create_anonymizer

        anonymizer = create_anonymizer(
            [{"pattern": EMAIL, "replace": EMAIL_MASK}, {"pattern": PHONE, "replace": PHONE_MASK}]
        )
        api_key = os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY")
        run_trees._CLIENT = Client(api_key=api_key, anonymizer=anonymizer)
        return True
    except Exception:  # tracing is optional; never block the app on it
        return False
