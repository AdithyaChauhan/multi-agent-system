# Phase 1: Clean product data
- **Status:** Done 2026-11-19 (plan approved 2026-11-18). The user skipped their own 50-product spot check, so only Claude's review stands.
- **Branch:** `phase-1-catalog` (off `phase-0-evals`)
- **Depends on:** Phase 0 (to measure the effect)
- **Decisions:** [0005](../decisions/0005-structured-product-catalog.md), [0010](../decisions/0010-prompt-budget.md)

## Goal
Every product has a correct type, a clean title, one canonical brand and the key attributes for its type. Facts about products move out of prompts and Python constants into the database.

## Context
Checked on 2026-11-18 in `multi_agent_baseline` (see also the audit in ADR 0005):
- `attributes` is empty on all 1,350 rows. The `specs` table is empty too.
- There are 97 category/subcategory pairs, and they're wrong in places:
  - the "adapter" bucket holds 5 Samsung/iQOO phones and a wireless mouse;
  - "Accessories" holds memory cards, smartwatches and a Nokia phone;
  - "monitor stand" is really laptop stands and tables;
  - "storage organizer" is laundry baskets.
- Brands are duplicated: MI/Mi/Xiaomi/Redmi, Amazon/AmazonBasics/Amazonbasics, ZEBRONICS/Zebronics, USHA/Usha, pTron/PTron.
- To compensate, the code has `PRODUCT_TYPES`, `SERVED_CATEGORIES` and `NOT_SERVED` (`app/agents/product_agent.py`), `EXCLUDED_SUBCATEGORIES` (`app/tools/product_tools.py`) and the catalog list in `app/prompts/product_extraction.md`.

## Decisions taken in planning
- **Redmi is an alias of Xiaomi** (user's choice). MI, Mi, Redmi and Xiaomi become one brand.
- **Regex first, then a batched LLM pass.** Regex pulls the easy facts from names and descriptions for free. The LLM then runs in two steps:
  - classify: about 25 products per call, names only;
  - attributes: about 15 products of one type per call, with only that type's schema.

  This costs about 0.45M tokens instead of 0.8M for one call per product. When regex and the LLM disagree, the row goes to review.
- **At search time, code maps shopper words to attribute filters.** The model names the product and lists feature words; code matches them against the type's values, aliases and units from the YAML. No schemas go into the prompt (0010).
- **About 45 types, each with an optional `kind` attribute** whose values are searchable product words: "pen drive" is type `storage` with kind `pen drive`. That's slightly over the 30–40 guideline. The extras are catch-all types plus phone, laptop and tablet (`served: false`), which are kept only so the app can say "we don't carry that".
- **A type with fewer than 5 products merges into its category's catch-all**, except `served: false` types.

## Target schema
```
product_types  id, name, category, served bool, synonyms jsonb, attribute_schema jsonb
brands         id, name, aliases jsonb
products       + type_id, brand_id, title, extracted_by (regex|llm|human), confidence
               (attributes is filled; raw name, type, category, subcategory, brand, tags stay)
```
Lists are JSONB rather than `text[]`, so the SQLite test database keeps working.

## Tasks
- [x] `data/catalog/product_types.yaml` (about 45 types, draft in the approved plan) and `data/catalog/brands.yaml`; user review of both.
- [x] `app/catalog/schema.py`: load the YAML and build one Pydantic model per type. Groq gets plain string fields, and validation happens afterwards, because an off-list enum makes Groq reject the whole call.
- [x] Alembic migration after `f3a9b2c7d1e5`: new tables and columns, non-destructive and reversible. Add `ProductType` and `Brand` models.
- [x] `scripts/enrich_catalog.py` with the subcommands `regex`, `classify`, `attributes`, `review` and `apply`. It writes checkpoints to `data/catalog/enriched_products.jsonl`, can resume, takes `--token-budget`, records through `call_llm`, and paces under the TPM limit. Run a 2-batch pilot first and re-estimate the tokens.
- [x] Run the enrichment on gpt-oss-120b, with the `.env.eval` key when the main key is capped.
- [x] (Claude's triage and spot check done; the user skipped theirs on 2026-11-19) Review: Claude triages `data/catalog/review.csv`, then the user spot-checks 50 random products plus the rows Claude was unsure about.
- [x] Search on the new columns:
  - the extraction returns `product`, resolved to a type and kind, and `features`;
  - `app/catalog/features.py` maps features to attribute filters;
  - `search_products` filters by `type_id`, attributes, brand aliases and `served`;
  - a `served: false` type triggers the deterministic "we don't carry" reply;
  - the relaxation order becomes price, brand, attributes, keywords.
- [x] Remove `PRODUCT_TYPES`, `SERVED_CATEGORIES`, `NOT_SERVED`, `EXCLUDED_SUBCATEGORIES` and the catalog list in the prompt (the prompt reads type lines from the database).
- [x] Tests: schema loading, regex extractors, feature mapping, product-word resolution, apply idempotency and search filters. Coverage stays at or above 80%, and lint stays clean.
- [x] Measure: a 10-query smoke test, then all 100 queries with the same model per query as `v1-combined`. Optionally, the renamed-catalog sample (about 70K tokens).
- [x] README restore steps (`alembic upgrade head`, then `scripts/enrich_catalog.py apply`).
- [x] Fill in Results, update the ROADMAP and run `/handoff`.
- [ ] Deferred to Phase 3's go/no-go: the optional renamed-catalog sample (about 70K tokens) was not run on v2.

## Acceptance criteria
- 100% of served products have a type, and at least 90% have every required attribute for their type (or an explicit "not applicable").
- No duplicate brands from the agreed alias list, and every `review.csv` row is resolved.
- The catalog constants and the catalog list in the extraction prompt are gone.
- Phase 0 recall@5 is not lower than 0.874. Report the change, including the attribute (0.75) and Hinglish (0.60) tags.
- `dump.sql`, `backups/` and `ecommerce.db` are untouched.

## Token budget
| Step | Model | Tokens |
|---|---|---|
| Enrichment (pilot, classify, attributes) | gpt-oss-120b on both keys, gpt-oss-20b if needed | ~0.45M over 1–2 days |
| v2 eval (q001–055 and q088–100 on 20b, q056–074 on 120b, q075–087 on qwen) | mixed | ~220K |
| Optional renamed-catalog sample (35 queries) | gpt-oss-120b | ~70K |

## Risks and notes
- gpt-oss reasoning tokens vary, so the pilot sets the real per-batch cost before the full run.
- **Over-detailed schemas** waste tokens and review time. If nobody filters on a field, leave it out.
- `enriched_products.jsonl` will be about 1 MB, which is fine for the repo.
- Phase 0 labels come from SQL rules over raw names, so the enrichment can't leak into the eval.
- **`multi_agent_db` was updated on the user's request (2026-11-18).** Its Alembic history was at `a1e6f9d2c4b7` from `master`, which doesn't connect to this branch. It was backed up to `%TEMP%/multi_agent_db_before_phase1_20261118.dump`, re-stamped to `f3a9b2c7d1e5` (`stamp --purge`) and upgraded to `a7d4e2c9b1f0`. Master's `catalog_*` and `taxonomy_aliases` tables were left alone. To undo, restore the dump with `pg_restore --clean`.

## Results
- **Type list:** 47 types (3 not served), user-approved 2026-11-18. Brand merges in `brands.yaml`: Redmi counts as Xiaomi, and Amazon, AmazonBasics and Solimo are one brand.
- **Migration** `a7d4e2c9b1f0`: upgrade, downgrade and upgrade again all clean on `multi_agent_baseline`. Applied to `multi_agent_db` later, at the user's request (see Risks and notes).
- **Regex alone** on a random 400-name sample (no tokens): TV screen size 85%, cable connectors 90%, headphone connectivity 96%, mouse connectivity 61%.
- **Classify pilot** (gpt-oss-120b, 50 products):
  - about 2.7K tokens per 25 products;
  - 46 of 50 right. 1 was flagged automatically. 3 were wrong but confident: a calculator labelled "other electronics accessory", and 2 Pureit Germkill kits labelled purifiers when they're cartridges;
  - two fixes came from the pilot. The model copied the category headings into `type`, so the headings were dropped and the field renamed `product_type`. Groq rejected a whole batch (`tool_use_failed`), so the script now splits a rejected batch in half and retries.
- **Search** now uses `product_types`, attributes and brand aliases. The constants and the catalog list in the prompt are gone; the prompt is 29 lines.
- **Classify, full run** (gpt-oss-120b, `.env.eval` key): 1,348 of 1,350 typed for 156K tokens. The other 2 (iPhone covers the model put under an invented "phone accessory" type) were corrected in `review.csv` (`reviewer=claude`). The old buckets were wrong in places: the "tv" subcategory held 12 remotes and 5 covers or mounts, "mouse" held 9 non-mice, and "adapter" held 6 phones.
- **Regex attributes** (names only, 0 tokens) are applied. Two matcher bugs were fixed on the way: the value `other` was matched as a word, and description text cancelled the name's resolution.
- **Applied to both databases:** 1,350 typed and titled, 1,270 in served types, 1,289 with a brand, 360 brands. The app container was rebuilt on this branch, and in-container searches return correct results for "43 inch 4k tv", "geyser", "wireless mouse under 1000", "redmi charger" and "fitness tracker".
- **Attributes pilot** (gpt-oss-120b, `.env.eval` key): 195 products (all 165 cables and the 30 mice) for 36K tokens, about 2.8K per 15 products, so the remaining ~880 need about 165K, not 300K.
  - Fill rates: cable connectors 157/165, cable length 138/165, mouse connectivity 27/30.
  - Most of the 27 regex/LLM disagreements were the LLM being right, because regex lacked spellings like "Micro B", "Mini 5 pin" and "B-Male"; those aliases are now in the YAML. One real LLM error (an A-to-A extension cable marked usb-b) went to review.
  - A regex-only `--redo` could no longer overwrite LLM results (guarded).
  - Status after the pilot: 469 products have all their attributes; 111 rows need review.
- **Attributes, full run** (2026-11-19, gpt-oss-120b on both keys): all 1,350 done for 191K tokens in total, including the pilot. The main key hit Groq's rolling 24-hour cap at 131K.
- **Review:** all 105 rows resolved by Claude (`reviewer=claude`): 54 corrections, the rest accepted (the LLM was right, or the name doesn't state the detail).
  - Fixes found while reviewing, each with a test: numbers glued to letters are model codes, not specs ("S20", "MPK120L"); "500-Watt" is now read; negations ("Without Voice", "Non-Voice") are respected; the value names `other` and `power` are no longer matched as words; regex reads names only.
  - Data fixes: exhaust fan, pencil, sketch pens, convector and radiant heaters, optical and power-cord connectors, internal SSD; for mice and keyboards, bluetooth counts as wireless.
  - Code fixes: a kind the model writes in its own words is matched leniently ("bagless vacuum" → canister vacuum); a product phrase built from known words resolves ("neckband headphones" → headphones/neckband), but never to a type we don't sell.
- **Coverage:** 1,261 of 1,270 served products (99.3%) have every required attribute.
- **Spot check** (50 random products, seed 7, `data/catalog/review_sample.csv`): Claude found 6 with an error (44/50 fully right; type right on 47/50), all corrected. The user skipped their own check (2026-11-19).
- **v2 measurement** (`eval/retrieval_runs/v2-combined-summary.json`, same model per query as v1, `multi_agent_baseline`; 64 queries replayed at 0 tokens after the last search fixes, 36 recorded live):

  | | v1 | v2 |
  |---|---|---|
  | recall@5 | 0.874 | **0.958** |
  | precision@3 | 0.870 | **0.926** |
  | MRR | 0.837 | 0.927 |
  | empty rate | 9.5% | 0% |
  | attribute | 0.75 | 1.0 |
  | Hinglish | 0.60 | 0.80 |
  | follow-up | 0.93 | 1.0 |
  | price | 0.80 | 0.93 |
  | brand | 0.938 | 0.938 |
  | out of scope (refusal) | 0.8 | 0.8 |

  Tokens per query are unchanged (about 2.2K, from the live runs).
  - Remaining misses: q027 "noise smart watch" (the model dropped the brand this run), q084 "washing machine" (asked "what are you looking for?" instead of refusing), and q087 follow-up "Samsung" (lost the product). These belong to Phase 2: state and follow-ups.
  - Measured before the last 9 spot-check corrections; they don't change any labelled query's type.
- **Tests:** 221 unit tests pass, coverage 91%, lint clean. 13 obsolete mock tests for the old search were replaced by SQLite tests on a seeded catalog.
- **Acceptance check (2026-11-19):**
  - 100% of served products are typed, and 99.3% have every required attribute: met.
  - Brand merges are applied, and all 105 `review.csv` rows are resolved: met.
  - The constants and the prompt's catalog list are gone: met.
  - Recall@5 is 0.958, against 0.874: met.
  - `dump.sql`, `backups/` and `ecommerce.db` are untouched (`git status`): met.
- **Phase 3 gate inputs:**
  - attribute recall@5 is 1.0, which passes;
  - Hinglish is 0.80 (4 of 5) and vague is 0.80 (8 of 10). Both are under the 0.85 bar, but on very small samples;
  - the renamed catalog was not measured on v2.

  Phase 3's plan-mode step decides.
