"""Scoring for eval/run_retrieval.py. Pure functions: no app, model or database imports.

Definitions (see docs/plans/phase-0-measuring-stick.md):
- recall@5: share of queries with at least one `exact` product in the top 5 shown (hit rate@5).
  For brands we don't carry, `exact` is empty and any `ok` product (the right kind) counts.
- precision@3: share of the top 3 shown that are `exact` or `ok`; 0 when nothing is shown.
- MRR: mean of 1 / rank of the first hit in the top 5.
- empty rate: share of queries that should show products but showed none.
- correct-refusal rate: out-of-scope queries that showed nothing and said so.
"""

import math
import re

REFUSAL = re.compile(r"don.t carry|do not carry|not available|couldn.t find|no \w+ (match|found)", re.IGNORECASE)


def score_query(query: dict, shown: list, reply: str) -> dict:
    """Score one query. `shown` is the product ids the shopper saw, in display order."""
    if query.get("expect_none"):
        return {"kind": "none", "correct_refusal": not shown and bool(REFUSAL.search(reply or "")), "shown": len(shown)}
    exact = set(query["expect"]["exact"])
    ok = set(query["expect"]["ok"])
    target = exact or ok
    relevant = exact | ok
    top3 = shown[:3]
    first = next((rank for rank, pid in enumerate(shown[:5], 1) if pid in target), None)
    return {
        "kind": "search",
        "hit5": first is not None,
        "rr": round(1 / first, 3) if first else 0.0,
        "precision3": round(sum(pid in relevant for pid in top3) / len(top3), 3) if top3 else 0.0,
        "empty": not shown,
        "shown": len(shown),
    }


def percentile(values: list, pct: float):
    """Nearest-rank percentile; None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def _mean(values: list):
    return round(sum(values) / len(values), 3) if values else None


def summarize(records: list) -> dict:
    """Aggregate per-query records (each has 'score', 'llm_calls', 'tokens', 'seconds', optional 'error')."""
    done = [r for r in records if not r.get("error")]
    search = [r["score"] for r in done if r["score"]["kind"] == "search"]
    none = [r["score"] for r in done if r["score"]["kind"] == "none"]
    seconds = [r["seconds"] for r in done]
    return {
        "queries": len(records),
        "scored": len(done),
        "errors": len(records) - len(done),
        "recall@5": _mean([float(s["hit5"]) for s in search]),
        "precision@3": _mean([s["precision3"] for s in search]),
        "mrr": _mean([s["rr"] for s in search]),
        "empty_rate": _mean([float(s["empty"]) for s in search]),
        "correct_refusal_rate": _mean([float(s["correct_refusal"]) for s in none]),
        "llm_calls_per_query": _mean([r["llm_calls"] for r in done]),
        "tokens_per_query": _mean([r["tokens"] for r in done]),
        "p50_seconds": percentile(seconds, 50),
        "p95_seconds": percentile(seconds, 95),
    }


def by_tag(records: list) -> dict:
    tags = sorted({t for r in records for t in r.get("tags", [])})
    out = {}
    for tag in tags:
        subset = summarize([r for r in records if tag in r.get("tags", [])])
        keep = ("scored", "recall@5", "precision@3", "mrr", "empty_rate", "correct_refusal_rate")
        out[tag] = {k: v for k, v in subset.items() if k in keep and v is not None}
    return out
