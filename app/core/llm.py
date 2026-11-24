"""The chat model every agent uses, plus a call wrapper that records usage.

Calls go to GROQ_MODEL first; if it's rate-limited, down or retired, the next model in
GROQ_FALLBACK_MODELS answers (ADR 0015). If none can, ModelsUnavailable is raised and the API turns
it into a friendly "busy" reply. Identical calls within LLM_CACHE_SECONDS reuse the answer.

Evals can record and replay model calls (see "Record / replay" below), so a rerun costs no tokens
and gets the same answers as long as prompts, schemas and the model are unchanged.
"""

import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
)
from langchain_core.messages import AIMessage
from langchain_groq import ChatGroq

from app.core import config
from app.core.config import GROQ_MODEL
from app.core.logger import get_logger, get_request_id
from app.core.metrics import (
    llm_cache_hits_total,
    llm_duration_seconds,
    llm_fallback_total,
    llm_requests_total,
    llm_tokens_total,
    llm_unavailable_total,
)

load_dotenv()

logger = get_logger("app.core.llm")


def _new_client(model: str) -> ChatGroq:
    # No SDK retries: on a 429 the SDK sleeps for retry-after (9 s in the 2026-11-24 load test) before
    # trying again. The fallback chain already handles it: cool this model down, ask the next one.
    return ChatGroq(model=model, temperature=0, api_key=os.getenv("GROQ_API_KEY"), max_retries=0, timeout=20)


llm = _new_client(GROQ_MODEL)
_fallback_clients: dict = {}
_cooling: dict = {}  # model name -> monotonic time before which it is skipped (it returned 429)


class ModelsUnavailable(RuntimeError):
    """No model in the chain could answer (all rate-limited, down or retired)."""


def _why_fall_back(exc: Exception) -> Optional[str]:
    """The reason to try the next model, or None if this error isn't about the model's availability."""
    if isinstance(exc, RateLimitError):
        return "rate_limit"
    if isinstance(exc, (APITimeoutError, APIConnectionError)):
        return "unreachable"
    if isinstance(exc, InternalServerError) or (isinstance(exc, APIStatusError) and exc.status_code >= 500):
        return "server_error"
    if isinstance(exc, NotFoundError) and "model" in str(exc).lower():
        return "model_retired"
    return None


def _cooldown_seconds(exc: Exception) -> float:
    """How long to skip a model that returned 429: 10 minutes for a daily cap, else its retry-after."""
    text = str(exc).lower()
    if "per day" in text or "tpd" in text or "rpd" in text:
        return 600.0
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        return min(float(headers.get("retry-after", 30)), 600.0)
    except (TypeError, ValueError):
        return 30.0


def _chain() -> list:
    """The clients to try, in order. Evals pin one model (a cassette mode, or LLM_FALLBACK=off)."""
    if not config.LLM_FALLBACK or cassette_mode():
        return [llm]
    clients = [llm]
    for model in config.GROQ_FALLBACK_MODELS:
        if model != llm.model_name:
            if model not in _fallback_clients:
                _fallback_clients[model] = _new_client(model)
            clients.append(_fallback_clients[model])
    now = time.monotonic()
    ready = [c for c in clients if _cooling.get(c.model_name, 0) <= now]
    return ready or clients[-1:]  # everything is cooling down: still try the last one


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


def _invoke(agent: str, node: str, messages: list, schema=None, tools=None):
    """One real model call, down the fallback chain. Returns (result, token usage)."""
    chain = _chain()
    last_error = None
    for i, client in enumerate(chain):
        try:
            return _invoke_one(client, agent, node, messages, schema, tools)
        except AuthenticationError as exc:
            # The key itself is refused (revoked or mistyped). Every model shares it, so don't walk the
            # chain: answer with the busy reply instead of an error page, and say why in the log.
            logger.error(f"request_id={get_request_id()} | LLM_KEY_REJECTED | {agent}.{node} | check GROQ_API_KEY")
            llm_unavailable_total.inc()
            raise ModelsUnavailable(f"the Groq key was rejected ({agent}.{node})") from exc
        except Exception as exc:
            reason = _why_fall_back(exc)
            if reason is None:
                raise
            last_error = exc
            if reason == "rate_limit":
                _cooling[client.model_name] = time.monotonic() + _cooldown_seconds(exc)
            elif reason == "model_retired":  # it won't come back: don't spend a round trip on it each call
                _cooling[client.model_name] = time.monotonic() + 3600
            following = chain[i + 1].model_name if i + 1 < len(chain) else None
            logger.warning(
                f"request_id={get_request_id()} | LLM_FALLBACK | {agent}.{node} | {client.model_name} failed"
                f" ({reason}: {type(exc).__name__}) | next={following}"
            )
            if following:
                llm_fallback_total.labels(from_model=client.model_name, to_model=following, reason=reason).inc()
    llm_unavailable_total.inc()
    raise ModelsUnavailable(f"no model could answer {agent}.{node}") from last_error


def _invoke_one(client, agent: str, node: str, messages: list, schema=None, tools=None):
    run_config = {"metadata": {"agent": agent, "node": node, "model": client.model_name}}
    start = time.perf_counter()
    if tools:
        try:
            message = client.bind_tools(tools).invoke(messages, config=run_config)
        except BadRequestError as exc:  # a malformed tool call: answer without tools instead of failing
            if "tool_use_failed" not in str(exc) and "output_parse_failed" not in str(exc):
                raise
            logger.error(f"request_id={get_request_id()} | {agent}.{node} bad tool call | {type(exc).__name__}")
            return AIMessage(content=""), {}
        usage = _record(agent, node, message, time.perf_counter() - start)
        return AIMessage(content=message.content or "", tool_calls=message.tool_calls or []), usage
    if schema is None:
        message = client.invoke(messages, config=run_config)
        usage = _record(agent, node, message, time.perf_counter() - start)
        return (message.content or "").strip(), usage

    structured = client.with_structured_output(schema, include_raw=True)
    for attempt in (1, 2):
        try:
            out = structured.invoke(messages, config=run_config)
            break
        except BadRequestError as exc:
            # Groq checks tool-call arguments against the schema and rejects malformed calls
            # (code tool_use_failed), or answers in prose (output_parse_failed). Retry once, then let
            # the caller fall back.
            if "tool_use_failed" not in str(exc) and "output_parse_failed" not in str(exc):
                raise
            logger.error(f"request_id={get_request_id()} | {agent}.{node} tool_use_failed (attempt {attempt})")
            if attempt == 2:
                return None, {}
    usage = _record(agent, node, out.get("raw"), time.perf_counter() - start)
    parsed = out.get("parsed")
    if out.get("parsing_error"):
        parsed = _salvage(schema, out.get("raw"))
        level = logger.warning if parsed is not None else logger.error
        level(
            f"request_id={get_request_id()} | {agent}.{node} parse error | {out['parsing_error']}"
            f" | salvaged={parsed is not None}"
        )
    return parsed, usage


def _salvage(schema, raw):
    """gpt-oss sometimes names its tool call 'functions.RouteDecision' (its own namespace), and the
    parser rejects the name. Seen on 18% of router calls on 2026-11-24, never before. If the call's
    name minus that prefix is the schema's, validate its arguments; anything else stays a failure."""
    for call in getattr(raw, "tool_calls", None) or []:
        if str(call.get("name", "")).rsplit(".", 1)[-1] == schema.__name__:
            try:
                return schema.model_validate(call.get("args") or {})
            except ValueError:  # pydantic's ValidationError is a ValueError
                return None
    return None


def call_llm(agent: str, node: str, messages: list, schema=None, tools=None):
    """Invoke the model once.

    With `schema` (a Pydantic model) the reply is parsed through tool calling and the parsed
    object is returned, or None if the model returned nothing usable. With `tools`, the model may
    call them: an AIMessage comes back (its tool_calls run in a ToolNode). Otherwise, the reply text.
    """
    mode = cassette_mode()
    if mode == "replay":
        return _replay(messages, schema, tools)
    if mode == "fill":
        try:
            return _replay(messages, schema, tools)
        except CassetteMiss:
            pass
    key = None if mode else cassette_key(messages, schema, tools)
    if key is not None:
        cached = _cache_get(key)
        if cached is not None:
            llm_cache_hits_total.inc()
            logger.info(f"request_id={get_request_id()} | LLM_CACHE_HIT | agent={agent} | node={node}")
            return cached
    result, usage = _invoke(agent, node, messages, schema, tools)
    if mode in ("record", "fill"):
        _store(agent, node, messages, schema, result, usage, tools)
    if key is not None and result is not None:
        _cache_put(key, result)
    return result


# ── Answer cache ───────────────────────────────────────────────────────────────
# temperature=0, so the same call gets the same answer: a demo question asked again costs nothing.
# The key holds the whole prompt (including any order details), so it only matches the same input.
_CACHE_MAX = 512
_cache: OrderedDict = OrderedDict()
_cache_lock = threading.Lock()


def _cache_get(key: str):
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        stored, value = entry
        if time.monotonic() - stored > config.LLM_CACHE_SECONDS:
            del _cache[key]
            return None
        _cache.move_to_end(key)
        return value


def _cache_put(key: str, value) -> None:
    if config.LLM_CACHE_SECONDS <= 0:
        return
    with _cache_lock:
        _cache[key] = (time.monotonic(), value)
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# ── Record / replay ────────────────────────────────────────────────────────────
# LLM_CASSETTE_MODE=record|replay|fill and LLM_CASSETTE_PATH=<json file>. Record calls the model and
# saves each answer under a hash of (model, messages, schema). Replay never calls the network and
# raises CassetteMiss for a call it has no answer for, so a changed prompt can't pass silently.
# Fill replays what it has and records only the missing calls (a search change that alters only
# the ranker's input then costs only the ranker calls).


class CassetteMiss(RuntimeError):
    """Replay mode has no recorded answer for this exact call."""


_cassette: Optional[dict] = None
_cassette_file: Optional[Path] = None


def cassette_mode() -> str:
    mode = os.getenv("LLM_CASSETTE_MODE", "").strip().lower()
    if mode not in ("", "record", "replay", "fill"):
        raise ValueError(f"LLM_CASSETTE_MODE must be record, replay or fill, not {mode!r}")
    return mode


def _cassette_data() -> dict:
    global _cassette, _cassette_file
    path = Path(os.getenv("LLM_CASSETTE_PATH", "llm_cassette.json"))
    if _cassette is None or path != _cassette_file:
        _cassette_file = path
        _cassette = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return _cassette


def _message_key(m) -> list:
    entry = [getattr(m, "type", type(m).__name__), getattr(m, "content", str(m))]
    calls = getattr(m, "tool_calls", None)
    if calls:  # an assistant turn that called tools: which tools, with what arguments
        entry.append([[c.get("name"), c.get("args")] for c in calls])
    return entry


def cassette_key(messages: list, schema=None, tools=None) -> str:
    payload = {
        "model": llm.model_name,
        "messages": [_message_key(m) for m in messages],
        "schema": None if schema is None else [schema.__name__, schema.model_json_schema()],
    }
    if tools:  # absent for plain and structured calls, so their recorded keys don't change
        payload["tools"] = sorted(getattr(t, "name", str(t)) for t in tools)
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _store(agent: str, node: str, messages: list, schema, result, usage: dict, tools=None) -> None:
    if tools and isinstance(result, AIMessage):
        value = {"content": result.content, "tool_calls": result.tool_calls}
    elif schema is not None and result is not None and hasattr(result, "model_dump"):
        value = result.model_dump(mode="json")
    else:
        value = result
    data = _cassette_data()
    data[cassette_key(messages, schema, tools)] = {
        "agent": agent,
        "node": node,
        "model": llm.model_name,
        "message": str(getattr(messages[-1], "content", ""))[:200] if messages else "",
        "value": value,
        "total_tokens": usage.get("total_tokens", 0),
    }
    _write_json(_cassette_file, data)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    for attempt in range(20):  # OneDrive briefly locks a file it is syncing (WinError 5)
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.5)


# Query embeddings are model outputs too. Under a cassette mode they are recorded and replayed like
# the answers, so a replay doesn't depend on the CPU's floating-point details: GitHub's runners
# differ from the machine that recorded, and on 2026-11-24 that swapped near-tied search results and
# changed a ranker prompt. VECTOR_CASSETTE_RECORD=1 adds missing vectors during a replay (0 tokens).
VECTOR_CASSETTE = Path(__file__).resolve().parents[2] / "eval" / "cassettes" / "query_vectors.json"
_vectors: Optional[dict] = None
_vectors_lock = threading.Lock()


def recorded_vector(query: str, compute):
    """The query's embedding (pgvector text): computed live, or recorded and replayed in cassette modes."""
    mode = cassette_mode()
    if not mode:
        return compute()
    global _vectors
    path = Path(os.getenv("VECTOR_CASSETTE_PATH") or VECTOR_CASSETTE)
    with _vectors_lock:
        if _vectors is None:
            _vectors = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if query in _vectors:
            return _vectors[query]
    if mode == "replay" and os.getenv("VECTOR_CASSETTE_RECORD") != "1":
        raise CassetteMiss(f"no recorded vector for {query[:60]!r} in {path}; record it again")
    value = compute()
    with _vectors_lock:
        _vectors[query] = value
        _write_json(path, _vectors)
    return value


def _replay(messages: list, schema=None, tools=None):
    entry = _cassette_data().get(cassette_key(messages, schema, tools))
    if entry is None:
        kind = schema.__name__ if schema is not None else "text"
        raise CassetteMiss(f"no recorded answer for this {kind} call in {_cassette_file}; record it again")
    value = entry["value"]
    if tools:
        return AIMessage(content=value.get("content") or "", tool_calls=value.get("tool_calls") or [])
    if schema is None or value is None:
        return value
    return schema.model_validate(value)
