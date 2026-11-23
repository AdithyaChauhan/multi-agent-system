#!/usr/bin/env python3
"""Fail CI when a replayed eval drops below its bar (Phase 4, ADR 0015).

Reads what eval/ci_replay.sh just wrote and checks:
- product search (100 queries, ranker off): recall@5, precision@3 and refusals at or above the bars below,
  with no errors;
- the 51 baseline conversations: at least MIN_BASELINE pass, with no cassette misses;
- the adversarial and Q&A sets: every conversation passes (routing-quality cases are only reported),
  with no cassette misses.

The bars are the measured values on 2026-11-23 (Phase 4), so any drop fails the build. Raise them
when a change measurably improves a number; lower them only with an ADR saying why.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RETRIEVAL = {"recall@5": 0.97, "precision@3": 0.915, "correct_refusal_rate": 1.0}
MIN_BASELINE = 47
# Conversations about routing quality, not safety: a miss is printed but doesn't fail the build.
REPORT_ONLY_TAGS = {"routing"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    problems = []
    retrieval = load(REPO / "eval/retrieval_runs/ci-retrieval-combined-summary.json")["summary"]
    if retrieval.get("errors"):
        problems.append(f"retrieval: {retrieval['errors']} queries errored (cassette miss?)")
    for metric, bar in RETRIEVAL.items():
        value = retrieval.get(metric)
        if value is None or value < bar:
            problems.append(f"retrieval: {metric} {value} < {bar}")

    for label, minimum in (("ci-baseline", MIN_BASELINE), ("ci-adversarial", None), ("ci-qa", None)):
        summary = load(REPO / f"eval/baseline_runs/{label}_summary.json")
        run = load(REPO / f"eval/baseline_runs/{label}_run1.json")
        if minimum is None:  # every conversation must pass, except routing-quality cases (reported)
            required = [c for c in run["conversations"] if not set(c.get("tags", [])) & REPORT_ONLY_TAGS]
            failed = [c["id"] for c in required if not c["passed"]]
            reported = [c["id"] for c in run["conversations"] if c not in required and not c["passed"]]
            if failed:
                problems.append(f"{label}: failed {', '.join(failed)}")
            if reported:
                print(f"{label}: routing-quality cases that missed (reported, not gating): {', '.join(reported)}")
        else:
            passed, total = run["summary"]["conversations_passed"], run["summary"]["conversations"]
            if passed < minimum:
                failed = ", ".join(run["summary"].get("failed_conversations", []))
                problems.append(f"{label}: {passed}/{total} passed, need {minimum} (failed: {failed})")
        if summary.get("cassette_misses"):
            problems.append(f"{label}: {summary['cassette_misses']} model calls had no recorded answer")

    print(json.dumps({"retrieval": {k: retrieval.get(k) for k in RETRIEVAL}}, indent=1))
    if problems:
        print("EVAL GATE FAILED:\n- " + "\n- ".join(problems))
        return 1
    print("eval gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
