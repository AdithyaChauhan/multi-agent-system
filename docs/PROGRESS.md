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
