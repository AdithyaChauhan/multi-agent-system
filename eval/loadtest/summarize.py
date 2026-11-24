"""Summarize one load test: Locust's stats CSV, the reply outcomes, and the app's /metrics delta.

usage: python eval/loadtest/summarize.py <out_dir> <label>
Reads <label>_stats.csv, <label>_outcomes.json, <label>_metrics_before.txt and _after.txt from
<out_dir>, prints the report and writes <label>_summary.json next to them.
"""

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

LINE = re.compile(r'^([a-zA-Z_:][\w:]*)(?:\{(.*)\})?\s+([-+\deE.naNInf]+)$')
LABEL = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


def parse_metrics(text: str) -> dict:
    """{(name, ((label, value), ...)): value} for every sample line."""
    out = {}
    for line in text.splitlines():
        m = LINE.match(line.strip())
        if m and not line.startswith("#"):
            labels = tuple(sorted(LABEL.findall(m.group(2) or "")))
            out[(m.group(1), labels)] = float(m.group(3))
    return out


def delta(before: dict, after: dict, name: str, by: str = "", where: dict = None) -> dict:
    """Increase of a counter during the test, summed over labels (or grouped by one label)."""
    sums = defaultdict(float)
    for (n, labels), v in after.items():
        if n == name and all(dict(labels).get(k) == w for k, w in (where or {}).items()):
            key = dict(labels).get(by, "") if by else "all"
            sums[key] += v - before.get((n, labels), 0.0)
    return {k: round(v) for k, v in sums.items() if v}


def main(out_dir: Path, label: str) -> dict:
    with (out_dir / f"{label}_stats.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    steps = {}
    for r in rows:
        n = int(r["Request Count"])
        steps[r["Name"]] = {
            "requests": n,
            "failures": int(r["Failure Count"]),
            "median_ms": float(r["50%"] or 0),
            "p95_ms": float(r["95%"] or 0),
            "max_ms": float(r["Max Response Time"] or 0),
        }
    outcomes = json.loads((out_dir / f"{label}_outcomes.json").read_text(encoding="utf-8"))
    before = parse_metrics((out_dir / f"{label}_metrics_before.txt").read_text(encoding="utf-8"))
    after = parse_metrics((out_dir / f"{label}_metrics_after.txt").read_text(encoding="utf-8"))

    chat_outcomes = defaultdict(int)
    for step, counts in outcomes.items():
        for outcome, n in counts.items():
            chat_outcomes[outcome] += n
    total_chat = sum(chat_outcomes.values())
    agg = steps.get("Aggregated", {})
    summary = {
        "label": label,
        "requests": agg.get("requests"),
        "error_rate": round(agg.get("failures", 0) / max(1, agg.get("requests", 0)), 4),
        "p95_ms_all": agg.get("p95_ms"),
        "median_ms_all": agg.get("median_ms"),
        "steps": {k: v for k, v in steps.items() if k != "Aggregated"},
        "chat_replies": dict(chat_outcomes),
        "answered_share": round(chat_outcomes.get("answered", 0) / max(1, total_chat), 3),
        "llm_calls": delta(before, after, "llm_requests_total").get("all", 0),
        "llm_tokens": delta(before, after, "llm_tokens_total", where={"token_type": "total"}).get("all", 0),
        "llm_cache_hits": delta(before, after, "llm_cache_hits_total").get("all", 0),
        "llm_fallbacks_to": delta(before, after, "llm_fallback_total", by="to_model"),
        "llm_fallback_reasons": delta(before, after, "llm_fallback_total", by="reason"),
        "llm_unavailable": delta(before, after, "llm_unavailable_total").get("all", 0),
        "chat_limited": delta(before, after, "chat_limited_total", by="limit"),
    }
    (out_dir / f"{label}_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return summary


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2])
