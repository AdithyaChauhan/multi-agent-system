#!/usr/bin/env python3
"""Measure product search on the labelled queries in eval/product_queries.json (Phase 0).

Runs the product agent graph directly (no router, no HTTP) for each query, after first running the
query's history turns so follow-ups carry the same filters the app would, and scores what the
shopper would see. Metric definitions are in eval/retrieval_metrics.py.

    python eval/run_retrieval.py --label v1-gptoss20b --model openai/gpt-oss-20b
    python eval/run_retrieval.py --label v1-gptoss20b-replay --model openai/gpt-oss-20b --mode replay
    python eval/run_retrieval.py --label v1-renamed --model openai/gpt-oss-20b --mode replay \\
        --database-url postgresql://USER:PASSWORD@localhost:5433/multi_agent_renamed

Modes:
    record (default)  call Groq and save every answer to the cassette
    replay            answer from the cassette, never call Groq; a missing answer is an error
    live              call Groq without saving

Results go to eval/retrieval_runs/<label>.json. --resume skips queries already scored in that
file, so a run stopped by Groq's daily token cap can continue the next day. A full live run costs
roughly 200K tokens, about one model's daily free-tier quota.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from eval.retrieval_metrics import by_tag, summarize, score_query  # noqa: E402
from eval.run_baseline import (  # noqa: E402
    DEFAULT_DB,
    METER,
    configure_environment,
    install_meter,
    pace,
    quiet_app_loggers,
)

QUERIES_FILE = REPO / "eval" / "product_queries.json"
OUT_DIR = REPO / "eval" / "retrieval_runs"
CASSETTE_DIR = REPO / "eval" / "cassettes"


def cassette_for(model: str) -> Path:
    return CASSETTE_DIR / f"retrieval_{re.sub(r'[^a-z0-9]+', '-', model.lower()).strip('-')}.json"


def is_daily_cap(exc: Exception) -> bool:
    text = str(exc).lower()
    return type(exc).__name__ == "RateLimitError" and ("per day" in text or "tpd" in text or "rpd" in text)


def run_turn(graph, message: str, preferences, history: list) -> dict:
    return graph.invoke(
        {
            "user_message": message,
            "preferences": preferences,
            "conversation_history": history,
            "user_id": "eval-user",
            "session_id": "eval-session",
        }
    )


def run_query(graph, query: dict, args) -> dict:
    preferences, history = None, []
    before = METER.snapshot()
    for turn in query.get("history", []):
        if args.mode != "replay":
            pace(args.tpm_budget, args.turn_token_estimate)
        out = run_turn(graph, turn, preferences, history)
        preferences = out.get("preferences") or preferences  # main.py keeps the last non-empty filters
        history += [
            {"role": "user", "content": turn},
            {"role": "assistant", "content": out.get("final_response") or ""},
        ]
    if args.mode != "replay":
        pace(args.tpm_budget, args.turn_token_estimate)
    start = time.perf_counter()
    out = run_turn(graph, query["query"], preferences, history)
    seconds = time.perf_counter() - start
    after = METER.snapshot()
    ranked = (out.get("ranked_products") or [])[:5]
    shown = [p["product_id"] for p in ranked]
    reply = out.get("final_response") or ""
    return {
        "id": query["id"],
        "query": query["query"],
        "history": query.get("history", []),
        "tags": query.get("tags", []),
        "shown": shown,
        "shown_names": [p["name"][:80] for p in ranked],
        "preferences": out.get("preferences"),
        "relaxed": out.get("relaxed_filters") or [],
        "reply": reply[:300],
        "score": score_query(query, shown, reply),
        "llm_calls": after["calls"] - before["calls"],
        "tokens": after["tokens"] - before["tokens"],
        "seconds": round(seconds, 2),
    }


def save(path: Path, result: dict) -> None:
    result["summary"] = summarize(result["queries"])
    result["by_tag"] = by_tag(result["queries"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def rescore(path: Path) -> dict:
    """Score a saved run again against the current labels. No model or database calls."""
    labels = {q["id"]: q for q in json.loads(QUERIES_FILE.read_text(encoding="utf-8"))["queries"]}
    result = json.loads(path.read_text(encoding="utf-8"))
    for rec in result["queries"]:
        if not rec.get("error"):
            rec["score"] = score_query(labels[rec["id"]], rec["shown"], rec.get("reply", ""))
    result["rescored"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(path, result)
    return result


def line(rec: dict) -> str:
    if rec.get("error"):
        return f"{rec['id']} ERROR {rec['error'][:120]}"
    s = rec["score"]
    if s["kind"] == "none":
        verdict = "refused" if s["correct_refusal"] else f"WRONG (showed {s['shown']})"
    else:
        verdict = f"{'hit ' if s['hit5'] else 'MISS'} p@3={s['precision3']:.2f} shown={s['shown']}"
    return f"{rec['id']} {verdict:<28} {rec['tokens']:>6} tok {rec['seconds']:>5.1f}s  {rec['query'][:40]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True)
    parser.add_argument("--mode", choices=("record", "replay", "live"), default="record")
    parser.add_argument("--model", default="", help="Groq model (default: the app's GROQ_MODEL)")
    parser.add_argument("--cassette", default="", help="cassette file (default: eval/cassettes/retrieval_<model>.json)")
    parser.add_argument("--database-url", default=os.getenv("BASELINE_DATABASE_URL", DEFAULT_DB))
    parser.add_argument("--only", default="", help="comma-separated query ids")
    parser.add_argument("--tags", default="", help="comma-separated tags; keep queries having any of them")
    parser.add_argument("--resume", action="store_true", help="keep queries already scored in the output file")
    parser.add_argument("--token-budget", type=int, default=0, help="stop after this many tokens (0 = no cap)")
    parser.add_argument("--tpm-budget", type=int, default=7600, help="Groq tokens/minute to stay under")
    parser.add_argument("--turn-token-estimate", type=int, default=2600)
    parser.add_argument("--env-file", default="", help="load environment variables from this .env file")
    parser.add_argument("--trace", action="store_true", help="keep LangSmith tracing enabled")
    parser.add_argument("--rescore", action="store_true", help="re-score the saved run <label> against current labels")
    args = parser.parse_args()

    if args.rescore:
        result = rescore(OUT_DIR / f"{args.label}.json")
        print(json.dumps(result["summary"], indent=1))
        return 0

    configure_environment(args)
    install_meter()
    from app.core.config import GROQ_MODEL

    cassette = Path(args.cassette) if args.cassette else cassette_for(GROQ_MODEL)
    os.environ["LLM_CASSETTE_MODE"] = "" if args.mode == "live" else args.mode
    os.environ["LLM_CASSETTE_PATH"] = str(cassette)
    from app.agents.product_agent import product_agent_graph

    quiet_app_loggers()

    data = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))
    queries = data["queries"]
    if args.only:
        wanted = {q.strip() for q in args.only.split(",") if q.strip()}
        queries = [q for q in queries if q["id"] in wanted]
    if args.tags:
        tags = {t.strip() for t in args.tags.split(",") if t.strip()}
        queries = [q for q in queries if tags & set(q.get("tags", []))]

    out_path = OUT_DIR / f"{args.label}.json"
    result = {
        "label": args.label,
        "model": GROQ_MODEL,
        "mode": args.mode,
        "database": urlparse(args.database_url).path.lstrip("/"),  # name only: never the credentials
        "cassette": str(cassette.relative_to(REPO)) if cassette.is_relative_to(REPO) else str(cassette),
        "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "queries": [],
    }
    if args.resume and out_path.exists():
        previous = json.loads(out_path.read_text(encoding="utf-8"))
        result["queries"] = [r for r in previous.get("queries", []) if not r.get("error")]
        result["started"] = previous.get("started", result["started"])
    done = {r["id"] for r in result["queries"]}
    todo = [q for q in queries if q["id"] not in done]
    print(f"model={GROQ_MODEL} mode={args.mode} db={result['database']} queries={len(todo)} (skipping {len(done)})")

    stopped = ""
    for query in todo:
        try:
            rec = run_query(product_agent_graph, query, args)
        except Exception as exc:  # one bad query must not lose the run
            if is_daily_cap(exc):
                stopped = "Groq daily token cap reached; rerun later with --resume"
                break
            rec = {"id": query["id"], "query": query["query"], "tags": query.get("tags", [])}
            rec["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        result["queries"].append(rec)
        print(line(rec), flush=True)
        result["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        save(out_path, result)
        if args.token_budget and METER.snapshot()["tokens"] >= args.token_budget:
            stopped = f"token budget of {args.token_budget} reached; rerun with --resume"
            break

    result["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(out_path, result)
    if stopped:
        print(f"STOPPED: {stopped}")
    print(json.dumps(result["summary"], indent=1))
    print(f"results: {out_path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
