#!/usr/bin/env python3
"""Combine baseline run files (e.g. the two model partitions) into one before/after table.

python eval/summarize_baseline.py before_gptoss120b before_gptoss20b -- after_gptoss120b after_gptoss20b
"""

import json
import statistics
import sys
from pathlib import Path

RUNS = Path(__file__).resolve().parent / "baseline_runs"


def load(labels):
    convs = []
    for label in labels:
        data = json.loads((RUNS / f"{label}_run1.json").read_text(encoding="utf-8"))
        for c in data["conversations"]:
            convs.append({**c, "model": data.get("model")})
    return convs


def stats(convs):
    turns = [t for c in convs for t in c["turns"]]
    product = [t for t in turns if t["route"] == "product"]
    out = {
        "conversations_passed": f"{sum(c['passed'] for c in convs)}/{len(convs)}",
        "turns_passed": f"{sum(t['passed'] for t in turns)}/{len(turns)}",
        "llm_calls_per_turn": round(sum(t["llm_calls"] for t in turns) / len(turns), 2),
        "tokens_per_turn": round(sum(t["tokens"] for t in turns) / len(turns)),
        "tokens_per_product_turn": round(sum(t["tokens"] for t in product) / max(1, len(product))),
        "seconds_per_turn_mean": round(statistics.mean(t["seconds"] for t in turns), 2),
        "seconds_per_turn_median": round(statistics.median(t["seconds"] for t in turns), 2),
        "total_tokens": sum(t["tokens"] for t in turns),
    }
    by_route = {}
    for t in turns:
        r = by_route.setdefault(t["route"], [0, 0, 0.0, 0])
        r[0] += 1
        r[1] += t["llm_calls"]
        r[2] += t["seconds"]
        r[3] += t["tokens"]
    out["by_route"] = {
        k: {"turns": n, "calls/turn": round(c / n, 2), "s/turn": round(s / n, 2), "tokens/turn": round(tok / n)}
        for k, (n, c, s, tok) in sorted(by_route.items())
    }
    return out


def main():
    args = sys.argv[1:]
    split = args.index("--") if "--" in args else len(args)
    before, after = args[:split], args[split + 1 :]
    result = {"before": stats(load(before))}
    if after:
        b = {c["id"]: c["passed"] for c in load(before)}
        a_convs = load(after)
        result["after"] = stats(a_convs)
        result["fixed"] = sorted(c["id"] for c in a_convs if c["passed"] and not b.get(c["id"]))
        result["regressed"] = sorted(c["id"] for c in a_convs if not c["passed"] and b.get(c["id"]))
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
