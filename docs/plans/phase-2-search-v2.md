# Phase 2: Search v2
- **Status:** Not started
- **Branch:** `phase-2-search-v2`
- **Depends on:** Phase 0 (measurement) and Phase 1 (clean data and attributes)
- **Decisions:** [0006](../decisions/0006-hybrid-search-pgvector.md); the embedding-source ADR is written at the start of this phase

## Goal
Product search that understands meaning, doesn't depend on category names, and keeps hard filters (price, brand, attributes) exact.

## Tasks
- [ ] Plan mode: choose the embedding source (an embeddings API, or a local model through `fastembed`), the model and its dimension. Record the choice as ADR 0009.
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
_Fill in during the phase._
