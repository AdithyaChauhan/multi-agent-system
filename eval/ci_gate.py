#!/usr/bin/env python3
"""Fail CI when a replayed eval drops below its bar (Phase 4, ADR 0015).

Reads what eval/ci_replay.sh just wrote and checks:
- product search (100 queries, ranker off): recall@5, precision@3 and refusals at or above the bars below,
  with no errors;
- the 51 baseline conversations: at least MIN_BASELINE pass, with no cassette misses;
- the adversarial and Q&A sets: every conversation passes (routing-quality cases are only reported),
  with no cassette misses.

- the judge's set (Phase 6): at least MIN_JUDGE pass, with no cassette misses.

The bars are the measured values on 2026-11-23 (Phase 4), so any drop fails the build. Raise them
when a change measurably improves a number; lower them only with an ADR saying why.

Phase 6 added checks every set gets (ADR 0021). Promises nothing keeps gate at once. The two checks of
what the screen shows (the same product twice, a product chip that matches no card) are printed but don't
gate until PR B groups variants and keeps the chips and cards together; PR B removes SCREEN_ONLY.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RETRIEVAL = {"recall@5": 0.97, "precision@3": 0.915, "correct_refusal_rate": 1.0}
MIN_BASELINE = 47
MIN_JUDGE = 10  # measured after Phase 6 PR A (2026-11-28); the judge's session before any fix passed 1 of 14
# Conversations about routing quality, not safety: a miss is printed but doesn't fail the build.
REPORT_ONLY_TAGS = {"routing"}
# Failures of what the screen shows, reported until Phase 6 PR B fixes their cause (ADR 0021).
SCREEN_ONLY = ("the same product is shown twice", "product chip ")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def gating_failures(conversation: dict) -> list:
    return [f for t in conversation["turns"] for f in t["failures"] if not f.startswith(SCREEN_ONLY)]


def passes(conversation: dict) -> bool:
    return not gating_failures(conversation)


def main() -> int:
    problems = []
    retrieval = load(REPO / "eval/retrieval_runs/ci-retrieval-combined-summary.json")["summary"]
    if retrieval.get("errors"):
        problems.append(f"retrieval: {retrieval['errors']} queries errored (cassette miss?)")
    for metric, bar in RETRIEVAL.items():
        value = retrieval.get(metric)
        if value is None or value < bar:
            problems.append(f"retrieval: {metric} {value} < {bar}")

    sets = (("ci-baseline", MIN_BASELINE), ("ci-adversarial", None), ("ci-qa", None), ("ci-judge", MIN_JUDGE))
    for label, minimum in sets:
        summary = load(REPO / f"eval/baseline_runs/{label}_summary.json")
        run = load(REPO / f"eval/baseline_runs/{label}_run1.json")
        screen = [c["id"] for c in run["conversations"] if not c["passed"] and passes(c)]
        if screen:
            print(f"{label}: screen checks that missed (reported until Phase 6 PR B): {', '.join(screen)}")
        if minimum is None:  # every conversation must pass, except routing-quality cases (reported)
            required = [c for c in run["conversations"] if not set(c.get("tags", [])) & REPORT_ONLY_TAGS]
            failed = [c["id"] for c in required if not passes(c)]
            reported = [c["id"] for c in run["conversations"] if c not in required and not passes(c)]
            if failed:
                problems.append(f"{label}: failed {', '.join(failed)}")
            if reported:
                print(f"{label}: routing-quality cases that missed (reported, not gating): {', '.join(reported)}")
        else:
            total = len(run["conversations"])
            failed = [c["id"] for c in run["conversations"] if not passes(c)]
            if total - len(failed) < minimum:
                problems.append(
                    f"{label}: {total - len(failed)}/{total} passed, need {minimum} (failed: {', '.join(failed)})"
                )
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
