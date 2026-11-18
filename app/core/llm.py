"""The one chat model every agent uses, plus a call wrapper that records usage.

Evals can record and replay model calls (see "Record / replay" below), so a rerun costs no tokens
and gets the same answers as long as prompts, schemas and the model are unchanged.
"""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from groq import BadRequestError
from langchain_groq import ChatGroq

from app.core.config import GROQ_MODEL
from app.core.logger import get_logger, get_request_id
from app.core.metrics import llm_duration_seconds, llm_requests_total, llm_tokens_total

load_dotenv()

logger = get_logger("app.core.llm")

llm = ChatGroq(model=GROQ_MODEL, temperature=0, api_key=os.getenv("GROQ_API_KEY"))


def _usage(message) -> dict:
    meta = getattr(message, "response_metadata", None)
    usage = meta.get("token_usage", {}) if isinstance(meta, dict) else {}
    return usage if isinstance(usage, dict) else {}


def _record(agent: str, node: str, message, seconds: float) -> dict:
    usage = _usage(message)
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
    return usage


def _invoke(agent: str, node: str, messages: list, schema=None):
    """One real model call. Returns (result, token usage)."""
    config = {"metadata": {"agent": agent, "node": node}}
    start = time.perf_counter()
    if schema is None:
        message = llm.invoke(messages, config=config)
        usage = _record(agent, node, message, time.perf_counter() - start)
        return (message.content or "").strip(), usage

    structured = llm.with_structured_output(schema, include_raw=True)
    for attempt in (1, 2):
        try:
            out = structured.invoke(messages, config=config)
            break
        except BadRequestError as exc:
            # Groq checks tool-call arguments against the schema and rejects malformed calls
            # (code tool_use_failed). Retry once, then let the caller fall back.
            if "tool_use_failed" not in str(exc):
                raise
            logger.error(f"request_id={get_request_id()} | {agent}.{node} tool_use_failed (attempt {attempt})")
            if attempt == 2:
                return None, {}
    usage = _record(agent, node, out.get("raw"), time.perf_counter() - start)
    if out.get("parsing_error"):
        logger.error(f"request_id={get_request_id()} | {agent}.{node} parse error | {out['parsing_error']}")
    return out.get("parsed"), usage


def call_llm(agent: str, node: str, messages: list, schema=None):
    """Invoke the model once.

    With `schema` (a Pydantic model) the reply is parsed through tool calling and the parsed
    object is returned, or None if the model returned nothing usable. Without it, the reply text.
    """
    mode = cassette_mode()
    if mode == "replay":
        return _replay(messages, schema)
    result, usage = _invoke(agent, node, messages, schema)
    if mode == "record":
        _store(agent, node, messages, schema, result, usage)
    return result


# ── Record / replay ────────────────────────────────────────────────────────────
# LLM_CASSETTE_MODE=record|replay and LLM_CASSETTE_PATH=<json file>. Record calls the model and
# saves each answer under a hash of (model, messages, schema). Replay never calls the network and
# raises CassetteMiss for a call it has no answer for, so a changed prompt can't pass silently.


class CassetteMiss(RuntimeError):
    """Replay mode has no recorded answer for this exact call."""


_cassette: Optional[dict] = None
_cassette_file: Optional[Path] = None


def cassette_mode() -> str:
    mode = os.getenv("LLM_CASSETTE_MODE", "").strip().lower()
    if mode not in ("", "record", "replay"):
        raise ValueError(f"LLM_CASSETTE_MODE must be record or replay, not {mode!r}")
    return mode


def _cassette_data() -> dict:
    global _cassette, _cassette_file
    path = Path(os.getenv("LLM_CASSETTE_PATH", "llm_cassette.json"))
    if _cassette is None or path != _cassette_file:
        _cassette_file = path
        _cassette = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return _cassette


def cassette_key(messages: list, schema=None) -> str:
    payload = {
        "model": llm.model_name,
        "messages": [[getattr(m, "type", type(m).__name__), getattr(m, "content", str(m))] for m in messages],
        "schema": None if schema is None else [schema.__name__, schema.model_json_schema()],
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _store(agent: str, node: str, messages: list, schema, result, usage: dict) -> None:
    if schema is not None and result is not None and hasattr(result, "model_dump"):
        value = result.model_dump(mode="json")
    else:
        value = result
    data = _cassette_data()
    data[cassette_key(messages, schema)] = {
        "agent": agent,
        "node": node,
        "model": llm.model_name,
        "message": str(getattr(messages[-1], "content", ""))[:200] if messages else "",
        "value": value,
        "total_tokens": usage.get("total_tokens", 0),
    }
    _cassette_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = _cassette_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_cassette_file)


def _replay(messages: list, schema=None):
    entry = _cassette_data().get(cassette_key(messages, schema))
    if entry is None:
        kind = schema.__name__ if schema is not None else "text"
        raise CassetteMiss(f"no recorded answer for this {kind} call in {_cassette_file}; record it again")
    value = entry["value"]
    if schema is None or value is None:
        return value
    return schema.model_validate(value)
