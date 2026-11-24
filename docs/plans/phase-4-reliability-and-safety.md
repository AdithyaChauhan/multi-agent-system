# Phase 4: Demo never breaks
- **Status:** Done (2026-11-23)
- **Branch:** `phase-4-reliability`, off `phase-3-hybrid-search`
- **Decisions:** [0002](../decisions/0002-guardrails-in-python.md), [0008](../decisions/0008-safety-floor.md), [0013](../decisions/0013-judge-facing-priorities.md), [0015](../decisions/0015-demo-never-breaks.md)

## Goal
A judge never sees an error page. The app keeps answering when Groq is rate-limited or a model is retired, resists attacks, and every change is measured in CI.

## Tasks
- [x] Model fallback chain (`GROQ_FALLBACK_MODELS`): 429, timeout, 5xx and retired model move on; cooldowns; metrics `llm_fallback_total` and `llm_unavailable_total`.
- [x] All models down: a friendly "busy" reply, never a 500 (`/chat` and `/chat/stream`).
- [x] Answer cache for identical calls (30 minutes, 512 entries).
- [x] Limits: 20 turns a minute and 150 a day per user, or per IP when anonymous. Turn counts instead of the planned token budget (see 0015).
- [x] Safety floor (0008): `router.SAFETY_PATTERN`, escalate-only; 11 reports and 11 look-alikes tested.
- [x] The catalog checks "unclear" routes and empty extractions (fuzz balls → lint remover).
- [x] Data: bare "table" and "desk" are no longer laptop-table aliases (migration `c3a9d2e7f4b1`). p03 still fails (see Results).
- [x] p19: after widening, products of the requested type are shown when the ranker rejects them all.
- [x] PII redaction in logs and LangSmith traces.
- [x] **Found during the phase:**
  - `X-User-ID` let anyone act as any user; it's now only with `ALLOW_X_USER_ID=true`;
  - `/auth/demo-login` accepted any id; now only `demo-user-N`.
- [x] `eval/adversarial_conversations.json` (15) and `run_baseline.py --conversations`, with an `as_user` confirm step.
- [x] CI:
  - `scripts/make_ci_fixture.py` and `eval/fixtures/ci_baseline.dump`;
  - `eval/ci_replay.sh` and `eval/ci_gate.py`;
  - the `replay-evals` job replaces the dead self-hosted `evaluate` job;
  - `alembic` added to `requirements.txt`.
- [x] Results, ADR 0015, ROADMAP.

## Acceptance criteria
- [x] 0 adversarial failures (15/15).
- [x] A 429, 5xx or retired model on the first model is answered by the next one; all down gives a friendly reply. Tests plus a live retired-model check.
- [x] The safety pattern tests pass, and product names never escalate.
- [x] The 51-conversation baseline is ≥ 47/51 (48), and retrieval doesn't drop.
- [x] The CI replay job passes in a local Linux container with 0 cassette misses.
- [x] Emails and phone numbers are masked in logs and traces.
- [x] Prompts unchanged (68 lines).

## Results (2026-11-23)
Every number is 1 run on `multi_agent_baseline` unless it says otherwise.

| Check | Result |
|---|---|
| Adversarial set (15 conversations, gpt-oss-20b, recorded once at about 20K tokens) | **15/15** |
| 51-conversation baseline (gpt-oss-20b, fill mode, no new model calls) | **48/51** (Phase 3: 47). p19 now passes; p03, p10 and s16 still fail |
| Product search, all 100 queries, ranker off (replay, 0 tokens) | recall@5 **0.979**, precision@3 0.933, refusals 1.0 |
| CI simulation (`python:3.12-slim`, fixture restored, embeddings recomputed) | the same retrieval numbers, 48/51, 15/15, 0 cassette misses, gate passed |
| Unit tests | 338 pass, coverage 89% |

**Live checks** (`docker compose`):
- the app started with `GROQ_MODEL=openai/a-retired-model` answered "something to keep my room warm in winter" with 3 heater cards; every call logged `LLM_FALLBACK … model_retired … next=openai/gpt-oss-20b`;
- 21 "hi" messages in a row gave 20 replies (19 from the cache), then the rate-limit message.

**Not done or still open:**
- **p03 "table":** the alias is gone, but the model names "table" as the product and hybrid search finds laptop tables. A low-similarity refusal would also refuse "pointing device" on the renamed catalog (0.65 against "table" at 0.71), so it's left (0015).
- **The live safety check** wasn't run against `multi_agent_db`, to keep critical tickets out of the user's own database. a07 covers it on the baseline database.
- **Limits and the cache are per process.**
- **CI runs on GitHub only after a push,** which is the user's call.
- **About 25K tokens used** in this phase.
