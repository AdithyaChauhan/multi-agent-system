# 0006. Hybrid search with pgvector in the existing Postgres
- **Status:** Accepted, conditional. Now Phase 3, started only if Phase 1 leaves a gap (the phase numbers in the text below are from the original plan).
- **Date:** 2026-11-18

## Context
Today the model maps a message onto category, subcategory and type, and SQL filters on those values. Two consequences:
- Renamed categories break search: the old `multi_agent_db` produced replies like "We don't carry bose HomeAudio".
- Follow-ups depend on the model rewriting the whole filter set correctly every turn.

## Decision
- The model rewrites the turn into one standalone query plus hard constraints only: price, brand, rating, and attribute filters taken from the type schema (0005). No category names go into the prompt.
- Postgres runs vector similarity (pgvector) and full-text search (`tsvector`) together and merges them with reciprocal rank fusion. Hard constraints are WHERE clauses. Category is a ranking signal, not a filter.
- Product embeddings are computed offline from the clean title, type and attributes.
- It ships behind `PRODUCT_SEARCH=v1|v2`. v2 becomes the default only when it beats v1 on the Phase 0 metrics with no baseline regressions. The LLM ranker is kept or dropped based on the measurements.

## Consequences
- The Postgres images change to `pgvector/pgvector:pg15`. Docker compose currently uses `postgres:15-alpine` and Helm uses `postgres`. Render's database must allow `CREATE EXTENSION vector`.
- Each search turn adds one embedding call. Where embeddings come from is decided at the start of Phase 2 and recorded as a new ADR: an embeddings API (a new key, small cost) or a local model through `fastembed` (ONNX, no PyTorch).

## Alternatives considered
- A separate vector database service: rejected; 1,350 products fit easily in Postgres.
- Vector search over the raw titles without cleaning them first: possible, but hard filters like size and connectivity need 0005.
