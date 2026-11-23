# Phase 5: Ship and showcase
- **Status:** In progress (started 2026-11-23)
- **Branch:** `phase-5-ship`, off `phase-4-reliability`
- **Decisions:** [0013](../decisions/0013-judge-facing-priorities.md), [0016](../decisions/0016-product-qa-and-demo-shoppers.md)
- **The user's choices (2026-11-23):**
  - free hosting kept awake (Render + Neon);
  - safety alerts to a Discord channel;
  - LangGraph tool calling only for safe, read-only lookups.

## Goal
Meet the definition of done in `ROADMAP.md`. A judge opens the README, clicks a live link that works, tries every flow without an account, and sees measured numbers.

## Tasks
- [x] **One-click demo shopper:** `POST /auth/demo-shopper`, five orders each, 5 per IP per hour, purged after 2 days. The login page button and the chat's "things to try".
- [x] **Product Q&A:** a read-only ToolNode loop (`app/agents/product_qa.py`), the router's `about_shown`, and `names_a_search` so brands, budgets and new product words still search. Tool record and replay in `call_llm`.
- [x] **Robustness found on the way:** Groq `output_parse_failed` is retried instead of returning a 500, and a malformed tool call answers without tools.
- [x] **Deploy setup:**
  - `render.yaml` (one free service plus Neon);
  - mock carrier at `/carrier`;
  - migrations at start;
  - `keep-warm.yml` and `scripts/load_live_db.sh`;
  - the Kubernetes CI job on GitHub-hosted runners.
- [x] **Docs:** `docs/SETUP.md`, the README showcase, ADR 0016, and the regenerated graph diagram.
- [x] **Root cleanup:** 8 files removed, 11 cache folders deleted, history reports moved to `docs/history/`.
- [x] **Final run 1** (51 conversations, gpt-oss-20b): 48/51. The Q&A set 6/6; adversarial 14/15 (a12 is routing, reported).
- [ ] **Final runs 2 and 3:** live, `--mode live`, about 196K tokens each. One per key per day: `--env-file .env.eval` for one of them.
- [ ] **Load test:** `eval/loadtest/locustfile.py`, 20 users for 3 minutes on local Docker, on a separate app container with raised limits. Report p95, error rate, cache hits and fallbacks.
- [ ] **The CI simulation passes** with the new cassettes (run on 2026-11-23, see Results).
- [ ] `docs/CASE_STUDY.md`.
- [ ] **Visual explainer:** built steps lose "Proposed", add the tool loop and hybrid search, measured numbers, republish to the same URL (see `docs/visual/README.md`).
- [ ] **Grafana panels:** fallback, cache hits, limits, latency.
- [ ] **Go live with the user** (step 7 of the plan): push after asking, PR to `main`, CI green, merge; the user creates Neon, Discord and Render and pastes the secrets; `bash scripts/load_live_db.sh`; check the live link end to end; time the Discord alert.
- [ ] Final scorecard in the ROADMAP; Results; `/handoff`.

## Acceptance criteria
- The live link works, and search, an order and a cancel can be tried within 2 minutes without an account.
- Baseline ≥ 47/51 averaged over 3 live runs; 0 failures on the adversarial safety cases; the Q&A set passes.
- p95 under 3 s and under 1% errors in the 20-user load test.
- A safety report reaches Discord within 1 minute.
- Prompts under 40 lines (router 27, Q&A 6); the graph diagram shows the subgraphs, the loop, the pause and the tool loop.
- The case study and the visual explainer show measured numbers.

## Results (so far)
- **Live response times** (gpt-oss-20b, 2026-11-23):
  - product search turn: median 2.5 s;
  - question about shown products: median 2.4 s;
  - about 0.8 s per model call;
  - repeated questions are answered from the cache in under 0.1 s.
- **Final run 1 caught a regression.** It first scored 45/51: the router flagged "what about Bajaj" and "philps air purifier" as questions about the cards. `names_a_search` fixed it, and the run, re-scored in fill mode at 0 extra tokens, is **48/51**. The failures are the same as Phase 4: p03, p10 and s16.
- **Q&A set: 6/6.** In a live check the model used `compare_products` and `get_product_details`, and said "the facts don't mention a warranty" rather than guessing.
- **Data error seen through Q&A:** a heater titled 2000 W carries `watts: 1000`.
- **Tokens on 2026-11-23:** about 196K (run 1, `.env.eval` key), plus about 36K (Q&A), plus about 25K (adversarial).
