# 0014. Hybrid search: local embeddings, three fused lists, the catalog decides "we don't carry"
- **Status:** Accepted, implemented (Phase 3)
- **Date:** 2026-11-23

## Context
- **The Phase 3 gate** renamed 41 of 47 type names in a copy of the catalog. Recall@5 dropped from 0.971 to 0.853 (35 queries).
  - Every new miss was a shopper word that existed only as our type name.
  - The product titles still carried it.
- **Vague queries were at 0.70.**
- **"Remove fuzz balls from my sweaters" was refused** as "we don't carry clothing".
- **ADR 0006** chose pgvector and full text in the existing Postgres, and left the embedding source to this ADR.

## Decision
- **Embeddings:**
  - `fastembed` with `BAAI/bge-small-en-v1.5` (384 dimensions, ONNX on CPU). It runs locally with no API key or per-call cost, and gives the same vector for the same text, so evals need no cassette for it.
  - The model is baked into the app image.
  - Products are embedded from their own words: title, kind, full name and attribute values. Type and category names are never used, so renaming the catalog can't move the vectors.
  - `scripts/embed_catalog.py` recomputes every vector and records the model in `embedding_meta`.
  - The app uses hybrid search only when that row matches `EMBEDDING_MODEL`, and otherwise falls back to the type search.
- **Retrieval** (`app/search/hybrid.py`) uses three ranked candidate lists of 50 each:
  - **vector:** pgvector cosine on an HNSW index, with `hnsw.iterative_scan` so WHERE filters can't starve it;
  - **text:** full text over title, name and brand, matching any of the query's words;
  - **type:** products of the type the product word resolved to.

  They're fused by weighted reciprocal rank fusion (k = 60, equal weights), and the top 10 go to the LLM ranker.
  - The relax loop loosens price, brand, attributes and keywords until the **requested type** turns up (`found_what_was_asked`). Results of other types alone don't count: "sony headphones under 500" would otherwise stop at a Sony cable.
  - The query text is the extracted product and features plus the shopper's message.
  - The type is a vote, not a gate.
  - Served types, brand, price, rating and keywords are WHERE clauses on every list.
  - Attribute filters belong to one type's schema, so they apply only to products of that type.
- **"We don't carry":**
  - Types we stock but don't sell (phones, laptops, tablets) are still refused by the catalog.
  - For a word the catalog doesn't know, the closest product by meaning (of the word and of the message) must score below cosine 0.75, or we search for it instead.
  - Across 40 everyday things we don't sell (sofa, air conditioner, refrigerator…) the closest match never scored above 0.70.
- **Tuning:** on the dev half of `eval/query_split.json` only, with the extraction replayed and `PRODUCT_RANKER=off`, at 0 tokens.
  - The fusion weights, k and the query text barely moved the dev numbers, so the plainest settings stayed.
  - The shopper's message in the query text raised precision@3 from 0.907 to 0.933.
- **Defaults:** `PRODUCT_SEARCH=hybrid`; `type` remains as the fallback.

## Consequences
- **Test half** (47 queries, v3b model split, 1 run, `multi_agent_baseline`, LLM ranker on), compared with v3b on the same queries:
  - recall@5 0.933 → **1.0**;
  - precision@3 0.900 → 0.930;
  - MRR 0.922 → 0.957;
  - vague 0.6 → 1.0;
  - refusals 1.0.

  Before the loosening fix the run gave 0.978, 0.915 and 0.935.
- **51-conversation baseline** (gpt-oss-20b, 1 run, fill mode): **47/51**, the same 4 failures as Phase 2 (p03, p10, p19, s16).
  - The first run had 2 new failures (p23, p25): an off-type product of the requested brand stopped the loosening.
  - The fix above removed both.
- **Renamed catalog** (the gate's 35 queries, same model split, 1 run, about 81K tokens): recall@5 **0.971**, the same as the normal catalog, so a 0-point drop (the gate measured 11.8).
  - The four gate misses are all found.
  - Precision@3 on the renamed copy is 0.843, against 0.941 on the normal catalog. With weaker type names the type vote helps less, so some off-type products reach the top 3 (q089 "only Bajaj" shows a Bajaj toaster third).
- Search adds about 90 ms per call after a one-time model load of about 2 s, which the app does in the background at startup.
- The app image grows from 1.18 GB to 1.49 GB (onnxruntime plus the model). The running app uses about 310 MB, which fits a 512 MB host.
- The catalog has to be re-embedded when products change: about 2 minutes for 1,350 products on a laptop CPU.
- **The "we don't carry" margin is thin.** The highest non-catalog match was 0.70 against a threshold of 0.75, and the vague query q061 scored 0.76. A test query, q061, was seen while choosing the threshold; the 40 probe words set it. Treat it as a tunable setting (`NOT_CARRIED_MIN_SIM`), and add new out-of-scope words to the evals when they come up.

## Alternatives considered
- **An embeddings API:** a new key, a per-call cost, and network latency, plus cassettes for evals. The local model fits the memory budget, so the API isn't needed.
- **The pgvector/pgvector Docker image:** it's Debian (glibc), while the existing volumes were created on Alpine (musl), whose text sort order differs. Compose builds pgvector on `postgres:15-alpine` instead. Helm, which always starts on a fresh volume, uses the official image.
- **Grounding product words on product titles without embeddings:** this fixes the renamed misses but not the vague queries (0013).
- **The type as a hard filter:** a renamed or mis-picked type hides the right products, as with "mixer grinder" becoming hand mixers in the gate.
