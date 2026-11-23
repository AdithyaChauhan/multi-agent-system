# Phase 3: Hybrid search and product cards
- **Status:** In progress. The gate said go on 2026-11-23 (see Results).
- **Branch:** `phase-3-hybrid-search`
- **Depends on:** Phase 0 (measurement) and Phase 1 (clean data and attributes)
- **Decisions:** [0006](../decisions/0006-hybrid-search-pgvector.md), [0013](../decisions/0013-judge-facing-priorities.md); 0014 records the embedding choice and the fusion design

## Goal
Search that understands meaning and doesn't depend on our type names, while price, brand, rating and attribute filters stay exact. Product replies show cards a judge can see.

## Design
- The flow stays the same: extract (LLM) → plan → search loop → rank (LLM) → reply. Only the `search` node changes, behind `PRODUCT_SEARCH=hybrid` until it wins.
- **Three ranked candidate lists, fused** with weighted reciprocal rank fusion:
  - vector similarity on the query;
  - full text;
  - products of the resolved type.

  The model's type becomes one vote, not a gate.
- **Embeddings:** local `fastembed` with `BAAI/bge-small-en-v1.5` (384 dimensions). No API key, deterministic. They're built from the title, kind and attribute values, never from type or category names.
- **"We don't carry":** before the model's "not carried" becomes a refusal, the catalog checks the best vector match. Unserved types are still refused.

## Tasks
- [x] Go/no-go gate (2026-11-23): **go**, because the renamed catalog drops recall@5 by 11.8 points. See Results.
- [x] Roadmap reset around what a judge sees ([0013](../decisions/0013-judge-facing-priorities.md)).
- [ ] Postgres with pgvector:
  - `docker/postgres/Dockerfile` (`postgres:15-alpine` plus pgvector built from source, so the existing volumes stay compatible), used by compose and Helm;
  - back up both databases first;
  - migration: the extension, `products.embedding vector(384)` with an HNSW index, and a generated `search_tsv` with a GIN index (no-op on SQLite).
- [ ] `app/search/embeddings.py` and `scripts/embed_catalog.py` (re-runnable, records the model name). The model is baked into the app image.
- [ ] `app/search/hybrid.py`: hard filters in SQL, three candidate lists, weighted RRF, top 20 to the ranker.
- [ ] Catalog check before "we don't carry" (threshold tuned on the dev half).
- [ ] Product cards: `ChatResponse.products`, cards in `chat.html`, also in the stream's `reply` event.
- [ ] Eval harness:
  - `run_retrieval.py --rank score` (no LLM ranker, so tuning is free);
  - `eval/query_split.json` (a fixed dev/test split).
- [ ] Tests: fusion, query text, the not-carried check, cards; an integration test for pgvector.
- [ ] Measure:
  - tune on dev (replay, 0 tokens);
  - final live run on the test half, the renamed sample (re-embedded) and the 51-conversation baseline;
  - image size, container memory and added p95 latency.
- [ ] Make hybrid the default if the acceptance criteria are met. Otherwise record why.
- [ ] ADR 0014; fill in Results; update the ROADMAP; run `/handoff`.

## Acceptance criteria
- On the test half, recall@5 and precision@3 are no lower than v3b on the same queries.
- On the renamed catalog, recall@5 drops by less than 5 points (from 0.971 on the 35-query sample).
- Vague and Hinglish improve, and out-of-scope refusals stay at 1.0.
- No new failures in the 51-conversation baseline (47/51).
- Search adds less than 150 ms at p95, and the app container stays under 450 MB of memory (to fit a small free host).

## Risks and notes
- **Don't tune on the test half.**
- **The local model adds to the image and to memory.** If the app goes over 450 MB, Phase 5 embeds queries through an API instead.
- **Amazon image links can expire.** Cards fall back to a placeholder.

## Results

### Go/no-go gate (2026-11-23)
**Renamed catalog.** These are the 35 Phase 0 robustness queries, run on the same model per query as v3b: 25 on gpt-oss-20b, 6 on gpt-oss-120b and 4 on qwen3.8-27b. Each was run once, live, at about 83K tokens. The renamed copy changes 41 of the 47 `product_types` names and all four categories. Synonyms, kinds, attributes and brands are kept. Types we don't sell and the "other …" types keep their names.

| Database | recall@5 | precision@3 | MRR | empty rate | refusals |
|---|---|---|---|---|---|
| `multi_agent_baseline` (the v3b runs, same queries) | 0.971 | 0.941 | 0.951 | 0% | 1.0 |
| `multi_agent_renamed` | **0.853** | 0.833 | 0.829 | 2.9% | 1.0 |

- The drop is **11.8 points**, against a bar of 5. In Phase 0 it was 97 points (0.971 → 0.000), so Phase 1 recovered most of it.
- Every new miss has the same cause: the shopper's word was our type name, and nothing else in the data carries it.
  - q016 "lint remover" was refused as "we don't carry lint remover", although the type still has its products under its new name, "Fabric Care".
  - q002 "mixer grinder" and q089 "only Bajaj" fell back to the `hand mixer` kind.
  - q086 "what about Logitech", after "mouse", became "pointing device" and returned 1 result.
- The product titles still say "lint remover", "mixer grinder" and "mouse". Search that also reads titles (full text or embeddings) would find them. That is what this phase adds.
- Files: `eval/retrieval_runs/robust-v3b-renamed-{20b,120b,qwen}.json`, `robust-v3b-renamed-combined-summary.json` and `robust-v3b-baseline-summary.json`.

**Hinglish and vague** (v3b, 0 tokens). Of the 4 misses, only q061 ("fuzz balls from my sweaters", refused as clothing) is a meaning problem. The others:
- q071 "sasta": nothing ranks cheap items first;
- q065: a label or ambiguity question;
- q062: fitness-band data.

These go to Phase 4's list rather than driving this phase.
