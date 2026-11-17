"""The one chat model every agent uses, plus a call wrapper that records usage."""

import os
import time

from dotenv import load_dotenv
from langchain_groq import ChatGroq

from app.core.config import GROQ_MODEL
from app.core.logger import get_logger, get_request_id
from app.core.metrics import llm_duration_seconds, llm_requests_total, llm_tokens_total

load_dotenv()

logger = get_logger("app.core.llm")

llm = ChatGroq(model=GROQ_MODEL, temperature=0, api_key=os.getenv("GROQ_API_KEY"))


def _record(agent: str, node: str, message, seconds: float) -> None:
    meta = getattr(message, "response_metadata", None)
    usage = meta.get("token_usage", {}) if isinstance(meta, dict) else {}
    usage = usage if isinstance(usage, dict) else {}
    logger.info(
        f"request_id={get_request_id()} | LLM_USAGE | agent={agent} | node={node}"
        f" | prompt_tokens={usage.get('prompt_tokens', 0)}"
        f" | completion_tokens={usage.get('completion_tokens', 0)}"
        f" | total_tokens={usage.get('total_tokens', 0)}"
        f" | latency_ms={int(seconds * 1000)}"
    )
    llm_requests_total.labels(agent=agent, node=node).inc()
    llm_duration_seconds.labels(agent=agent, node=node).observe(seconds)
    for kind in ("prompt", "completion", "total"):
        value = usage.get(f"{kind}_tokens", 0)
        if isinstance(value, (int, float)):
            llm_tokens_total.labels(agent=agent, node=node, token_type=kind).inc(value)


def call_llm(agent: str, node: str, messages: list, schema=None):
    """Invoke the model once.

    With `schema` (a Pydantic model) the reply is parsed through tool calling and the parsed
    object is returned, or None if the model returned nothing usable. Without it, the reply text.
    """
    config = {"metadata": {"agent": agent, "node": node}}
    start = time.perf_counter()
    if schema is None:
        message = llm.invoke(messages, config=config)
        _record(agent, node, message, time.perf_counter() - start)
        return (message.content or "").strip()

    out = llm.with_structured_output(schema, include_raw=True).invoke(messages, config=config)
    _record(agent, node, out.get("raw"), time.perf_counter() - start)
    if out.get("parsing_error"):
        logger.error(f"request_id={get_request_id()} | {agent}.{node} parse error | {out['parsing_error']}")
    return out.get("parsed")
