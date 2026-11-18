# Phase 3: Search state and filter chips
- **Status:** Not started
- **Branch:** `phase-3-state`
- **Depends on:** Phase 2 (the rewrite schema). The state table can start earlier.
- **Decisions:** [0007](../decisions/0007-search-state-in-postgres.md)

## Goal
Follow-up turns never silently lose filters, the app keeps no conversation state in memory, and the shopper can see and remove active filters.

## Tasks
- [ ] Plan mode: refine this plan, including the patch format (set and unset fields) and the merge rules.
- [ ] Migration: a `session_state` table (session id, state as JSONB, `updated_at`).
- [ ] Replace `_session_preferences` in `app/main.py` with loading and saving that state.
- [ ] Change the rewrite schema so the model returns a patch, and code merges it. Rules to test:
  - a new product clears the old constraints;
  - a refinement keeps them;
  - an explicit "any brand" unsets the brand.
- [ ] `ChatResponse` gains `active_filters`, and `app/static/chat.html` shows them as chips. Removing a chip sends a patch.
- [ ] Tests: follow-up chains of 3–5 turns, and state surviving an app restart.
- [ ] Measure the follow-up queries in the Phase 0 set, plus the baseline.
- [ ] Fill in Results, update the ROADMAP and run `/handoff`.

## Acceptance criteria
- Follow-up chains pass, and no follow-up query regresses in the Phase 0 set.
- `docker compose restart app` in the middle of a conversation keeps the filters.
- Removing a chip works end to end in the browser.

## Results
_Fill in during the phase._
