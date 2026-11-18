# Phase 5: Ship and showcase
- **Status:** Not started
- **Branch:** `phase-5-ship`
- **Depends on:** Phases 0–4
- **Decisions:** write new ADRs for the deploy path and any auth changes

## Goal
Meet the definition of done in `ROADMAP.md` and present the project with measured numbers.

## Tasks
- [ ] Plan mode: refine this plan. Ask the user to choose Helm or Render, and whether the capstone brief still needs a ToolNode in each agent (ADR 0002).
- [ ] Admin page inside FastAPI: list, assign and resolve tickets, and reply into the chat. Safety tickets notify a human channel (an email or Slack webhook).
- [ ] Auth review: the existing Google sign-in (`static/login.html`, `callback.html`). Turn off demo users outside dev, and use secure session cookies.
- [ ] Two app replicas: show a session continuing across them.
- [ ] Load test with 20 users. Report p95 latency and the error rate, including a period of Groq rate-limiting.
- [ ] Grafana dashboard and alerts covering:
  - route mix, tokens, cost and p95 latency;
  - error rate, fallback rate and empty-result rate;
  - thumbs-up/down feedback.
- [ ] Keep one deploy path and remove the other.
- [ ] Final scorecard: 3 live baseline runs on the production model, and the Phase 0 metrics. Update the Today column in `ROADMAP.md`.
- [ ] `docs/CASE_STUDY.md`: the problem, measured before and after, the decisions (with ADR links), and the trade-offs.
- [ ] **Update the visual explainer** (`docs/visual/agent-flow.html`, see `docs/visual/README.md`):
  - built steps lose their "Proposed" tag and the "not built yet" wording;
  - illustrative numbers are replaced with measured ones;
  - file references are checked against the code;
  - republish to the same artifact URL.
- [ ] Portfolio: list the sentences in `../Portfolio-main/preview.html` that need new numbers. The user edits the portfolio.
- [ ] Clean the root folder (`pytest-cache-files-*`, `tat.txt`, `test.db`). Ask before deleting anything.
- [ ] Fill in Results, mark the project Done, and run `/handoff`.

## Acceptance criteria
Every item in the ROADMAP's definition of done, measured and recorded here.

## Results
_Fill in during the phase._
