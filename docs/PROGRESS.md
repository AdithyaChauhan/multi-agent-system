# Progress log

Newest first. `/handoff` adds an entry at the end of every session. Keep entries short; details go in the phase plan's Results section.

<!-- Entry template:
## YYYY-MM-DD · Phase N · one-line summary
- **Done:**
- **Measured:** (numbers, with model, number of runs and database)
- **Decisions:** (ADR links)
- **Open questions:**
- **Next:**
- **Commits:**
-->

## 2026-11-23 · Phase 5 · Demo shoppers, product Q&A tool loop, deploy setup, showcase README
- **Done:**
  - one-click demo shoppers (own orders, per-IP limit, purge after 2 days);
  - product Q&A as a read-only ToolNode loop (ADR 0016), with `names_a_search` so brand, budget or product words still search;
  - Groq `output_parse_failed` is retried (it had caused a 500);
  - Render + Neon single-service deploy files, keep-warm workflow, live-database load script;
  - the Kubernetes CI job moved to GitHub-hosted runners;
  - README rewritten as a showcase, `docs/SETUP.md`, regenerated graph diagram;
  - root cleanup.
- **Measured** (gpt-oss-20b, 1 run, `multi_agent_baseline`):
  - final run 1: 48/51 (it first showed 45/51 and caught the Q&A routing regression; fixed);
  - Q&A 6/6; adversarial 14/15 (all safety cases pass; a12 routing reported);
  - product turn median 2.5 s; Q&A turn 2.4 s;
  - 350 tests;
  - about 257K tokens across two keys.
- **Decisions:** [0016](decisions/0016-product-qa-and-demo-shoppers.md).
- **Open questions:** none for the user until go-live (Neon, Discord, Render accounts; permission to push).
- **Next:** final runs 2 and 3, the load test, the case study, the visual explainer, Grafana, then go live together.
- **Commits:** `85e47c4`, `fc9986a` and the handoff on `phase-5-ship`.

## 2026-11-23 · Phase 4 · Demo never breaks: fallback, limits, safety floor, CI eval gate
- **Done:**
  - model fallback chain with cooldowns, and a "busy" reply instead of a 500;
  - answer cache; 20 turns a minute and 150 a day per user;
  - the safety floor pattern (0008);
  - the catalog checks unclear and empty extractions;
  - the requested type is shown after widening (p19); the "table" alias migration;
  - PII redaction in logs and traces;
  - fixed `X-User-ID` impersonation and the open demo login;
  - 15 adversarial conversations;
  - CI `replay-evals` job (scrubbed 668 KB fixture, `ci_replay.sh`, `ci_gate.py`) replacing the dead self-hosted job;
  - `alembic` added to the requirements.
- **Measured** (gpt-oss-20b, 1 run, `multi_agent_baseline`):
  - adversarial 15/15;
  - baseline 48/51 (from 47);
  - retrieval, all 100 queries, ranker off: recall@5 0.979, precision@3 0.933, refusals 1.0;
  - CI simulated in `python:3.12-slim`: identical numbers, 0 cassette misses;
  - a live retired-model check answered through gpt-oss-20b;
  - 338 tests, coverage 89%;
  - about 25K tokens.
- **Decisions:** [0015](decisions/0015-demo-never-breaks.md).
- **Open questions:**
  - p03 "table" (left, see 0015);
  - limits and cache are per process;
  - the CI job runs on GitHub after the next push.
- **Next:** new chat, `/resume`, plan Phase 5.
- **Commits:** this phase's commits on `phase-4-reliability`.

## 2026-11-23 · Phase 3 · Hybrid search and product cards done; roadmap reset for judges
- **Done:**
  - roadmap reset around what a judge sees (0013);
  - pgvector on an Alpine Postgres image (the volume was kept; both databases backed up to `%TEMP%`);
  - migration `b5e1f0a3c2d4`;
  - local embeddings (`fastembed`, bge-small) from the products' own words;
  - `app/search/hybrid.py` (vector + full text + type, weighted RRF);
  - the catalog checks meaning before "we don't carry";
  - the relax loop waits for the requested type;
  - product cards with photos;
  - `PRODUCT_RANKER=off`, a cassette `fill` mode, `eval/query_split.json` and `eval/run_split.py`;
  - `.dockerignore` no longer lets `.env.eval` into local images.
- **Measured** (v3b split, 1 run):
  - test half 47 queries: recall@5 0.933 → 1.0, precision@3 0.900 → 0.930, vague 0.6 → 1.0, refusals 1.0;
  - renamed 35 queries: recall drop 11.8 → 0 points, precision@3 0.843 against 0.941;
  - baseline 47/51 (gpt-oss-20b, same 4 failures);
  - about 120K tokens in total;
  - app memory about 315 MB, image 1.18 → 1.49 GB, search about 90 ms;
  - 286 tests, coverage 89%.
- **Decisions:** [0013](decisions/0013-judge-facing-priorities.md), [0014](decisions/0014-hybrid-search-design.md).
- **Open questions:**
  - the router routes "fuzz balls on sweaters" to clarify;
  - renamed-catalog precision;
  - a burst of Groq 500s during the baseline (Phase 4's fallback chain).
- **Next:** new chat, `/resume`, plan Phase 4.
- **Commits:** `1284bf7` (gate), `7b57a02` (roadmap reset), and this phase's code and eval commits on `phase-3-hybrid-search`.

## 2026-11-23 · Phase 3 · Gate says go: renamed catalog drops recall@5 by 11.8 points
- **Done:**
  - fixed `scripts/make_renamed_catalog_db.py`, which now also renames `product_types` (search reads those since Phase 1), and added a unit test;
  - created `multi_agent_renamed`;
  - ran the 35-query robustness sample on it.
- **Measured** (35 queries, v3b model split: 25 on 20b, 6 on 120b, 4 on qwen; 1 live run, about 83K tokens): recall@5 0.971 → 0.853 renamed, precision@3 0.941 → 0.833, refusals 1.0 on both.
  - The misses are shopper words that existed only as our type names.
  - Hinglish and vague misses trace to ranking, labels and data, not meaning (except q061).
- **Decisions:** none yet. The embedding-source ADR comes with the build plan.
- **Open questions:** whether full text alone, without embeddings, closes the gap (measure it first, because it's cheaper).
- **Next:** plan the Phase 3 build and get approval.
- **Commits:** the gate commit on `phase-3-hybrid-search`.

## 2026-11-21 · Phase 2 · LangGraph-native architecture done
- **Done:**
  - Postgres checkpointer (one thread per session); cancel through `interrupt()` with `/cancel-order` removed; search loop as graph edges; per-agent input and output schemas; escalation subgraph (ticket, then webhook or log alert);
  - `/chat/stream` step labels; patch extraction with filter chips (removing one costs no tokens); product grounding in code; diagram in `docs/architecture/graph.md`;
  - the baseline ported to Phase 1 types, with record/replay;
  - bug fixed: an unreachable database at startup left the app without its catalog until a restart.
- **Measured** (gpt-oss-20b, 1 run, `multi_agent_baseline`):
  - baseline 45 → 47/51;
  - retrieval (100 queries, v2 model split): recall@5 0.958 → 0.947, precision@3 0.926 → 0.918, refusals 0.8 → 1.0;
  - steps 2–6 replay identical at 0 tokens;
  - prompts 66 → 68 lines; agent code 858 → 1,284 lines (both size criteria missed);
  - 262 tests, coverage 92%.
- **Decisions:** [0012](decisions/0012-phase-2-graph-contracts.md).
- **Open questions:** the Phase 3 gate (renamed-catalog sample, about 70K tokens); the Phase 0 label review.
- **Next:** new chat, `/resume`, plan Phase 3 starting with its gate.
- **Commits:** `404a865` (Phase 1) through this handoff on `phase-2-architecture`.

## 2026-11-19 · Phase 1 · Typed catalog live; search targets met; phase closed
- **Done:**
  - 47 product types and brand merges in `data/catalog/*.yaml`, plus migration `a7d4e2c9b1f0`;
  - `scripts/enrich_catalog.py` (regex, classify, attributes, review, apply). All 1,350 products are typed, titled and branded, with 99.3% of served products fully attributed, on both databases. `multi_agent_db` was backed up first, to `%TEMP%`;
  - search runs on types, attributes and brand aliases, and the catalog constants and the prompt list are gone;
  - 221 tests pass, coverage 91%, lint clean.
- **Measured:** v2 against v1 on 100 queries, with the same model per query, 1 run, `multi_agent_baseline`. Recall@5 0.874 → 0.958, precision@3 0.870 → 0.926, empty rate 9.5% → 0%, attribute 0.75 → 1.0, Hinglish 0.60 → 0.80. Enrichment cost about 350K tokens.
- **Decisions:** [0011](decisions/0011-catalog-words-resolved-in-code.md).
- **Open questions:**
  - the user skipped their 50-product spot check; Claude's check found 6 of 50 wrong, all fixed;
  - the Phase 0 label review is still pending;
  - Phase 3 go/no-go: Hinglish and vague are at 0.80, and the renamed catalog is unmeasured.
- **Next:** commit `phase-1-catalog`, then in a new chat run `/resume` and plan Phase 2.
- **Commits:** none yet; everything is uncommitted on `phase-1-catalog`.

## 2026-11-18 · Phase 0 · Baseline complete (100/100); phase closed
- **Done:** ran q088–q100 on gpt-oss-20b using a second Groq key (`.env.eval`, git-ignored, never printed). Replaying all three parts matched exactly at 0 tokens. Phase 0 closed, except the label review.
- **Measured:** recall@5 0.874, precision@3 0.870, MRR 0.837, empty rate 9.5%. Follow-ups 0.93, attribute 0.75, Hinglish 0.60, plain and typo 1.00.
- **Decisions:** none.
- **Open questions:** the user's label review.
- **Next:** new chat, `/resume`, plan Phase 1 (the type list and attribute schemas need the user's review before extraction).
- **Commits:** this handoff.

## 2026-11-18 · Phase 0 · 87/100 measured; re-planned around prompts and architecture
- **Done:**
  - v1 baseline on 87 of 100 queries (gpt-oss-20b, then gpt-oss-120b, then qwen, each until its daily cap);
  - combined summary in `eval/retrieval_runs/v1-combined-summary.json`;
  - re-plan: new Phase 2 is LangGraph-native architecture, hybrid search becomes conditional Phase 3; ADRs 0009 and 0010.
- **Measured:** recall@5 0.854, precision@3 0.866, empty rate 11%. Attribute 0.65, Hinglish 0.60, plain and typo 1.00. Wrong "we don't carry" replies for fitness tracker, laptop stand and geyser.
- **Decisions:** [0009](decisions/0009-langgraph-primitives.md), [0010](decisions/0010-prompt-budget.md).
- **Open questions:** label review by the user; whether qwen's generic "What are you looking for?" replies are tool-call failures.
- **Next:** in a **new chat**, `/resume`: run q088–q100, replay once, close Phase 0, then plan Phase 1.
- **Commits:** `6c65da3` (re-plan), plus this handoff.

## 2026-11-18 · Phase 0 · Measuring stick built; first numbers
- **Done:**
  - LLM record/replay in `app/core/llm.py`;
  - 100 labelled queries (`eval/product_queries.json`) and the labelling tool `eval/label_queries.py`;
  - `eval/run_retrieval.py` with `--resume`, `--rescore` and `--token-budget`, plus `eval/retrieval_metrics.py`;
  - `scripts/make_renamed_catalog_db.py`;
  - 20 new tests. 195 pass in total, coverage 90%, lint clean.
- **Measured:** v1 recall@5 0.885 and precision@3 0.897 on q001–q052 (gpt-oss-20b, 1 run). Attribute queries: 0.62. Renamed catalog: recall@5 0.97 → 0.00 (35-query sample, gpt-oss-120b). Details are in the phase 0 plan's Results.
- **Decisions:** none new. The renamed-catalog result is the evidence for 0005 and 0006.
- **Open questions:** the user should review the labels (`reviewed: false`). A CI replay step needs Postgres in CI.
- **Next:** finish q053–q100 with `--resume` after the gpt-oss-20b daily cap resets, replay once, then close Phase 0.
- **Commits:** see `git log` on `phase-0-evals`.

## 2026-11-18 · Planning · Roadmap, decisions and session workflow
- **Done:** finished the `simplify-agents` branch (15 commits, see `SIMPLIFY_REPORT.md`). Reviewed the architecture, audited the product table, and wrote `ROADMAP.md`, phase plans 0–5, ADRs 0001–0008 and the `/resume` and `/handoff` skills. Saved the 3D explainer to `docs/visual/`.
- **Measured:** 43/51 baseline conversations after simplification (gpt-oss-20b/120b, 1 run, `multi_agent_baseline`). Product table: 1,350 rows; `attributes` empty on all of them; `type` null on 977 (72%); 91 subcategories, 29 of them with 3 or fewer items; names average 127 characters.
- **Decisions:** [0001](decisions/0001-keep-router-and-agents.md) to [0008](decisions/0008-safety-floor.md).
- **Open questions:** Embeddings from an API or a local model (decide at Phase 2 start)? Keep Helm or Render (Phase 5)? Does the capstone brief still require a ToolNode per agent (see 0002)?
- **Next:** Phase 0 in a new chat: `/resume`.
- **Commits:** none; these planning files aren't committed yet.
