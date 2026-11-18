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

## 2026-11-18 · Planning · Roadmap, decisions and session workflow
- **Done:** finished the `simplify-agents` branch (15 commits, see `SIMPLIFY_REPORT.md`). Reviewed the architecture, audited the product table, and wrote `ROADMAP.md`, phase plans 0–5, ADRs 0001–0008 and the `/resume` and `/handoff` skills. Saved the 3D explainer to `docs/visual/`.
- **Measured:** 43/51 baseline conversations after simplification (gpt-oss-20b/120b, 1 run, `multi_agent_baseline`). Product table: 1,350 rows; `attributes` empty on all of them; `type` null on 977 (72%); 91 subcategories, 29 of them with 3 or fewer items; names average 127 characters.
- **Decisions:** [0001](decisions/0001-keep-router-and-agents.md) to [0008](decisions/0008-safety-floor.md).
- **Open questions:** Embeddings from an API or a local model (decide at Phase 2 start)? Keep Helm or Render (Phase 5)? Does the capstone brief still require a ToolNode per agent (see 0002)?
- **Next:** Phase 0 in a new chat: `/resume`.
- **Commits:** none; these planning files aren't committed yet.
