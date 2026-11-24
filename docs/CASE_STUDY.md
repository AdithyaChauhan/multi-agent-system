# Case study: rebuilding a multi-agent shopping assistant, measured

A chat assistant for an electronics store: it finds products, answers questions about them, tracks and cancels orders, and hands safety reports to a person. This is the story of taking it from a prototype that didn't start to a system with measured quality, in six phases. Each number below says how it was measured: the model, the number of runs and the database.

> **Status:** release numbers still to come. The 3-run average, the load test, the live link and the alert timing are marked _pending_ and get filled in when Phase 5 closes.

## 1. Where it started
Commit `e0bdf3c`, rated about 4.2/10. The full diagnosis is in [docs/history/DIAGNOSIS.md](history/DIAGNOSIS.md).

- **It didn't start.** A startup "migration" sent SQL that Postgres rejects, so the app crash-looped after the README's own setup steps.
- **It ran out of model quota.** A product turn sent about 3,650 tokens, mostly fixed prompt text. On Groq's free tier (200K tokens a day per model) every message failed with HTTP 500 after about 55 product turns, across all users.
- **The prompt that ran wasn't the one in git.** Two prompts were pulled from a hub at runtime, and the hub copies were older than the code.
- **Fixes fought each other.** 38 rules overrode the model, each added for one conversation, and 12 keyword lists matched the user's words ("issue" contains "sue", which read as a legal threat).
- **There was no way to tell better from worse.** Of the old test scripts, one couldn't be found and the others failed because of rate limits rather than bugs.

## 2. The approach
Three rules held across every phase. Each is written down as a decision record.

1. **Measure before and after every change** ([ADR 0004](decisions/0004-measure-before-changing.md)). Phase 0 built the measuring stick before anything was fixed: 100 labelled product queries and 51 multi-turn conversations. Model calls are recorded once and replayed for free, so a change can be measured without spending quota.
2. **Fix behaviour in data, code or tests, never with a one-off prompt rule** ([0010](decisions/0010-prompt-budget.md)). Every prompt stays under 40 lines. When the model got something wrong, the fix went into the catalog, the code or a new eval case.
3. **Guardrails live in Python** ([0002](decisions/0002-guardrails-in-python.md)). Sign-in, order ownership, cancelling and escalation are code. The model never gets a tool that acts on an order or takes a user id.

## 3. What each phase changed

| Phase | What changed | Measured result |
|---|---|---|
| Simplify (before Phase 0) | 38 steering rules → 10; 12 keyword lists → 0; agent code 2,810 → 948 lines; one prompt source (git) | 51 conversations: 37 → 43 passed. Tokens per product turn −23%. Stand-in models (gpt-oss-20b and -120b), 1 run |
| 0. Measuring stick | 100 labelled queries, the 51-conversation baseline, record and replay | Product search, all 100 queries: recall@5 0.874, precision@3 0.870. On a copy of the shop with renamed categories, recall fell to **0**: search only worked through category names |
| 1. Clean product data | An LLM typed all 1,350 products into 47 types with attributes; every flagged row was reviewed; catalog lists removed from the prompt | recall@5 0.874 → **0.958**, precision@3 0.870 → 0.926, empty results 9.5% → 0%. Same model per query, 1 run |
| 2. LangGraph architecture | Postgres checkpointer, `interrupt()` for the cancel pause, the search loop as graph edges, subgraph schemas, streaming, an escalation subgraph, filter chips | 51 conversations: 45 → **47**. A pending cancel survives an app restart |
| 3. Hybrid search and cards | pgvector + full text + product type, fused by rank; local embeddings; the catalog decides "we don't carry X"; product cards with photos | Held-out half (47 queries): recall@5 0.933 → **1.0**. Renamed shop: recall drop 11.8 → **0** points. Search about 90 ms |
| 4. Demo never breaks | Model fallback chain, a "busy" reply instead of an error page, an answer cache, per-user limits, a safety floor, CI replays every eval | Attack conversations **15/15** safe. 51 conversations **48/51**. CI gate replays everything at 0 tokens |
| 5. Ship and showcase | One-click demo shoppers, product questions through a read-only tool loop, a free single-service deploy | Final run 1: **48/51**. Product questions 6/6. Runs 2 and 3, the load test and the live link: _pending_ |

## 4. Decisions worth explaining

**The model names the product; code resolves it** ([0011](decisions/0011-catalog-words-resolved-in-code.md)). The old prompt carried the catalog's category list, and drifted whenever the catalog changed. Now the model writes what the shopper asked for in plain words, and code matches it against the catalog's own types, synonyms and brands. Renaming every category no longer breaks search.

**The model returns only what changed** ([0007](decisions/0007-search-state-in-postgres.md)). In "show me TVs", then "under 30000", then "what about Samsung", each message sends a small patch, and code merges it into the saved filters. The filters appear as chips the shopper can remove. Follow-ups stopped losing the product or the brand.

**The catalog decides "we don't carry it"** ([0014](decisions/0014-hybrid-search-design.md)). The model used to refuse things the shop sells under another name, such as "fuzz balls from my sweaters" (a lint remover). Now a refusal needs both an unknown word and no product close in meaning. On the held-out half, vague requests went from 0.6 to 1.0, and correct refusals stayed at 1.0.

**Cancelling is a pause, not a tool.** "Cancel ORD-2005" pauses the graph with `interrupt()` and shows Yes and No buttons. Only the order's owner pressing Yes resumes it, and a Python node checks the owner and the status again before anything changes. The attack set includes someone else pressing Yes on that pause.

**Tool calling only where it's safe** ([0016](decisions/0016-product-qa-and-demo-shoppers.md)). Questions about the cards on screen ("which is the most powerful?") run through a LangGraph `ToolNode` loop. Its tools only read the facts of products already shown. Orders, cancels and tickets stay deterministic.

**Quota is a design constraint** ([0015](decisions/0015-demo-never-breaks.md)). The free tier gives each model 200K tokens a day. A chain of three models with separate quotas, a 30-minute answer cache and per-user limits stretch it. When every model is out, the chat says it's busy instead of showing an error.

## 5. How quality is checked
- **Product search:** 100 labelled queries, tagged plain, typo, brand, price, attribute, vague, Hinglish, follow-up and out of scope. The settings were tuned on 53 of them and reported on the other 47.
- **Conversations:** 51 multi-turn conversations scored on routes, extracted filters, products shown and database effects, not on exact wording.
- **Attacks:** 15 conversations: prompt injection, asking for another user's order, a fake admin, and someone else pressing Yes on a cancel. Scored on what reaches the database.
- **Record and replay:** each model answer is stored with a key that includes the prompt, so replay fails loudly if a prompt changed. CI replays all of it at 0 tokens and fails the build if a number drops.
- **Unit tests:** 355, coverage 90%.

## 6. What didn't work, or isn't done
- **Three conversations still fail:**
  - "table" shows laptop tables instead of "we don't sell furniture". A tighter similarity bar would fix it, but it would also refuse "pointing device" on the renamed shop.
  - "4k monitor": the catalog has one Full HD monitor.
  - "resolve support issues" goes to support instead of asking what's wrong.
- **Precision on the renamed shop is still about 10 points lower** (0.843 against 0.941), although recall no longer drops.
- **Phase 2 missed its size targets.** Agent code grew by 50% because the phase added features (chips, alerts, the pause, streaming), not only replacements.
- **One instance only.** The rate limits and the answer cache live in process memory.
- **The data is synthetic.** The catalog comes from a public dataset, and the orders and users are demo data. There's no production traffic or A/B evidence.
- **The labels need a second reviewer.** The 100 query labels were written by the AI assistant that helped build the project and haven't been reviewed by a person yet.

## 7. Release numbers (_pending_)
| What | Target | Result |
|---|---|---|
| 51 conversations, average of 3 live runs (gpt-oss-20b) | ≥ 47/51 | run 1: 48/51; runs 2 and 3 _pending_ |
| 20-user load test, p95 latency | < 3 s | _pending_ |
| 20-user load test, errors | < 1% | _pending_ |
| A safety report reaches Discord | < 1 minute | _pending_ |
| A judge tries search, an order and a cancel from the live link | < 2 minutes, no sign-up | _pending_ |
