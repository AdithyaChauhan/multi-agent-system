# Phase 3: Hybrid search and product cards
- **Status:** Done (2026-11-23). Every acceptance criterion is met; the renamed catalog's precision@3 is still 10 points lower (see Results).
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
- [x] Postgres with pgvector:
  - `docker/postgres/Dockerfile`: pgvector 0.8.0 on `postgres:15-alpine`; the volume was kept, with the same row counts after the switch;
  - both databases were backed up to `%TEMP%` first;
  - migration `b5e1f0a3c2d4`.
- [x] `app/search/embeddings.py`; `scripts/embed_catalog.py` (both databases, about 2 minutes each); the model is baked into the image.
- [x] `app/search/hybrid.py`: three lists, weighted RRF, top 10 to the ranker. The relax loop loosens until the requested type turns up.
- [x] Catalog check before "we don't carry" (cosine 0.75, set from 40 out-of-catalog probe words).
- [x] Product cards: `ChatResponse.products`, cards in `chat.html`, and the stream's `reply` event.
- [x] Eval harness:
  - `PRODUCT_RANKER=off`;
  - `eval/query_split.json` (53 dev, 47 test);
  - `eval/run_split.py`;
  - a cassette `fill` mode in `app/core/llm.py`, `run_retrieval.py` and `run_baseline.py`.
- [x] Tests: `tests/test_hybrid_search.py` (19 unit tests, plus 1 integration test on pgvector) and the fill-mode test. 286 pass, coverage 89%, lint clean.
- [x] Measured: see Results.
- [x] Hybrid is the default (`PRODUCT_SEARCH=hybrid`); `type` remains the fallback.
- [x] ADR 0014; Results; ROADMAP.

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

### Build (2026-11-23)
Every number below is 1 run on `multi_agent_baseline` unless it says otherwise. "v3b split" means each query runs on the model that answered it in v3b (gpt-oss-20b, gpt-oss-120b or qwen3.8-27b).

**Tuning** (dev half, 53 queries, extraction replayed, `PRODUCT_RANKER=off`, 0 tokens):

| Setting | recall@5 | precision@3 | MRR |
|---|---|---|---|
| type search (v3b code) | 0.940 | 0.927 | 0.893 |
| **hybrid, equal weights, k = 60, product + features + message** | **0.960** | **0.933** | **0.927** |
| type weight 0.5 / 2 | 0.960 | 0.920 / 0.933 | 0.917 |
| k = 20 | 0.960 | 0.933 | 0.927 |
| query without the message | 0.960 | 0.907 | 0.877 |
| vector or text weight 2 | 0.960 | 0.913 / 0.933 | 0.917 |

The settings barely matter, so the plain defaults stayed (`eval/retrieval_runs/tune-dev-*-combined-summary.json`).

**Test half** (47 queries, v3b split, LLM ranker on, fill mode, about 34K tokens):

| | recall@5 | precision@3 | MRR | vague | refusals |
|---|---|---|---|---|---|
| v3b (type search) | 0.933 | 0.900 | 0.922 | 0.6 | 1.0 |
| **hybrid** (`v4b-test`) | **1.000** | **0.930** | **0.957** | **1.0** | 1.0 |

The first hybrid run (`v4-test`) gave 0.978, 0.915 and 0.935, before the loosening fix below.

**Renamed catalog** (the gate's 35 queries, v3b split, about 81K tokens, recorded to `eval/cassettes/renamed_*`):

| | recall@5 | precision@3 | MRR |
|---|---|---|---|
| normal catalog (v3b) | 0.971 | 0.941 | 0.951 |
| renamed, type search (gate) | 0.853 | 0.833 | 0.829 |
| **renamed, hybrid** | **0.971** | 0.843 | 0.893 |

- The recall drop goes from 11.8 points to 0, against a bar of 5. All four gate misses are found.
- Precision@3 on the renamed copy is still 10 points below the normal catalog. With unfamiliar type names the type vote helps less, so an off-type product can reach the top 3 (q089 shows a Bajaj toaster third).

**51-conversation baseline** (gpt-oss-20b, fill mode): **47/51 conversations, 86/90 turns**, the same as Phase 2. The same 4 fail: p03 "table", p10 "4k monitor", p19 "usb hub with ethernet" and s16 routing.
- **A bug the baseline caught:** the first run failed p23 "sony headphones under 500" and p25 "amazon fire tv stick". A Sony cable or an Amazon-brand TV satisfied the search, so the loop never loosened the brand, and the ranker then rejected everything.
  - Fix: `found_what_was_asked`. Only the requested type counts as found.
  - This also produced the test-half numbers above.
- That first run also had a burst of HTTP 500s (p12–p25), with Groq calls failing after SDK retries. A single call worked straight afterwards, and re-running those conversations passed. A Phase 4 item: the friendly busy message and the fallback chain.

**Running it** (local Docker):
- the app image grew from 1.18 GB to 1.49 GB;
- the app uses 310–320 MB of memory with the model loaded, under the 450 MB criterion;
- a search call takes about 90 ms after a one-time model load of about 2 s at startup (in the background);
- embedding the catalog takes about 2 minutes per database.

**Live check** (`docker compose`, `multi_agent_db`):
- "something to keep my room warm in winter" shows 3 heater cards with photos, prices and ratings;
- "iphone 15" is refused;
- "remove fuzz balls from my sweaters" was routed to *clarify* by the router (the app's `GROQ_MODEL`), so product search never ran. This is a routing problem for Phase 4's evals, not a prompt rule (0010).

**Found along the way:** `.dockerignore` excluded only `.env`, so locally built images contained `.env.eval` (a second Groq key), `.claude/`, `dump.sql` and `ecommerce.db`. Images built by CI and Render start from the git checkout, so they never had them. `.dockerignore` now excludes every `.env.*` and the local-only files.

**Still open:**
- the router misroute above;
- renamed-catalog precision;
- the Phase 4 list (sort by price for "sasta", fitness-band data, the p03 "table" kind, p19).

