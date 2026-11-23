# Phase 5: Ship and showcase
- **Status:** Not started
- **Branch:** `phase-5-ship`
- **Depends on:** Phases 0–4
- **Decisions:** [0013](../decisions/0013-judge-facing-priorities.md); write new ADRs for the host and any auth changes

## Goal
Meet the definition of done in `ROADMAP.md`. A judge opens the README, clicks a live link that works, tries every flow without an account, and sees measured numbers.

## Tasks
- [ ] Plan mode: refine this plan.
  - Choose a host that doesn't sleep or expire, sized to the app memory measured in Phase 3. A free Postgres with pgvector that doesn't expire (Neon or Supabase) plus a web host, or a small paid instance.
  - Ask the user whether the capstone brief still needs a ToolNode in each agent (ADR 0002).
- [ ] Deploy:
  - one deploy path, with the other removed;
  - pgvector enabled and embeddings loaded;
  - a health check;
  - a keep-warm ping if the host sleeps.
- [ ] A one-click "Try as demo shopper" button on the login page, clearly labelled. The demo shopper's seeded orders (processing, shipped, delivered) reset daily, so cancel can always be tried. Google sign-in stays for real accounts. Secure session cookies.
- [ ] A small ticket inbox inside FastAPI: list and resolve tickets. Safety tickets go to the webhook channel (`ESCALATION_WEBHOOK_URL`).
- [ ] Load test with 20 users. Report p95 latency and the error rate, including a period of Groq rate-limiting.
- [ ] A Grafana dashboard covering route mix, tokens, p95 latency, error rate, fallback rate and empty-result rate. Add a screenshot to the README.
- [ ] Final scorecard: 3 live baseline runs on the production model, and the Phase 0 metrics. Update the Today column in `ROADMAP.md`.
- [ ] README as a showcase, with setup moved to `docs/SETUP.md`:
  - live link and a 30-second GIF;
  - a results table with how each number was measured;
  - the graph diagram;
  - "what the model decides, what the code decides";
  - links to the ADRs and the case study.
- [ ] `docs/CASE_STUDY.md`: the problem, measured before and after, the decisions (with ADR links), and the trade-offs.
- [ ] **Update the visual explainer** (`docs/visual/agent-flow.html`, see `docs/visual/README.md`):
  - built steps lose their "Proposed" tag;
  - add the subgraphs, the search loop, the cancel pause, the ticket handoff and hybrid search;
  - measured numbers;
  - file references checked against the code;
  - republish to the same artifact URL.
- [ ] Portfolio: list the sentences in `../Portfolio-main/preview.html` that need new numbers. The user edits the portfolio.
- [ ] Clean the root folder: `pytest-cache-files-*`, `tat.txt`, `test_live.py`, `generate_*.py`, `inspect_dataset.py` and old reports. Ask before deleting anything.
- [ ] Fill in Results, mark the project Done, and run `/handoff`.

## Acceptance criteria
Every item in the ROADMAP's definition of done, measured and recorded here. That includes trying search, an order lookup and a cancel from the live link within 2 minutes, without an account.

## Results
_Fill in during the phase._
