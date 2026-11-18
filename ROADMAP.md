# Roadmap

**Goal:** take the assistant from about 5.8/10 to 9/10: measured quality, holds up when things fail, and escalations reach a real person. The work is split into phases, and each phase is worth keeping even if work stops after it.

## Now
- **Current phase:** Phase 0, Measuring stick (not started)
- **Branch:** `simplify-agents`. Start each phase on its own branch, e.g. `phase-0-evals`.
- **Next action:** in a new chat, run `/resume`, refine `docs/plans/phase-0-measuring-stick.md` in plan mode, then build the labelled query set.
- **Blocked on:** nothing.

## Phases
| # | Phase | Status | Plan | Exit criteria (short) |
|---|---|---|---|---|
| 0 | Measuring stick | Not started | [plan](docs/plans/phase-0-measuring-stick.md) | 100 labelled product queries; today's recall@5 measured; LLM replay mode |
| 1 | Clean product data | Not started | [plan](docs/plans/phase-1-clean-product-data.md) | Every product typed, key attributes filled, catalog constants removed |
| 2 | Search v2 | Not started | [plan](docs/plans/phase-2-search-v2.md) | Query rewrite + hybrid search beats v1 on Phase 0 metrics |
| 3 | State and filter chips | Not started | [plan](docs/plans/phase-3-state-and-filter-chips.md) | Search state in Postgres; active filters visible and removable in chat |
| 4 | Reliability and safety | Not started | [plan](docs/plans/phase-4-reliability-and-safety.md) | Friendly quota message, fallback model, safety floor, 0 injection failures |
| 5 | Ship and showcase | Not started | [plan](docs/plans/phase-5-ship-and-showcase.md) | Admin tickets, auth review, dashboards, load test, case study, updated visual |

Statuses: Not started, In progress, Done, Dropped (say why in the plan).

## Scorecard
Judged on 2026-11-18. "Today" is `simplify-agents` at `262f624`. Change the Today column only with measured evidence.

| Aspect | Before (`c8a0fa6`) | Today | Target | Moved by phase |
|---|---|---|---|---|
| Architecture clarity | 4 | 7 | 9 | 1, 2 |
| Product search correctness | 4 | 5.5 | 9 | 0, 1, 2 |
| Follow-up turns | 4 | 6 | 9 | 2, 3 |
| Robustness to catalog changes | 3 | 3.5 | 9 | 1, 2 |
| Guardrails and safety | 5 | 7.5 | 9.5 | 4 |
| State and scaling | 3 | 3 | 9 | 3, 5 |
| Cost and latency | 4 | 6 | 9 | 2, 4 |
| Evaluation rigor | 4 | 5.5 | 9 | 0, 4 |
| Maintainability | 3.5 | 7 | 9 | 1, 2 |
| Ops and deploy | 5 | 6 | 9 | 5 |
| Portfolio signal | 5 | 6.5 | 9.5 | 5 |
| **Overall** | **~4.2** | **~5.8** | **9** | |

## Definition of done (the 9 bar)
- Recall@5 ≥ 0.9 and precision@3 ≥ 0.85 on the labelled product queries, and recall drops by less than 5 points when category names are renamed.
- At least 47 of 51 baseline conversations pass, averaged over 3 runs on the production model.
- 0 failures on the prompt-injection and cross-user test set.
- p95 latency under 3 s and under 1% errors in a 20-user load test, including while Groq is rate-limiting.
- A safety report reaches a human channel within one minute.
- The case study and the visual explainer show measured numbers.

A 10 would need real users: today the data is synthetic and there's no production traffic or A/B evidence.

## Principles
Details and the reasoning are in [docs/decisions/](docs/decisions/README.md).
- Keep the router and three agents; rebuild only the product layer. (0001)
- Guardrails live in Python, never in prompts or model tools. (0002)
- Prompts live in `app/prompts/`; nothing is pulled from a hub at runtime. (0003)
- Measure before and after every change. (0004)
- Facts about products live in the database as typed attributes, not in prompt lists or Python constants. (0005)
- Hybrid search (pgvector + full-text) in the existing Postgres, behind a flag until it wins. (0006)
- Search state lives in Postgres; the model returns changes and code merges them. (0007)
- Safety escalates if the model flags it or a narrow pattern matches. (0008)

## Out of scope
- Replacing LangGraph, adding agents, a separate vector database, or one autonomous tool-calling agent (0001).
- Selling phones, laptops or tablets. They stay in the database with `served = false`.
