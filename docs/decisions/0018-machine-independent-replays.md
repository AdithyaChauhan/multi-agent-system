# 0018. Replays depend on nothing machine-specific
- **Status:** Accepted, implemented (Phase 5)
- **Date:** 2026-11-24

## Context
The first CI runs on GitHub's own runners (2026-11-24) failed where the local simulation had passed. Each cause was something that differs between machines:
- **The Postgres client:** the runner's `pg_restore` (17 or later) sent `SET transaction_timeout`, which the Postgres 15 service rejects.
- **Local files:** `eval/run_split.py` strips `GROQ_API_KEY` so that `.env` wins, but CI has no `.env`, so the replay child had no key and the Groq client refused to start.
- **Storage order:** seeded orders shared one timestamp per user, so "newest first" left their order to Postgres. That order shifts as the harness updates rows, and it changed the router prompt.
- **The CPU:** CI recomputed every embedding on the runner. Vectors are written with 6 decimals, and the last digits differ between CPU types. That reordered near-tied smartwatches (0.00003 apart), changed q05's ranker prompt, and missed its recording on 3 of 6 runs.

The simulation hid all four because it copied the working folder (`.env` included) and ran Debian's Postgres 15 client on this machine's CPU.

## Decision
- **A replay computes no embeddings:**
  - the CI fixture carries the product vectors and `embedding_meta` (`scripts/make_ci_fixture.py` keeps them), and `eval/ci_replay.sh` no longer runs `embed_catalog.py`;
  - query vectors are recorded and replayed like model answers (`app/core/llm.py: recorded_vector`, `eval/cassettes/query_vectors.json`). `VECTOR_CASSETTE_RECORD=1` adds missing ones during a replay, at 0 tokens.
- **Every order a prompt depends on has a tie-breaker:** `fetch_user_orders` sorts by `created_at, id`, and `scripts/untie_order_times.py` gave tied seed orders distinct times. The eval users' orders keep the order their recordings saw, recovered by matching every recorded router call's key.
- **CI uses the database container's own `pg_restore`,** and replay runs get a placeholder key.
- **A miss says what missed.** The harness prints each cassette miss (kind and prompt start) and, on GitHub, reports it as an annotation, which anyone can read without the log.
- **Simulate CI from `git archive HEAD`** in the CI images (`pgvector/pgvector:0.8.0-pg15`, `python:3.12`, `CI=true`), never from the working folder.

## Consequences
- 5 green GitHub runs in a row since (2026-11-24); a local run with the embedding model blocked passes too.
- The fixture grew from 0.7 to 2.6 MB.
- After a change that alters search queries, record the missing query vectors along with the cassettes (0 tokens).
- CI no longer exercises `embed_catalog.py`; `scripts/load_live_db.sh` and the unit tests still do.

## Alternatives considered
- **Rounding distances before ranking:** values near a rounding boundary still flip, and it would change every recording.
- **Pinning a CPU type:** not possible on GitHub-hosted runners.
- **Re-recording on GitHub:** costs tokens and stays non-deterministic across runners.
- **Dropping q05 from the gate:** would hide the problem, not fix it.
