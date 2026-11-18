# Phase 0: Measuring stick
- **Status:** Not started
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
- [ ] Plan mode at phase start: confirm the query mix, label format and metric definitions with the user.
- [ ] `eval/product_queries.json`, about 100 queries. Each has an `id`, an optional `history` (earlier turns), the `query`, `tags`, and `expect`. `expect` is either `{"exact": [product ids], "ok": [product ids]}` or `{"none": true}` for items we don't carry. Suggested mix:
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
- [ ] Label against `multi_agent_baseline` using **product ids, never categories**, so the labels survive Phase 1. Generate candidates with SQL (name, brand, price), then have a human confirm every label. An LLM may propose labels but never finalises them. Keep the candidate SQL in a script so labels can be checked again later.
- [ ] Record and replay in `app/core/llm.py`, behind an environment variable such as `LLM_CASSETTE=record|replay` plus a file path:
  - key each entry by a hash of the model, messages and schema;
  - replay never touches the network, and a missing entry fails loudly;
  - recordings go in `eval/cassettes/`, which must stay small.
- [ ] `eval/run_retrieval.py`:
  - runs the product graph directly, without the router, for each query and its history;
  - computes the metrics above;
  - writes `eval/retrieval_runs/<label>.json` and prints a table;
  - takes the same options as `run_baseline.py`: `--label`, `--model`, `--database-url`, `--only`, `--tags`.
- [ ] Today's numbers:
  - one live run on `openai/gpt-oss-20b`, recorded;
  - one replay run, which must give identical numbers;
  - optionally, one live qwen run when quota allows.
- [ ] Robustness check:
  - `scripts/make_renamed_catalog_db.py` creates a copy of `multi_agent_baseline` (for example `CREATE DATABASE multi_agent_renamed TEMPLATE multi_agent_baseline`) and renames every category and subcategory, e.g. "mouse" becomes "Pointing Devices";
  - run the eval against the copy and report the drop;
  - optionally spot-check `multi_agent_db` (read-only) after confirming its product ids match.
- [ ] Tests: `tests/test_retrieval_metrics.py` and `tests/test_llm_replay.py`. Lint passes and coverage stays at or above 80%.
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
_Fill in during the phase: date, model, number of runs, database, and every metric by tag._
