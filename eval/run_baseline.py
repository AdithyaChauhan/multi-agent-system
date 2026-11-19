#!/usr/bin/env python3
"""
Replay eval/baseline_conversations.json through the real app and check plain assertions.

Each turn goes through FastAPI's /chat endpoint in-process (TestClient), so the
real router graph, agents, database and Groq model are used. Nothing is mocked.

Per turn it records: pass/fail, the failed assertions, LLM calls, tokens and
wall-clock seconds. Turns are paced to stay under Groq's tokens-per-minute
limit, and the pacing wait is NOT counted in the per-turn time.

Usage (from the repo root, with the docker-compose `db` and `mock-carrier-api`
services running and the restored baseline database):

    python eval/run_baseline.py --label before --runs 3
    python eval/run_baseline.py --label step1 --only p01,p02 --runs 1
    python eval/run_baseline.py --label step2 --mode replay      # 0 tokens: reuse recorded answers

Modes: `record` (default) calls Groq and saves every answer in eval/cassettes/baseline_<model>.json;
`replay` answers from that file and counts any call it has no answer for (a changed prompt);
`live` calls Groq without saving. Record and replay use per-conversation ticket ids, so a reply
that quotes a ticket id is the same in both.

Environment:
    BASELINE_DATABASE_URL  default postgresql://postgres:mypassword@localhost:5433/multi_agent_baseline
    MOCK_CARRIER_API_URL   default http://localhost:9000
    GROQ_API_KEY           read from the environment / .env (never printed)

Results are written to eval/baseline_runs/<label>_run<N>.json and a summary
to eval/baseline_runs/<label>_summary.json.
"""

import argparse
import hashlib
import json
import logging
import math
import os
import re
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONVERSATIONS_FILE = REPO / "eval" / "baseline_conversations.json"
OUT_DIR = REPO / "eval" / "baseline_runs"
CASSETTE_DIR = REPO / "eval" / "cassettes"
DEFAULT_DB = "postgresql://postgres:mypassword@localhost:5433/multi_agent_baseline"

# Orders the support/order conversations rely on. Reset before every signed-in conversation
# so earlier conversations (a confirmed cancel, a new ticket) cannot change later results.
FIXTURE_ORDERS = [
    ("ORD-2001", "demo-user-1", "boAt Rockerz 255 Pro+", "delivered", "BlueDart", "TRK-2001"),
    ("ORD-2002", "demo-user-1", "Mi 108cm Full HD Android LED TV", "shipped", "FakeExpress", "TRK-2002"),
    ("ORD-2003", "demo-user-1", "Fire-Boltt Phoenix Smartwatch", "shipped", "DTDC", "TRK-2003"),
    ("ORD-2004", "demo-user-1", "Croma 500W Mixer Grinder", "delivered", "BlueDart", "TRK-2004"),
    ("ORD-2005", "demo-user-1", "Logitech M221 Wireless Mouse", "processing", None, None),
    ("ORD-9901", "test-user-99", "iPhone 15 Pro Max", "shipped", "FakeExpress", "TRK-9901"),
]
FIXTURE_USERS = ["demo-user-1", "test-user-99"]

ERROR_PATTERNS = [
    r"something went wrong",
    r"traceback",
    r"internal server error",
    r"could not rank",
    r"\berror\b",
]


# ── Environment (must happen before any app import) ────────────────────────────


def configure_environment(args) -> None:
    os.chdir(REPO)  # the app mounts app/static relative to the working directory
    sys.path.insert(0, str(REPO))
    if args.env_file:
        # Read keys into this process's environment only (used when running from a worktree).
        from dotenv import load_dotenv

        load_dotenv(args.env_file, override=False)
    os.environ["DATABASE_URL"] = args.database_url
    if args.model:
        os.environ["GROQ_MODEL"] = args.model  # read by app.core.config at import
    os.environ.setdefault("MOCK_CARRIER_API_URL", "http://localhost:9000")
    if not args.trace:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        os.environ["LANGSMITH_TRACING"] = "false"
    os.environ.pop("CI", None)

    # Keep app logs out of the (OneDrive-synced) repo and off stdout.
    import app.core.logger as app_logger

    app_logger.LOG_FILE = str(Path(tempfile.gettempdir()) / f"multi_agent_baseline_app_{os.getpid()}.log")


def quiet_app_loggers() -> None:
    for name, obj in logging.root.manager.loggerDict.items():
        if name.startswith("app") and isinstance(obj, logging.Logger):
            for h in list(obj.handlers):
                if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                    obj.removeHandler(h)


# ── LLM metering and pacing ────────────────────────────────────────────────────


class Meter:
    """Counts every Groq chat call made by any agent (patched at ChatGroq._generate)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.calls = 0
        self.tokens = 0
        self.rate_limited = 0
        self.errors = 0
        self.sdk_retries = 0
        # Groq's tokens-per-minute limit behaves like a token bucket that refills continuously.
        self.bucket_capacity = 7600.0
        self.bucket = 0.0  # start empty: earlier processes may have used the quota
        self.bucket_ts = time.time()

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "calls": self.calls,
                "tokens": self.tokens,
                "rate_limited": self.rate_limited,
                "errors": self.errors,
                "sdk_retries": self.sdk_retries,
            }

    def _refill(self) -> None:
        now = time.time()
        self.bucket = min(self.bucket_capacity, self.bucket + (now - self.bucket_ts) * self.bucket_capacity / 60.0)
        self.bucket_ts = now

    def record(self, tokens: int) -> None:
        with self.lock:
            self.calls += 1
            self.tokens += tokens
            self._refill()
            self.bucket -= tokens

    def available(self) -> float:
        with self.lock:
            self._refill()
            return self.bucket


METER = Meter()


class _RetryCounter(logging.Handler):
    def emit(self, record):
        if "Retrying" in record.getMessage():
            with METER.lock:
                METER.sdk_retries += 1


def install_meter() -> None:
    import groq
    from langchain_groq import ChatGroq

    original = ChatGroq._generate

    def metered(self, messages, stop=None, run_manager=None, **kwargs):
        if str(self.model_name).startswith("openai/gpt-oss"):
            kwargs.setdefault("reasoning_effort", "low")  # same setting for before and after runs
        try:
            result = original(self, messages, stop=stop, run_manager=run_manager, **kwargs)
        except groq.RateLimitError:
            with METER.lock:
                METER.calls += 1
                METER.rate_limited += 1
            raise
        except Exception:
            with METER.lock:
                METER.calls += 1
                METER.errors += 1
            raise
        usage = (result.llm_output or {}).get("token_usage") or {}
        METER.record(int(usage.get("total_tokens") or 0))
        return result

    ChatGroq._generate = metered

    groq_logger = logging.getLogger("groq._base_client")
    groq_logger.setLevel(logging.INFO)
    groq_logger.addHandler(_RetryCounter())
    groq_logger.propagate = False


def pace(tpm_budget: int, estimate: int) -> float:
    """Sleep until the token bucket has room for one more turn (so no call waits on a 429)."""
    METER.bucket_capacity = float(tpm_budget)
    waited = 0.0
    while METER.available() < estimate:
        delay = max(0.5, (estimate - METER.available()) * 60.0 / tpm_budget)
        time.sleep(delay)
        waited += delay
    return waited


# ── Record / replay ────────────────────────────────────────────────────────────


def cassette_for(model: str) -> Path:
    return CASSETTE_DIR / f"baseline_{re.sub(r'[^a-z0-9]+', '-', model.lower()).strip('-')}.json"


class TicketIds:
    """Stands in for `uuid` in support_tools: ticket ids that depend only on the conversation."""

    def __init__(self):
        self.conversation = ""
        self.count = 0

    def start(self, conversation_id: str) -> None:
        self.conversation, self.count = conversation_id, 0

    def uuid4(self):
        self.count += 1
        return uuid.UUID(hashlib.md5(f"{self.conversation}-{self.count}".encode()).hexdigest())


TICKET_IDS = TicketIds()
MISSES = {"count": 0}


def install_cassette(mode: str, path: Path) -> None:
    os.environ["LLM_CASSETTE_MODE"] = "" if mode == "live" else mode
    os.environ["LLM_CASSETTE_PATH"] = str(path)
    if mode == "live":
        return
    import app.core.llm as llm
    import app.tools.support_tools as support_tools

    support_tools.uuid = TICKET_IDS
    original = llm._replay

    def counted(messages, schema=None):
        try:
            return original(messages, schema)
        except llm.CassetteMiss:
            MISSES["count"] += 1
            raise

    llm._replay = counted


# ── App wiring ─────────────────────────────────────────────────────────────────


class GraphRecorder:
    """Wraps a compiled graph so the final state of each invoke can be inspected."""

    def __init__(self, graph):
        self._graph = graph
        self.last = None
        self.invocations = 0

    def invoke(self, *args, **kwargs):
        result = self._graph.invoke(*args, **kwargs)
        self.last = result
        self.invocations += 1
        return result

    def __getattr__(self, name):
        return getattr(self._graph, name)


def load_app():
    import app.main as app_main

    router_rec = GraphRecorder(app_main.router_graph)
    app_main.router_graph = router_rec
    reroute_rec = None
    if hasattr(app_main, "order_agent_graph"):
        reroute_rec = GraphRecorder(app_main.order_agent_graph)
        app_main.order_agent_graph = reroute_rec
    quiet_app_loggers()
    return app_main, router_rec, reroute_rec


# ── Database fixtures and probes ───────────────────────────────────────────────


def reset_fixtures() -> None:
    from sqlalchemy import text
    from app.db.database import engine

    with engine.begin() as conn:
        for user_id in FIXTURE_USERS:
            conn.execute(
                text("INSERT INTO users (user_id) VALUES (:u) ON CONFLICT (user_id) DO NOTHING"),
                {"u": user_id},
            )
        for order_id, user_id, product, status, carrier, tracking in FIXTURE_ORDERS:
            exists = conn.execute(text("SELECT 1 FROM orders WHERE order_id = :o"), {"o": order_id}).first()
            params = {"o": order_id, "u": user_id, "p": product, "s": status, "c": carrier, "t": tracking}
            if exists:
                conn.execute(
                    text(
                        "UPDATE orders SET user_id=:u, product_name=:p, status=:s, carrier=:c, tracking_id=:t "
                        "WHERE order_id=:o"
                    ),
                    params,
                )
            else:
                conn.execute(
                    text(
                        "INSERT INTO orders (order_id, user_id, product_name, status, carrier, tracking_id) "
                        "VALUES (:o, :u, :p, :s, :c, :t)"
                    ),
                    params,
                )
        conn.execute(
            text("DELETE FROM support_tickets WHERE user_id = ANY(:users)"),
            {"users": FIXTURE_USERS},
        )


def ticket_count(user_id: str) -> int:
    from sqlalchemy import text
    from app.db.database import engine

    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM support_tickets WHERE user_id = :u"), {"u": user_id}).scalar()


def order_status(order_id: str):
    from sqlalchemy import text
    from app.db.database import engine

    with engine.connect() as conn:
        row = conn.execute(text("SELECT status FROM orders WHERE order_id = :o"), {"o": order_id}).first()
        return row[0] if row else None


# ── Assertions ─────────────────────────────────────────────────────────────────


def _norm(s) -> str:
    return (str(s) if s is not None else "").replace("’", "'").lower()


def _alnum(s) -> str:
    return re.sub(r"[^a-z0-9]", "", _norm(s))


# Expected products are written as shopper words ("air fryer", "monitor"). A word the catalog knows
# is compared by product type (and kind, when both sides name one); any other word must appear in
# the text, so a product the catalog has no type for (one Acer monitor) can still be checked.


def _resolve(word):
    from app.catalog.runtime import get_catalog

    return get_catalog().resolve_product(word)


def same_product(got, expected: str) -> bool:
    """Did the search preferences name the expected product?"""
    if not got:
        return False
    want_type, want_kind = _resolve(expected)
    if want_type is None:
        return _norm(expected) in _norm(got)
    got_type, got_kind = _resolve(got)
    if got_type is None or got_type.name != want_type.name:
        return False
    return not (want_kind and got_kind) or want_kind == got_kind


def shows_product(product: dict, expected: str) -> bool:
    """Is a shown product the expected kind of thing?"""
    want_type, want_kind = _resolve(expected)
    if want_type is None:
        return _norm(expected) in _norm(product.get("name"))
    if product.get("type") != want_type.name:
        return False
    return not want_kind or (product.get("attributes") or {}).get("kind") == want_kind


def has_product_listing(text: str) -> bool:
    return "₹" in text and bool(re.search(r"(?m)^\s*1\.\s+\S", text))


def derive_route(state, user_id: str) -> str:
    if state is None:
        return "safety"  # main.py answered before invoking the graph
    if state.get("route"):
        return state["route"]
    intent = state.get("intent")
    confidence = state.get("confidence")
    confidence = 1.0 if confidence is None else confidence  # a router without a confidence score
    if intent not in ("order", "product", "support") or confidence < 0.7:
        return "clarify"
    if user_id.startswith("anon-") and intent in ("order", "support"):
        return "sign_in"
    return intent


def _phrases(spec, phrase_sets):
    if isinstance(spec, str) and spec.startswith("$"):
        return phrase_sets[spec[1:]]
    if isinstance(spec, str):
        return [spec]
    return list(spec)


def check_turn(expect: dict, *, text, status_code, state, route, api_json, user_id, tickets_delta, phrase_sets):
    failures = []
    t = _norm(text)

    if status_code != 200:
        failures.append(f"http {status_code}")
    for pat in ERROR_PATTERNS:
        if re.search(pat, t):
            failures.append(f"error text /{pat}/")

    if "route" in expect:
        allowed = expect["route"] if isinstance(expect["route"], list) else [expect["route"]]
        if route not in allowed:
            failures.append(f"route {route!r} not in {allowed}")

    prefs = {}
    if state:
        prefs = state.get("preferences") or {}

    if "product" in expect:
        allowed = expect["product"] if isinstance(expect["product"], list) else [expect["product"]]
        if not any(same_product(prefs.get("product"), a) for a in allowed):
            failures.append(f"product {prefs.get('product')!r} is not {allowed}")
    if "brand" in expect:
        got, want = _alnum(prefs.get("brand")), _alnum(expect["brand"])
        if not got or not (want in got or got in want):
            failures.append(f"brand {prefs.get('brand')!r} != {expect['brand']!r}")
    if "max_price" in expect:
        got, want = prefs.get("max_price"), expect["max_price"]
        if isinstance(want, dict):
            ok = got is not None and (
                ("lt" not in want or got < want["lt"]) and ("lte" not in want or got <= want["lte"])
            )
        else:
            ok = got == want
        if not ok:
            failures.append(f"max_price {got!r} !~ {want!r}")
    if "min_rating" in expect:
        got = prefs.get("min_rating")
        if got is None or abs(float(got) - float(expect["min_rating"])) > 0.01:
            failures.append(f"min_rating {got!r} != {expect['min_rating']!r}")

    shown = ((state or {}).get("ranked_products") or [])[:3]
    if expect.get("results"):
        if not has_product_listing(text):
            failures.append("no product listing in reply")
        if not shown:
            failures.append("ranked_products empty")
    if expect.get("no_results") and has_product_listing(text):
        failures.append("reply lists products but none were expected")
    if "result_product" in expect and shown:
        allowed = expect["result_product"]
        hits = sum(1 for p in shown if any(shows_product(p, a) for a in allowed))
        if hits < math.ceil(len(shown) / 2):
            got = [f"{p.get('type')}/{(p.get('attributes') or {}).get('kind')}" for p in shown]
            failures.append(f"shown products {got} mostly not {allowed}")
    if "result_brand" in expect and shown:
        want = _alnum(expect["result_brand"])
        bad = [
            p.get("brand") for p in shown if want not in _alnum(p.get("brand")) and _alnum(p.get("brand")) not in want
        ]
        if bad:
            failures.append(f"shown brands {bad} != {expect['result_brand']!r}")

    for phrase in expect.get("contains", []):
        options = _phrases(phrase, phrase_sets)
        if not any(_norm(o) in t for o in options):
            failures.append(f"missing {options if len(options) > 1 else options[0]!r}")
    if "contains_any" in expect:
        options = _phrases(expect["contains_any"], phrase_sets)
        if not any(_norm(o) in t for o in options):
            failures.append(f"none of {options}")
    for phrase in expect.get("not_contains", []):
        if _norm(phrase) in t:
            failures.append(f"forbidden {phrase!r}")

    if "order_id" in expect:
        want = expect["order_id"].upper()
        st = state or {}
        ids = {
            str(st.get("order_id") or "").upper(),
            str((st.get("order_data") or {}).get("order_id") or "").upper(),
            str((st.get("support_order") or {}).get("order_id") or "").upper(),
        }
        if want not in ids and want.lower() not in t:
            failures.append(f"order {want} not resolved")

    if "action" in expect:
        action = (api_json or {}).get("action")
        got = action.get("type") if isinstance(action, dict) else None
        if got != expect["action"]:
            failures.append(f"action {got!r} != {expect['action']!r}")

    if "ticket_created" in expect:
        if expect["ticket_created"] and tickets_delta < 1:
            failures.append("no ticket created")
        if not expect["ticket_created"] and tickets_delta > 0:
            failures.append(f"{tickets_delta} unexpected ticket(s)")

    for order_id, want in (expect.get("db") or {}).items():
        got = order_status(order_id)
        if got != want:
            failures.append(f"db {order_id} status {got!r} != {want!r}")

    return failures


# ── Runner ─────────────────────────────────────────────────────────────────────


def run_conversation(client, conv, router_rec, reroute_rec, phrase_sets, args):
    user_base = conv["user"]
    user_id = f"anon-baseline-{conv['id']}" if user_base == "anon" else user_base
    signed_in = not user_id.startswith("anon-")
    if signed_in:
        reset_fixtures()
    TICKET_IDS.start(conv["id"])

    turns_out = []
    session_id = None
    for turn in conv["turns"]:
        if turn.get("new_session"):
            session_id = None
            user_id = f"{user_id}-2" if not signed_in else user_id
        estimate = 0 if args.mode == "replay" else args.turn_token_estimate
        paced = pace(args.tpm_budget, estimate)

        router_rec.last = None
        if reroute_rec is not None:
            reroute_rec.last = None
        before = METER.snapshot()
        tickets_before = ticket_count(user_id) if signed_in else 0

        payload = {"message": turn["message"]}
        if session_id:
            payload["session_id"] = session_id
        t0 = time.perf_counter()
        resp = client.post("/chat", json=payload, headers={"X-User-ID": user_id})
        seconds = time.perf_counter() - t0
        after = METER.snapshot()

        try:
            api_json = resp.json()
        except ValueError:
            api_json = {}
        text = api_json.get("response") or api_json.get("detail") or ""
        session_id = api_json.get("session_id") or session_id
        state = router_rec.last
        route = derive_route(state, user_id)
        tickets_delta = (ticket_count(user_id) - tickets_before) if signed_in else 0

        failures = check_turn(
            turn.get("expect", {}),
            text=text,
            status_code=resp.status_code,
            state=state,
            route=route,
            api_json=api_json,
            user_id=user_id,
            tickets_delta=tickets_delta,
            phrase_sets=phrase_sets,
        )

        # UI "Yes, cancel" button → POST /cancel-order (only after the assistant asked).
        if "confirm_cancel" in turn:
            spec = turn["confirm_cancel"]
            r = client.post(
                "/cancel-order",
                json={"order_id": spec["order_id"], "session_id": session_id or ""},
                headers={"X-User-ID": user_id},
            )
            ok = r.status_code == 200 and r.json().get("success") is True
            if ok != spec["expect_success"]:
                failures.append(f"confirm cancel success={ok} != {spec['expect_success']}")
            if order_status(spec["order_id"]) != spec["db_after"]:
                failures.append(f"after confirm {spec['order_id']} is {order_status(spec['order_id'])!r}")
        if "cancel_endpoint" in turn:
            spec = turn["cancel_endpoint"]
            r = client.post(
                "/cancel-order",
                json={"order_id": spec["order_id"], "session_id": session_id or ""},
                headers={"X-User-ID": user_id},
            )
            ok = r.status_code == 200 and r.json().get("success") is True
            if ok != spec["expect_success"]:
                failures.append(f"direct cancel success={ok} != {spec['expect_success']}")
            if order_status(spec["order_id"]) != spec["db_after"]:
                failures.append(f"after direct cancel {spec['order_id']} is {order_status(spec['order_id'])!r}")

        prefs = (state or {}).get("preferences") or {}
        turns_out.append(
            {
                "message": turn["message"],
                "route": route,
                "rerouted_to_order": bool((state or {}).get("reroute_to_order")),
                "passed": not failures,
                "failures": failures,
                "llm_calls": after["calls"] - before["calls"],
                "tokens": after["tokens"] - before["tokens"],
                "rate_limited": after["rate_limited"] - before["rate_limited"],
                "sdk_retries": after["sdk_retries"] - before["sdk_retries"],
                "seconds": round(seconds, 3),
                "paced_wait_seconds": round(paced, 1),
                "extracted": {
                    k: prefs.get(k)
                    for k in ("category", "subcategory", "type", "brand", "max_price", "min_rating", "keywords")
                    if prefs
                },
                "shown": [
                    {"name": (p.get("name") or "")[:60], "brand": p.get("brand"), "subcategory": p.get("subcategory")}
                    for p in ((state or {}).get("ranked_products") or [])[:3]
                ],
                "response": text[:700],
            }
        )
    infra = any(t["rate_limited"] for t in turns_out)
    return {
        "id": conv["id"],
        "tags": conv.get("tags", []),
        "passed": all(t["passed"] for t in turns_out),
        "infra_error": infra,
        "turns": turns_out,
    }


def summarize(results: list) -> dict:
    turns = [t for c in results for t in c["turns"]]
    secs = [t["seconds"] for t in turns]
    by_route = {}
    for t in turns:
        r = by_route.setdefault(t["route"], {"turns": 0, "llm_calls": 0, "seconds": 0.0, "tokens": 0})
        r["turns"] += 1
        r["llm_calls"] += t["llm_calls"]
        r["seconds"] += t["seconds"]
        r["tokens"] += t["tokens"]
    for r in by_route.values():
        r["llm_calls_per_turn"] = round(r["llm_calls"] / r["turns"], 2)
        r["seconds_per_turn"] = round(r["seconds"] / r["turns"], 2)
        r["tokens_per_turn"] = round(r["tokens"] / r["turns"])
        r["seconds"] = round(r["seconds"], 1)
    return {
        "conversations": len(results),
        "conversations_passed": sum(1 for c in results if c["passed"]),
        "turns": len(turns),
        "turns_passed": sum(1 for t in turns if t["passed"]),
        "llm_calls": sum(t["llm_calls"] for t in turns),
        "llm_calls_per_turn": round(sum(t["llm_calls"] for t in turns) / max(1, len(turns)), 2),
        "tokens": sum(t["tokens"] for t in turns),
        "tokens_per_turn": round(sum(t["tokens"] for t in turns) / max(1, len(turns))),
        "seconds_per_turn_mean": round(statistics.mean(secs), 2) if secs else None,
        "seconds_per_turn_median": round(statistics.median(secs), 2) if secs else None,
        "rate_limited_calls": sum(t["rate_limited"] for t in turns),
        "sdk_retries": sum(t["sdk_retries"] for t in turns),
        "infra_error_conversations": [c["id"] for c in results if c["infra_error"]],
        "failed_conversations": [c["id"] for c in results if not c["passed"]],
        "by_route": by_route,
    }


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, text=True).strip()
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True, help="name for this measurement, e.g. before / after / step2")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--only", default="", help="comma-separated conversation ids")
    parser.add_argument("--tags", default="", help="comma-separated tags; keep conversations having any of them")
    parser.add_argument("--database-url", default=os.getenv("BASELINE_DATABASE_URL", DEFAULT_DB))
    parser.add_argument("--tpm-budget", type=int, default=7600, help="Groq tokens/minute to stay under")
    parser.add_argument("--turn-token-estimate", type=int, default=4000)
    parser.add_argument("--max-calls", type=int, default=0, help="abort a run after this many LLM calls (0 = no cap)")
    parser.add_argument("--trace", action="store_true", help="keep LangSmith tracing enabled")
    parser.add_argument("--env-file", default="", help="load environment variables from this .env file")
    parser.add_argument("--model", default="", help="Groq model for this measurement (default: the app's GROQ_MODEL)")
    parser.add_argument("--exclude", default="", help="comma-separated conversation ids to skip")
    parser.add_argument("--mode", choices=["record", "replay", "live"], default="record")
    parser.add_argument("--cassette", default="", help="cassette file (default eval/cassettes/baseline_<model>.json)")
    args = parser.parse_args()

    configure_environment(args)
    install_meter()
    from app.core.config import GROQ_MODEL as model

    cassette = Path(args.cassette) if args.cassette else cassette_for(model)
    install_cassette(args.mode, cassette)
    app_main, router_rec, reroute_rec = load_app()
    from fastapi.testclient import TestClient

    data = json.loads(CONVERSATIONS_FILE.read_text(encoding="utf-8"))
    phrase_sets = data.get("phrase_sets", {})
    convs = data["conversations"]
    if args.only:
        wanted = {c.strip() for c in args.only.split(",") if c.strip()}
        convs = [c for c in convs if c["id"] in wanted]
    if args.tags:
        tags = {t.strip() for t in args.tags.split(",") if t.strip()}
        convs = [c for c in convs if tags & set(c.get("tags", []))]
    if args.exclude:
        skip = {c.strip() for c in args.exclude.split(",") if c.strip()}
        convs = [c for c in convs if c["id"] not in skip]
    from app.core.config import GROQ_MODEL

    print(f"model={GROQ_MODEL} mode={args.mode} conversations={len(convs)}", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_summaries = []
    with TestClient(app_main.app) as client:
        for run_idx in range(1, args.runs + 1):
            started = datetime.now(timezone.utc).isoformat(timespec="seconds")
            results = []
            calls_at_start = METER.snapshot()["calls"]
            for conv in convs:
                outcome = run_conversation(client, conv, router_rec, reroute_rec, phrase_sets, args)
                if outcome["infra_error"]:
                    print(f"  [{conv['id']}] rate-limited by Groq — cooling down 65 s and retrying once", flush=True)
                    time.sleep(65)
                    outcome = run_conversation(client, conv, router_rec, reroute_rec, phrase_sets, args)
                    outcome["retried_after_rate_limit"] = True
                    if outcome["infra_error"]:
                        print("  still rate-limited after a retry (daily quota?) — stopping this run", flush=True)
                        break
                results.append(outcome)
                mark = "PASS" if outcome["passed"] else "FAIL"
                calls = sum(t["llm_calls"] for t in outcome["turns"])
                secs = sum(t["seconds"] for t in outcome["turns"])
                print(f"  run {run_idx} {conv['id']:<4} {mark}  calls={calls:<2} {secs:6.1f}s", flush=True)
                for t in outcome["turns"]:
                    if t["failures"]:
                        print(f"        - {t['message']!r}: {'; '.join(t['failures'])}", flush=True)
                if args.max_calls and METER.snapshot()["calls"] - calls_at_start > args.max_calls:
                    print("  aborting run: --max-calls reached", flush=True)
                    break
            summary = summarize(results)
            payload = {
                "label": args.label,
                "run": run_idx,
                "model": GROQ_MODEL,
                "mode": args.mode,
                "git_sha": git_sha(),
                "started_at": started,
                "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "summary": summary,
                "conversations": results,
            }
            out = OUT_DIR / f"{args.label}_run{run_idx}.json"
            out.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
            run_summaries.append(summary)
            print(
                f"run {run_idx}: {summary['conversations_passed']}/{summary['conversations']} conversations, "
                f"{summary['turns_passed']}/{summary['turns']} turns, "
                f"{summary['llm_calls_per_turn']} LLM calls/turn, "
                f"{summary['seconds_per_turn_mean']} s/turn mean ({summary['seconds_per_turn_median']} median), "
                f"{summary['tokens_per_turn']} tokens/turn -> {out.relative_to(REPO)}",
                flush=True,
            )

    if run_summaries:
        n = len(run_summaries)
        agg = {
            "label": args.label,
            "model": GROQ_MODEL,
            "runs": n,
            "git_sha": git_sha(),
            "conversation_ids": [c["id"] for c in convs],
            "conversations_passed_per_run": [s["conversations_passed"] for s in run_summaries],
            "conversations_total": run_summaries[0]["conversations"],
            "pass_rate_mean": round(
                statistics.mean(s["conversations_passed"] / s["conversations"] for s in run_summaries), 4
            ),
            "turns_passed_per_run": [s["turns_passed"] for s in run_summaries],
            "turns_total": run_summaries[0]["turns"],
            "llm_calls_per_turn_mean": round(statistics.mean(s["llm_calls_per_turn"] for s in run_summaries), 2),
            "tokens_per_turn_mean": round(statistics.mean(s["tokens_per_turn"] for s in run_summaries)),
            "seconds_per_turn_mean": round(statistics.mean(s["seconds_per_turn_mean"] for s in run_summaries), 2),
            "seconds_per_turn_median_mean": round(
                statistics.mean(s["seconds_per_turn_median"] for s in run_summaries), 2
            ),
            "rate_limited_calls": sum(s["rate_limited_calls"] for s in run_summaries),
            "mode": args.mode,
            "cassette_misses": MISSES["count"],
            "failed_conversations_per_run": [s["failed_conversations"] for s in run_summaries],
        }
        (OUT_DIR / f"{args.label}_summary.json").write_text(json.dumps(agg, indent=1), encoding="utf-8")
        print(json.dumps(agg, indent=1))
    if MISSES["count"]:
        print(f"REPLAY INCOMPLETE: {MISSES['count']} model calls had no recorded answer (a prompt changed?)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
