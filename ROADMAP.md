# Roadmap

**Goal:** take the assistant from about 5.8/10 to 9/10. That means short prompts, a clean LangGraph architecture that shows how agents are built (subgraphs, loops, a human-in-the-loop pause, ticket handoff), measured quality, and escalations that reach a real person. The work is split into phases, and each phase is worth keeping even if work stops after it.

## Now
- **Current phase:** Phase 3, Hybrid search: in progress. Its gate said **go** on 2026-11-23. Phases 0, 1 and 2 are done.
- **Branch:** `phase-3-hybrid-search`, off `phase-2-architecture`. Nothing is pushed.
- **Gate result:** renaming the catalog's type names drops recall@5 from 0.971 to **0.853** (35 queries, v3b model split, 1 run). The bar is a drop of less than 5 points.
  - Every new miss is a shopper word that was only our type name ("lint remover", "mixer grinder", "mouse").
  - The product titles still contain those words.
- **Roadmap reset (2026-11-23, [0013](docs/decisions/0013-judge-facing-priorities.md)):** the remaining phases are now ordered by what a judge sees: search and product cards (3), a demo that never breaks (4), then a live link that stays up with a one-click demo and a showcase README (5).
- **Next action:** build Phase 3 (pgvector + full-text + rank fusion, local embeddings, product cards), as in its plan.
  - Also open: the p03 "table" data fix, p19 "usb hub with ethernet", s16 routing, "sasta" → sort by price (q071), and the fitness-band data (q062).
- **Phase 2 result:**
  - 51-conversation baseline: 45 → **47/51** (gpt-oss-20b, 1 run, `multi_agent_baseline`).
  - Product search (100 queries, v2 model split): recall@5 **0.947**, precision@3 0.918 (v2: 0.958, 0.926), out-of-scope refusals 0.8 → **1.0**.
  - The conversation state survives a restart; cancel is an `interrupt()` pause; filters show as chips; replies stream step labels.
- **Still open:** the user's review of the Phase 0 labels; the user skipped the 50-product spot check.
- **Blocked on:** nothing.

## Phases
| # | Phase | Status | Plan | Exit criteria (short) |
|---|---|---|---|---|
| 0 | Measuring stick | Done (labels await review) | [plan](docs/plans/phase-0-measuring-stick.md) | 100 labelled product queries; today's recall@5 measured; LLM replay mode |
| 1 | Clean product data | Done | [plan](docs/plans/phase-1-clean-product-data.md) | Every product typed, key attributes filled, catalog constants removed |
| 2 | LangGraph-native architecture | Done (2 size criteria missed) | [plan](docs/plans/phase-2-langgraph-architecture.md) | Checkpointer, `interrupt()` for cancel, search loop as graph edges, subgraph schemas, streaming, escalation subgraph, filter chips |
| 3 | Hybrid search and product cards | In progress (gate: go) | [plan](docs/plans/phase-3-hybrid-search.md) | Renamed-catalog drop < 5 points, no metric drops, refusals 1.0, cards with images |
| 4 | Demo never breaks | Not started | [plan](docs/plans/phase-4-reliability-and-safety.md) | Model fallback chain, busy message, search cache, 0 adversarial failures, replay evals in CI |
| 5 | Ship and showcase | Not started | [plan](docs/plans/phase-5-ship-and-showcase.md) | Live link that stays up, one-click demo shopper, showcase README, case study, final scorecard |

Statuses: Not started, In progress, Done, Dropped (say why in the plan). The order changed on 2026-11-18 to match the user's goals (see 0009 and 0010), and again on 2026-11-23 to put what a judge sees first (0013).

## Scorecard
Judged on 2026-11-18; updated 2026-11-19 after Phase 1, 2026-11-21 after Phase 2 (`phase-2-architecture`) and 2026-11-23 after the Phase 3 gate (robustness: renamed drop measured at 11.8 points, against 97 in Phase 0) for the measured rows. Change the Today column only with measured evidence.

| Aspect | Before (`c8a0fa6`) | Today | Target | Moved by phase |
|---|---|---|---|---|
| Architecture clarity | 4 | 8.5 | 9 | 1, 2 |
| Product search correctness | 4 | 8 | 9 | 0, 1, 3 |
| Follow-up turns | 4 | 7.5 | 9 | 2 |
| Robustness to catalog changes | 3 | 5 | 9 | 1, 3 |
| Guardrails and safety | 5 | 8 | 9.5 | 2, 4 |
| State and scaling | 3 | 6 | 9 | 2, 5 |
| Cost and latency | 4 | 6 | 9 | 1, 4 |
| Evaluation rigor | 4 | 7 | 9 | 0, 4 |
| Maintainability | 3.5 | 7 | 9 | 1, 2 |
| Ops and deploy | 5 | 6 | 9 | 5 |
| Portfolio signal | 5 | 7.5 | 9.5 | 2, 5 |
| **Overall** | **~4.2** | **~6.8** | **9** | |

## Definition of done (the 9 bar)
- Recall@5 ≥ 0.9 and precision@3 ≥ 0.85 on the labelled product queries, and recall drops by less than 5 points when category names are renamed.
- At least 47 of 51 baseline conversations pass, averaged over 3 runs on the production model.
- 0 failures on the prompt-injection and cross-user test set.
- p95 latency under 3 s and under 1% errors in a 20-user load test, including while Groq is rate-limiting.
- A safety report reaches a human channel within one minute.
- Every prompt is under 40 lines (0010), and the graph diagram shows the subgraphs, the loop and the pause (0009).
- The case study and the visual explainer show measured numbers.
- A judge can try a search, an order lookup and a cancel from the README's live link within 2 minutes, without creating an account (0013).
- Product replies show cards with image, price and rating.

A 10 would need real users: today the data is synthetic and there's no production traffic or A/B evidence.

## Principles
Details and the reasoning are in [docs/decisions/](docs/decisions/README.md).
- Keep the router and three agents; rebuild only the product layer. (0001)
- Guardrails live in Python, never in prompts or model tools. (0002)
- Prompts live in `app/prompts/`; nothing is pulled from a hub at runtime. (0003)
- Fix behaviour in data, code or tests, never with one-off prompt rules; every prompt stays under 40 lines. (0010)
- Measure before and after every change. (0004)
- Facts about products live in the database as typed attributes, not in prompt lists or Python constants. (0005)
- Use LangGraph's built-in features (checkpointer, `interrupt()`, graph loops, subgraph schemas, streaming) only where they replace hand-written code. (0009)
- The model returns only what changed in a search; code merges it, and active filters appear as chips. (0007, stored via 0009)
- Hybrid search (pgvector + full-text, fused) behind a flag until it wins; the Phase 3 gate showed the gap. (0006)
- Order the work by what a judge sees: a live demo that never breaks and needs no sign-up comes before internal polish. (0013)
- Safety escalates if the model flags it or a narrow pattern matches. (0008)

## Out of scope
- Replacing LangGraph, a separate vector database, or one autonomous tool-calling agent (0001).
- More agents, a supervisor agent, or model-driven tool calling for deterministic flows like orders and cancellation (0009).
- Selling phones, laptops or tablets. They stay in the database with `served = false`.
