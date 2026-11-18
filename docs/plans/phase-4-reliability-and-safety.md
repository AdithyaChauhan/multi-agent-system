# Phase 4: Reliability and safety
- **Status:** Not started
- **Branch:** `phase-4-reliability`
- **Depends on:** nothing hard. It can run alongside Phase 3.
- **Decisions:** [0002](../decisions/0002-guardrails-in-python.md), [0008](../decisions/0008-safety-floor.md)

## Goal
The app behaves well when the model is rate-limited or attacked, and real safety reports always escalate.

## Tasks
- [ ] Plan mode: refine this plan.
- [ ] Groq 429: show a friendly "busy, try again in a minute" reply with a retry hint. The logs keep the detail.
- [ ] Fallback model on 429 (`GROQ_FALLBACK_MODEL`), counted in the metrics.
- [ ] A per-session token budget, with a clear message when it's reached.
- [ ] Safety floor (ADR 0008) with tests: real reports that must escalate, plus product names (Fire TV, Fire-Boltt) that must not.
- [ ] `eval/adversarial.json`, scored on routes and database effects, never on reply wording:
  - prompt injection in the message and inside product text;
  - another user's order ids;
  - "I'm an admin";
  - attempts to cancel without confirmation.
- [ ] `/cancel-order`: CSRF protection and an idempotency key. Add a per-user rate limit on `/chat`.
- [ ] Redact personal data (emails, phone numbers, addresses) from logs and LangSmith traces.
- [ ] Optional: stream replies (SSE) so the first words appear in under a second.
- [ ] Fill in Results, update the ROADMAP and run `/handoff`.

## Acceptance criteria
- 0 adversarial failures.
- A mocked 429 produces the friendly message, and the fallback path is covered by tests.
- The safety tests pass, and the 51-conversation baseline doesn't regress.

## Results
_Fill in during the phase._
