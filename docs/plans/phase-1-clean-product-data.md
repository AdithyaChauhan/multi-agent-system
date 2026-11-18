# Phase 1: Clean product data
- **Status:** Not started
- **Branch:** `phase-1-catalog`
- **Depends on:** Phase 0 (to measure the effect)
- **Decisions:** [0005](../decisions/0005-structured-product-catalog.md)

## Goal
Every product has a correct type, a clean title, one canonical brand and the key attributes for its type. Facts about products move out of prompts and Python constants into the database.

## Context
The 2026-11-18 audit is in ADR 0005. In short:
- `attributes` is empty on all 1,350 products;
- `type` is null on 72% of them;
- there are 91 mixed subcategories;
- specs live only inside long product names;
- tags are wrong in places, and brands are duplicated.

The largest current subcategories:

| Subcategory | Products |
|---|---|
| cable | 219 |
| tv | 83 |
| headphones | 66 |
| smartphone | 66 |
| smartwatch | 55 |
| room heater | 45 |
| water heater | 44 |
| mixer grinder | 40 |
| mouse | 37 |
| electric kettle | 33 |
| iron | 32 |

## Target schema (sketch, finalise in plan mode)
```
product_types  id, name, category, served bool, synonyms text[], attribute_schema jsonb
brands         id, name, aliases text[]
products       + type_id, brand_id, title (short, clean), attributes jsonb,
               extracted_by (regex|llm|human), confidence
               (name, description, tags stay as raw input)
```
Example attribute schemas. Keep 3–6 per type, and only fields shoppers actually filter on:
- **mouse:** connectivity [wired, wireless, bluetooth], dpi, silent
- **tv:** screen_inches, resolution [hd, fhd, 4k], smart, os
- **cable:** connector_a, connector_b, length_m, watts, braided
- **headphones:** form [over-ear, on-ear, in-ear, neckband, tws], connectivity, anc
- **room heater:** heater_type [fan, oil, halogen, ceramic, infrared], watts

## Tasks
- [ ] Plan mode: write the type list (30–40 types) and their schemas in `data/catalog/product_types.yaml`, and review it with the user before any extraction. A type with fewer than 5 products merges into its parent.
- [ ] Alembic migration that creates `product_types` and `brands` and adds the new columns to `products`. It must be non-destructive and reversible, with raw columns kept.
- [ ] `scripts/enrich_catalog.py`:
  1. Regex extraction for the easy fields: screen sizes, watts, lengths, resolution, and connectivity words.
  2. One structured LLM call per product, validated with the type's Pydantic schema. Fills the type, clean title and remaining attributes, records a confidence, can resume from checkpoints, and paces itself to the token budget.
  3. Rows below the confidence threshold go to `data/catalog/review.csv`.
  4. `--apply` writes the results from `data/catalog/enriched_products.jsonl`. A restore re-applies the file with no LLM calls.
- [ ] Brands: merge known duplicates ("Amazon" and "AmazonBasics", "MI" and "Xiaomi"). Ask the user whether Redmi is an alias or its own brand.
- [ ] Mark phones, laptops and tablets as `served = false`.
- [ ] Human review: 50 random products, plus every row in `review.csv`.
- [ ] Point v1 search at the new columns:
  - filter by `type_id` instead of subcategory and type strings;
  - use attributes for words like "wireless";
  - match brands through their aliases;
  - replace `PRODUCT_TYPES`, `SERVED_CATEGORIES`, `NOT_SERVED` and the catalog list in `app/prompts/product_extraction.md` with reads from the database.
- [ ] Measure with the Phase 0 harness: v1 on clean data against v1 before.
- [ ] Update the README restore steps (migration, then `enrich_catalog.py --apply`) and the tests.
- [ ] Fill in Results, update the ROADMAP and run `/handoff`.

## Acceptance criteria
- 100% of served products have a type, and at least 90% have every required attribute for their type (or an explicit "not applicable").
- No duplicate brands from the agreed alias list, and every `review.csv` row is resolved.
- The catalog constants and the catalog list in the extraction prompt are gone.
- Phase 0 recall@5 is not lower than before. Report the change.
- `dump.sql`, `backups/` and `ecommerce.db` are untouched.

## Risks and notes
- **The LLM pass costs about 0.8M tokens.** Run it on the gpt-oss models over several days, or once with a paid key. The script must resume after a quota error.
- **Over-detailed schemas** waste tokens and review time. If nobody filters on a field, leave it out.
- `enriched_products.jsonl` will be about 1 MB, which is fine for the repo.

## Results
_Fill in during the phase._
