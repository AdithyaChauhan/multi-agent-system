# Phase 4: Demo never breaks
- **Status:** Not started
- **Branch:** `phase-4-reliability`
- **Depends on:** Phase 3 (the CI eval job needs pgvector in the Postgres service)
- **Decisions:** [0002](../decisions/0002-guardrails-in-python.md), [0008](../decisions/0008-safety-floor.md), [0013](../decisions/0013-judge-facing-priorities.md)

## Goal
A judge never sees an error page. The app keeps answering when Groq is rate-limited, resists attacks, and every change is measured in CI.

## Tasks
- [ ] Plan mode: refine this plan.
- [ ] Model fallback chain on 429 or a timeout: `GROQ_MODEL`, then `GROQ_FALLBACK_MODELS` (for example gpt-oss-120b, then qwen). Each model has its own daily quota. Count fallbacks in the metrics. Never fall back to another account (0013).
- [ ] When every model is out: a friendly "busy, try again in a minute" reply with a retry hint. The logs keep the detail.
- [ ] Cache repeated identical product searches (normalised message plus filters) for a short time, so popular demo questions cost no tokens.
- [ ] A per-session token budget, with a clear message when it's reached.
- [ ] Safety floor (ADR 0008) with tests: real reports that must escalate, plus product names (Fire TV, Fire-Boltt) that must not.
- [ ] `eval/adversarial.json`, scored on routes and database effects, never on reply wording:
  - prompt injection in the message and inside product text;
  - another user's order ids;
  - "I'm an admin";
  - attempts to cancel without confirmation, or by resuming another user's pause.
- [ ] Replay evals in CI: a Postgres + pgvector service, the baseline data restored, then the retrieval and conversation replays plus the adversarial set at 0 tokens. The job fails on a metric drop.
- [ ] A per-user rate limit on `/chat`.
- [ ] Redact personal data (emails, phone numbers, addresses) from logs and LangSmith traces.
- [ ] Fill in Results, update the ROADMAP and run `/handoff`.

## Acceptance criteria
- 0 adversarial failures.
- A mocked 429 on every model produces the friendly message, and a 429 on the first model is answered by the next one. Both are covered by tests.
- CI runs the replay evals on every push.
- The safety tests pass, and the 51-conversation baseline doesn't regress.

## Results
_Fill in during the phase._
