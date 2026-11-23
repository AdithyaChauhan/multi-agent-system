# Phase 3: Hybrid search (conditional)
- **Status:** In progress. The gate said go on 2026-11-23 (see Results). **Start only if** the Phase 1 results leave a gap: attribute recall@5 below 0.85, a recall@5 drop of more than 5 points on the renamed catalog, or vague and Hinglish queries below 0.85. If not, mark this phase Dropped and say why.
- **Branch:** `phase-3-hybrid-search`
- **Depends on:** Phase 0 (measurement) and Phase 1 (clean data and attributes)
- **Decisions:** [0006](../decisions/0006-hybrid-search-pgvector.md); the embedding-source ADR is written at the start of this phase

## Goal
Product search that understands meaning, doesn't depend on category names, and keeps hard filters (price, brand, attributes) exact.

## Tasks
- [x] Go/no-go gate (2026-11-23). Result: **go**, because the renamed catalog drops recall@5 by 11.8 points. Details are in Results.
  - attribute recall@5 is 1.0, so no gap;
  - Hinglish (0.80) and vague (0.70) are below the bar, but only 1 of their 4 misses is a meaning problem (see Results);
  - `scripts/make_renamed_catalog_db.py` had to be fixed first. It renamed the old text columns on `products`, but since Phase 1 search reads `product_types`, so it now renames those type names and categories too.
- [ ] Choose the embedding source (an embeddings API, or a local model through `fastembed`), the model and its dimension, and record the choice as the next ADR. Also consider a full-text-only first step (see Results).
- [ ] Postgres with pgvector:
  - switch docker compose from `postgres:15-alpine` and Helm from `postgres` to `pgvector/pgvector:pg15`;
  - check that Render allows `CREATE EXTENSION vector`;
  - migration: the extension, `products.embedding vector(N)` with an HNSW index, and a generated `tsv` column with a GIN index.
- [ ] `scripts/embed_catalog.py`: embeds the clean title, type and attributes. It can be re-run safely and stores the model name and version.
- [ ] `app/prompts/query_rewrite.md`, under 40 lines with no catalog list. It returns a standalone query, hard constraints (price, brand, rating) and attribute filters. Attribute filters are validated against the type schema when the type is clear.
- [ ] Hybrid search in `app/tools/product_tools.py`:
  - vector top 50 and full-text top 50, with the constraints as WHERE clauses;
  - merged with reciprocal rank fusion;
  - top 20 returned.
- [ ] Product graph v2 behind `PRODUCT_SEARCH=v2`; v1 stays untouched.
- [ ] Measure v1 against v2 with the Phase 0 harness, on the same model and database:
  - on the baseline database and on the renamed copy;
  - with and without the LLM ranker;
  - tune k and the fusion constant on half the queries, and report on the other half.
- [ ] Run the 51-conversation baseline on v2.
- [ ] Make v2 the default only if the acceptance criteria are met. Otherwise record why, and keep v1 on the clean data.
- [ ] Fill in Results, update the ROADMAP and run `/handoff`.

## Acceptance criteria
- v2 recall@5 is at least 10 points above v1 (aim for 0.85 now, 0.9 by Phase 5), and precision@3 is no lower than v1.
- On the renamed-taxonomy copy, recall@5 drops by less than 5 points.
- No new baseline failures compared with v1, on the same model and number of runs.
- Tokens per product turn are no higher than v1, excluding the embedding call. Report p95 latency.

## Risks and notes
- **Brand filtering:** a hard brand filter can hide good results when the user typed the brand wrong. Measure a hard filter against a ranking boost.
- **The local-model option adds to the Docker image size.** Check the image size before choosing it.
- **Don't tune on the full query set**, or the numbers will look better than real use.

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
