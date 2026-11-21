# Roadmap

**Goal:** take the assistant from about 5.8/10 to 9/10. That means short prompts, a clean LangGraph architecture that shows how agents are built (subgraphs, loops, a human-in-the-loop pause, ticket handoff), measured quality, and escalations that reach a real person. The work is split into phases, and each phase is worth keeping even if work stops after it.

## Now
- **Current phase:** Phase 3, Hybrid search (conditional; not started). Phases 0, 1 and 2 are done.
- **Branch:** `phase-2-architecture` holds Phase 2 (committed, not pushed). Phase 3 branches off it if the gate says go.
- **Next action:** in a new chat, run `/resume` and plan Phase 3, starting with its go/no-go gate.
  - The gate needs the renamed-catalog sample on v3b (about 70K tokens).
  - Hinglish (0.80) and vague (0.70) are already below the 0.85 bar, on small samples.
  - Also open: the p03 "table" data fix, p19 "usb hub with ethernet", and s16 routing.
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
| 3 | Hybrid search (conditional) | Not started | [plan](docs/plans/phase-3-hybrid-search.md) | Only if Phase 1 leaves a gap; must beat v1 on Phase 0 metrics |
| 4 | Reliability and safety | Not started | [plan](docs/plans/phase-4-reliability-and-safety.md) | Friendly quota message, fallback model, safety floor, 0 injection failures |
| 5 | Ship and showcase | Not started | [plan](docs/plans/phase-5-ship-and-showcase.md) | Admin tickets, auth review, dashboards, load test, case study, updated visual |

Statuses: Not started, In progress, Done, Dropped (say why in the plan). The order changed on 2026-11-18 to match the user's goals (see 0009 and 0010).

## Scorecard
Judged on 2026-11-18; updated 2026-11-19 after Phase 1 and 2026-11-21 after Phase 2 (`phase-2-architecture`) for the measured rows. Change the Today column only with measured evidence.

| Aspect | Before (`c8a0fa6`) | Today | Target | Moved by phase |
|---|---|---|---|---|
| Architecture clarity | 4 | 8.5 | 9 | 1, 2 |
| Product search correctness | 4 | 8 | 9 | 0, 1, 3 |
| Follow-up turns | 4 | 7.5 | 9 | 2 |
| Robustness to catalog changes | 3 | 3.5 | 9 | 1, 3 |
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
- Hybrid search (pgvector + full-text) only if Phase 1 leaves a gap, and behind a flag until it wins. (0006)
- Safety escalates if the model flags it or a narrow pattern matches. (0008)

## Out of scope
- Replacing LangGraph, a separate vector database, or one autonomous tool-calling agent (0001).
- More agents, a supervisor agent, or model-driven tool calling for deterministic flows like orders and cancellation (0009).
- Selling phones, laptops or tablets. They stay in the database with `served = false`.
