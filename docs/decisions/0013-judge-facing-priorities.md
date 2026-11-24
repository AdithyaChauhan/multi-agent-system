# 0013. Order the remaining work by what a judge sees
- **Status:** Accepted
- **Date:** 2026-11-23

## Context
The goal is a 9/10 capstone and portfolio project. A judge spends about five minutes on it: the README, the live demo (a vague search, a cheap product, an order, a cancel), then a skim of the architecture, tests and CI. On 2026-11-23 that path showed these gaps:
- **The live demo can fail.**
  - Render's free web service sleeps, and its free Postgres expires after 30 days.
  - Groq's free tier (200K tokens a day per model) can run out in the middle of a demo.
- **Product replies are text lists,** although all 1,350 products have an image link (`img_link`).
- **No semantic retrieval.** The Phase 3 gate measured an 11.8-point recall drop on a renamed catalog, and "fuzz balls on sweaters" is refused.
- **The evals are strong but run only by hand.** CI runs unit tests only.
- **The demo is hard to try.** The Phase 5 plan said to turn demo users off, but a judge won't create a Google account to try orders.
- **The repository root is cluttered,** and the README is mostly setup steps.

## Decision
- **Phase 3: hybrid search and product cards.**
- **Phase 4, "the demo never breaks":**
  - a fallback chain across models on a 429 (each Groq model has its own quota), then a friendly "busy" reply;
  - a per-session token budget and a cache for repeated searches;
  - the adversarial set;
  - replay evals in CI.
- **Phase 5, "ship and showcase":**
  - a host that doesn't sleep or expire;
  - a labelled one-click demo shopper with seeded orders that reset daily;
  - a README written as a showcase (live link, GIF, results, diagram), with setup moved out;
  - a clean root, the case study, the visual explainer and the final scorecard.
- **The demo account stays in production.** It owns only seeded demo orders. Every ownership check of 0002 still applies, so it can never see or cancel another user's orders.
- **Fallback happens across models, never across accounts or organisations.** The second key in `.env.eval` stays an eval-only tool.

## Consequences
- The definition of done gains two judge-facing checks: try every flow from the README link in 2 minutes without an account, and product cards.
- The two-replica demo and the full admin page move behind the live demo in priority. The checkpointer already proves sessions survive across instances.
- Phase 3's local embedding model has to fit a small free host, so its container memory is measured.

## Alternatives considered
- **Keep the old order** (search, then reliability, then ship): the demo-breaking risks would stay open until the very end.
- **Ground product words on product titles only, without embeddings:** this fixes the 4 renamed-catalog misses, but not the vague queries. It is also a heuristic a judge won't recognise. Rejected for hybrid search (0006).
