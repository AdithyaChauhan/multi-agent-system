# Phase 0: Measuring stick
- **Status:** In progress (started 2026-11-18)
- **Branch:** `phase-0-evals`
- **Depends on:** nothing
- **Decisions:** [0004](../decisions/0004-measure-before-changing.md)

## Goal
A cheap, repeatable measurement of product search quality, so every later change is judged by numbers rather than by trying a few chats.

## Why first
Phases 1 and 2 change the data and the search. Without a fixed yardstick it's impossible to tell whether they helped, and the Groq quota makes ad-hoc live testing expensive.

## Scope
- **In:** labelled product queries, a retrieval scorer, LLM record and replay, today's numbers, a renamed-taxonomy robustness check.
- **Out:** changing search behaviour, the prompt-injection set (Phase 4), live DeepEval judging.

## Metric definitions
- **recall@5** (as used in the roadmap): the share of queries where at least one `exact` product appears in the top 5. This is also called hit rate@5.
- **precision@3:** the share of the top 3 results that are `exact` or `ok`.
- **MRR:** the mean of 1 / rank of the first `exact` product.
- **Empty-result rate:** the share of queries that should return products but returned none.
- **Correct-refusal rate:** for items we don't carry, the share of queries that return no products and say so.
- Also report: LLM calls, tokens, p50 and p95 latency. Break every metric down by tag.

## Tasks
- [x] Plan mode at phase start. Skipped: the user said to go ahead, so the defaults below were used.
- [x] `eval/product_queries.json`: 100 queries (95 labelled, 5 out of scope). Rules were checked against every match and false positives fixed by Claude. **A person still needs to review them** (`reviewed: false` on each query). Each has an `id`, an optional `history` (earlier turns), the `query`, `tags`, and `expect`. `expect` is either `{"exact": [product ids], "ok": [product ids]}` or `{"none": true}` for items we don't carry. Suggested mix:
  - 20 plain item ("electric kettle");
  - 10 item + brand ("sony headphones");
  - 10 item + price ("mixer grinder under 3000");
  - 15 attributes ("wireless mouse", "55 inch 4k tv", "braided type-c cable");
  - 10 vague needs ("something to keep my room warm");
  - 10 typos and Hinglish ("lojitech mouse", "sasta trimmer");
  - 5 brands we don't carry ("bose speakers");
  - 5 out of scope ("iphone 15", "gaming laptop");
  - 15 multi-turn follow-ups ("under 1000" or "what about Logitech" after an earlier query).

  Reuse the product cases p01–p25 in `eval/baseline_conversations.json` where they fit.
- [x] Label against `multi_agent_baseline` using **product ids, never categories**, via `eval/label_queries.py` (`--show qNNN` lists every match; `--write` freezes the ids). Original wording: so the labels survive Phase 1. Generate candidates with SQL (name, brand, price), then have a human confirm every label. An LLM may propose labels but never finalises them. Keep the candidate SQL in a script so labels can be checked again later.
- [x] Record and replay in `app/core/llm.py` (`LLM_CASSETTE_MODE=record|replay`, `LLM_CASSETTE_PATH`). Verified: a replay run used 0 tokens and matched the live run exactly. Original wording, record and replay behind an environment variable plus a file path:
  - key each entry by a hash of the model, messages and schema;
  - replay never touches the network, and a missing entry fails loudly;
  - recordings go in `eval/cassettes/`, which must stay small.
- [x] `eval/run_retrieval.py`, with metrics in `eval/retrieval_metrics.py`. It also has `--resume` and `--token-budget` for the daily cap:
  - runs the product graph directly, without the router, for each query and its history;
  - computes the metrics above;
  - writes `eval/retrieval_runs/<label>.json` and prints a table;
  - takes the same options as `run_baseline.py`: `--label`, `--model`, `--database-url`, `--only`, `--tags`.
- [ ] Today's numbers (partly done: q001–q052 recorded on gpt-oss-20b before the daily cap; finish with `--resume`, about 95K tokens):
  - one live run on `openai/gpt-oss-20b`, recorded;
  - one replay run, which must give identical numbers;
  - optionally, one live qwen run when quota allows.
- [x] Robustness check (done on a 35-query sample; see Results):
  - `scripts/make_renamed_catalog_db.py` creates a copy of `multi_agent_baseline` (for example `CREATE DATABASE multi_agent_renamed TEMPLATE multi_agent_baseline`) and renames every category and subcategory, e.g. "mouse" becomes "Pointing Devices";
  - run the eval against the copy and report the drop;
  - optionally spot-check `multi_agent_db` (read-only) after confirming its product ids match.
- [x] Tests: `tests/test_retrieval_metrics.py` and `tests/test_llm_replay.py`. 194 passed, coverage 90%, black and flake8 clean.
- [ ] Optional: a CI step that runs the retrieval eval in replay mode.
- [ ] Fill in Results, update the ROADMAP status and run `/handoff`.

## Acceptance criteria
- At least 100 labelled queries, each confirmed by a person.
- One command prints the metrics. A replay run uses 0 tokens and reproduces the live numbers exactly.
- Today's numbers are recorded, both on the baseline database and on the renamed copy.
- Tests and lint pass, with coverage at or above 80%.

## Risks and notes
- **Tokens:** about 2 LLM calls (extraction and ranking) and about 2,000 tokens per query, so roughly 200K tokens per live run. That is one model's full daily quota. Split the run by tag across gpt-oss-20b and -120b, or across days. Record once, then replay.
- **Labelling is the slow part.** Budget most of the phase for it. A wrong label hides real problems.
- **`TEMPLATE` copies need no other open connections** to `multi_agent_baseline`. Stop any baseline runs first.

## Results
All runs were on 2026-11-18, 1 run each, code at `phase-0-evals`. Files are in `eval/retrieval_runs/`, scored against the labels after the rule fixes (`--rescore`).

**v1 (today's search), gpt-oss-20b, `multi_agent_baseline`, q001–q052 only** (the daily cap stopped the run) · `v1-gptoss20b.json`

| Metric | Value |
|---|---|
| recall@5 | 0.885 |
| precision@3 | 0.897 |
| MRR | 0.865 |
| empty rate | 9.6% |
| LLM calls per query | 1.96 |
| tokens per query | ~1,885 |
| latency p50 / p95 | 1.1 s / 2.2 s |

| Tag (n) | recall@5 | precision@3 |
|---|---|---|
| plain (20) | 1.00 | 0.98 |
| brand (10) | 1.00 | 1.00 |
| price (10) | 0.80 | 0.80 |
| attribute (13) | 0.62 | 0.69 (31% empty) |

**Robustness: 35-query sample, gpt-oss-120b, same queries on both databases**

| Database | recall@5 | precision@3 | MRR | empty rate |
|---|---|---|---|---|
| `multi_agent_baseline` | 0.971 | 0.931 | 0.936 | 2.9% |
| `multi_agent_renamed` | **0.000** | 0.000 | 0.000 | **100%** |

With the categories renamed, every search answered "I couldn't find any …". Out-of-scope items were still refused. Today's search depends entirely on the exact category names (ADRs 0005 and 0006).

**Failures worth fixing in Phases 1–2** (from the 20b run):
- "geyser under 5000" and "3 litre instant geyser": the reply said "we don't carry water heater", although there are 44 water heaters.
- "hdmi cable", "braided type-c cable" and "wireless mouse under 500" showed nothing, although matching products exist.
- "earbuds with noise cancellation" showed ENC earbuds (microphone noise reduction), not ANC.

**Notes:**
- Fixing my label rules raised v1 precision@3 from 0.865 to 0.897. The labels still need a person to review them.
- Replay can't run the renamed check for free: the extraction prompt contains the catalog list, so a different database means different prompts. Phase 3 (hybrid search) removes that list.
- A CI replay step would need Postgres in CI, because search runs real SQL. Deferred.
