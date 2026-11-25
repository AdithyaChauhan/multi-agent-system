# Roadmap

**Goal:** take the assistant from about 5.8/10 to 9/10. That means short prompts, a clean LangGraph architecture that shows how agents are built (subgraphs, loops, a human-in-the-loop pause, ticket handoff), measured quality, and escalations that reach a real person. The work is split into phases, and each phase is worth keeping even if work stops after it.

## Now
- **Current phase:** Phase 5, Ship and showcase: in progress. Phases 0–4 are done.
- **Live:** https://multi-agent-chatbot-58ur.onrender.com (Render free, Neon free, Singapore). `main` is the live site: Render deploys every push to it, so change it only through a PR with green CI ([0019](docs/decisions/0019-main-is-live.md)).
- **Branch:** `main` (`phase-5-ship` merged as PR #3, the Neon fix as PR #4, honest replies as PR #6); new work goes on short branches with a PR each.
- **Phase 5 so far:**
  - one-click demo shoppers;
  - product Q&A through a read-only ToolNode loop;
  - **live** on Render + Neon: the judge path (demo shopper → search → question → order → cancel) takes 10 s; safety alerts reach Discord;
  - CI green on GitHub's runners, publishing the image from `main`; replays depend on nothing machine-specific ([0018](docs/decisions/0018-machine-independent-replays.md));
  - showcase README, `docs/SETUP.md`, the case study draft, Grafana panels;
  - replies claim only what code checked ([0020](docs/decisions/0020-replies-claim-only-what-code-checked.md)): the false "don't match" header the user found live is gone, and the evals now fail such claims;
  - final run 3, the first live run of the fixed code: **48/51**, 0 false claims (runs 1 and 2 of the old code: 48/51 then, 38/51 re-scored; not counted); Q&A 6/6; adversarial safety cases 14/14;
  - 20-user load test: p95 **1.3 s**, 0 of 377 errors, 14% real answers;
  - the visual explainer rebuilt from the code (version 3);
  - five bugs found by the release checks, all fixed (`functions.` tool names, SDK retry sleeps, a rejected key's 500, an unreachable Groq scored as a run, Neon's closed connections);
  - the free tier's ceiling, reported rather than bought: about 5 product turns a minute ([0017](docs/decisions/0017-free-tier-capacity.md)).
- **Phase 4 result** ([0015](docs/decisions/0015-demo-never-breaks.md)):
  - a model fallback chain (a retired model still answers, live-checked); a "busy" reply instead of a 500;
  - an answer cache and per-user limits;
  - the safety floor;
  - adversarial set **15/15**; baseline **48/51**;
  - CI now replays every eval at 0 tokens and gates the build (simulated in a Linux container);
  - fixed two identity holes (`X-User-ID` impersonation, open demo login).
- **Phase 3 result** (hybrid search and product cards, [0014](docs/decisions/0014-hybrid-search-design.md)):
  - test half (47 queries, v3b split, 1 run): recall@5 0.933 → **1.0**, precision@3 0.900 → 0.930, vague 0.6 → 1.0, refusals 1.0;
  - renamed catalog: recall drop 11.8 → **0** points (precision@3 is still 10 points lower);
  - 51 conversations **47/51** (no regressions);
  - app memory about 315 MB, search about 90 ms;
  - product replies show cards with photos.
- **Roadmap reset (2026-11-23, [0013](docs/decisions/0013-judge-facing-priorities.md)):** the remaining phases are ordered by what a judge sees: a demo that never breaks (4), then a live link that stays up with a one-click demo and a showcase README (5).
- **Next action:** new chat, `/resume`, then finish Phase 5 (see its plan):
  - final runs 4 and 5 of the fixed code on 2026-11-26 after 05:30 IST (the quota's daily reset), one per key, about 196K tokens each;
  - the 3-run average into the case study, the plan and the explainer's last screen;
  - the final scorecard, then mark Phase 5 done.
- **For the user:** merge this handoff's PR; can the local branch `backup/phase-5-ship-before-rewrite` be deleted?
- **Still open:** the user's review of the Phase 0 labels; the user skipped the 50-product spot check.
- **Blocked on:** nothing (only quota timing).

## Phases
| # | Phase | Status | Plan | Exit criteria (short) |
|---|---|---|---|---|
| 0 | Measuring stick | Done (labels await review) | [plan](docs/plans/phase-0-measuring-stick.md) | 100 labelled product queries; today's recall@5 measured; LLM replay mode |
| 1 | Clean product data | Done | [plan](docs/plans/phase-1-clean-product-data.md) | Every product typed, key attributes filled, catalog constants removed |
| 2 | LangGraph-native architecture | Done (2 size criteria missed) | [plan](docs/plans/phase-2-langgraph-architecture.md) | Checkpointer, `interrupt()` for cancel, search loop as graph edges, subgraph schemas, streaming, escalation subgraph, filter chips |
| 3 | Hybrid search and product cards | Done | [plan](docs/plans/phase-3-hybrid-search.md) | Renamed-catalog drop < 5 points, no metric drops, refusals 1.0, cards with images |
| 4 | Demo never breaks | Done | [plan](docs/plans/phase-4-reliability-and-safety.md) | Model fallback chain, busy message, search cache, 0 adversarial failures, replay evals in CI |
| 5 | Ship and showcase | In progress | [plan](docs/plans/phase-5-ship-and-showcase.md) | Live link that stays up, one-click demo shopper, showcase README, case study, final scorecard |

Statuses: Not started, In progress, Done, Dropped (say why in the plan). The order changed on 2026-11-18 to match the user's goals (see 0009 and 0010), and again on 2026-11-23 to put what a judge sees first (0013).

## Scorecard
Judged on 2026-11-18; updated 2026-11-19 after Phase 1, 2026-11-21 after Phase 2 (`phase-2-architecture`) and 2026-11-23 after Phases 3 and 4 (hybrid search; renamed recall drop 0 points; adversarial 15/15; CI eval gate; fallback chain) and 2026-11-25 after going live (the live judge path; a Discord safety alert delivered; impersonation blocked on the live site; CI green on GitHub's runners, 5 runs in a row, with machine-independent replays) for the measured rows. Change the Today column only with measured evidence.

| Aspect | Before (`e0bdf3c`) | Today | Target | Moved by phase |
|---|---|---|---|---|
| Architecture clarity | 4 | 8.5 | 9 | 1, 2 |
| Product search correctness | 4 | 9 | 9 | 0, 1, 3 |
| Follow-up turns | 4 | 7.5 | 9 | 2 |
| Robustness to catalog changes | 3 | 8 | 9 | 1, 3 |
| Guardrails and safety | 5 | 9.5 | 9.5 | 2, 4, 5 |
| State and scaling | 3 | 6 | 9 | 2, 5 |
| Cost and latency | 4 | 7 | 9 | 1, 4 |
| Evaluation rigor | 4 | 9 | 9 | 0, 3, 4, 5 |
| Maintainability | 3.5 | 7 | 9 | 1, 2 |
| Ops and deploy | 5 | 8 | 9 | 4, 5 |
| Portfolio signal | 5 | 8.5 | 9.5 | 2, 3, 5 |
| **Overall** | **~4.2** | **~8.0** | **9** | |

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
- Hybrid search: pgvector + full text + the product type, fused by rank; local embeddings from the products' own words. (0006, 0014)
- Order the work by what a judge sees: a live demo that never breaks and needs no sign-up comes before internal polish. (0013)
- Safety escalates if the model flags it or a narrow pattern matches. (0008)
- A reply claims only what code checked, and the evals check the claims. (0020)

## Out of scope
- Replacing LangGraph, a separate vector database, or one autonomous tool-calling agent (0001).
- More agents, a supervisor agent, or model-driven tool calling for deterministic flows like orders and cancellation (0009).
- Selling phones, laptops or tablets. They stay in the database with `served = false`.
