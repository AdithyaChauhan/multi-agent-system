#!/usr/bin/env python3
"""Run eval/run_retrieval.py on a set of queries with the same model per query as v3b, and combine.

Phase 3 tuned and measured hybrid search with this (ADR 0014). Each query runs on the model that
answered it in the v3b runs (v3b-gptoss20b, v3b-gptoss120b-rest, v3b-qwen-rest), so numbers compare
query for query with v3b.

    python eval/run_split.py tune-dev dev PRODUCT_RANKER=off --mode replay       # tuning: 0 tokens
    python eval/run_split.py v4b-test test --mode fill                          # final: ranker live
    python eval/run_split.py robust ids:q001,q002 --mode fill --db multi_agent_renamed --cassette-prefix renamed

Halves come from eval/query_split.json: dev, test, all, or ids:<comma-separated ids>. NAME=VALUE
arguments set environment variables (PRODUCT_SEARCH, PRODUCT_RANKER, HYBRID_*). Writes the usual
per-model run files plus <label>-combined-summary.json in eval/retrieval_runs/.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from eval.retrieval_metrics import by_tag, summarize  # noqa: E402

RUNS = REPO / "eval" / "retrieval_runs"
MODEL_RUNS = {
    "openai/gpt-oss-20b": "v3b-gptoss20b",
    "openai/gpt-oss-120b": "v3b-gptoss120b-rest",
    "qwen/qwen3.8-27b": "v3b-qwen-rest",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def query_ids(half: str) -> set:
    if half.startswith("ids:"):
        return {q for q in half[4:].split(",") if q}
    split = load(REPO / "eval" / "query_split.json")
    return set(split["dev"] + split["test"]) if half == "all" else set(split[half])


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    label, half, *rest = sys.argv[1:]
    env = {k: v for k, v in os.environ.items() if k != "GROQ_API_KEY"}  # the key comes from .env
    mode, db, prefix, i = "replay", None, None, 0
    while i < len(rest):
        arg = rest[i]
        if arg in ("--mode", "--db", "--cassette-prefix"):
            value = rest[i + 1]
            mode, db, prefix = (
                value if arg == "--mode" else mode,
                value if arg == "--db" else db,
                value if arg == "--cassette-prefix" else prefix,
            )
            i += 2
            continue
        key, value = arg.split("=", 1)
        env[key] = value
        i += 1
    if mode == "replay":
        # Replay never calls Groq, but the client refuses to start without a key, and CI has no .env.
        env["GROQ_API_KEY"] = "replay-no-calls"
    if db:
        from eval.run_baseline import DEFAULT_DB

        env["BASELINE_DATABASE_URL"] = DEFAULT_DB.rsplit("/", 1)[0] + "/" + db

    ids, records, runs = query_ids(half), [], []
    for model, v3b in MODEL_RUNS.items():
        mine = [q["id"] for q in load(RUNS / f"{v3b}.json")["queries"] if q["id"] in ids]
        if not mine:
            continue
        short = model.split("/")[-1]
        run = f"{label}-{short}"
        cmd = [sys.executable, "eval/run_retrieval.py", "--label", run, "--model", model, "--mode", mode]
        cmd += ["--only", ",".join(mine)]
        if prefix:
            cmd += ["--cassette", f"eval/cassettes/{prefix}_{short}.json"]
        done = subprocess.run(
            cmd, cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        for line in done.stdout.splitlines():
            if line.startswith("q") and any(w in line for w in (" MISS", "WRONG", "ERROR")):
                print("   ", line[:110])
        if done.returncode:
            print(f"   {run} exited {done.returncode}: {done.stderr[-400:]}")
        records += load(RUNS / f"{run}.json")["queries"]
        runs.append(run)

    summary, tags = summarize(records), by_tag(records)
    settings = {k: env[k] for k in env if k.startswith(("HYBRID", "PRODUCT", "NOT_CARRIED"))}
    out = {"label": label, "half": half, "mode": mode, "database": db, "settings": settings, "runs": runs}
    (RUNS / f"{label}-combined-summary.json").write_text(
        json.dumps({**out, "summary": summary, "by_tag": tags}, indent=1), encoding="utf-8"
    )
    keep = ("queries", "errors", "recall@5", "precision@3", "mrr", "empty_rate", "correct_refusal_rate")
    print(label, {k: summary[k] for k in keep})
    print("   recall@5 by tag:", {k: v.get("recall@5") for k, v in tags.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
