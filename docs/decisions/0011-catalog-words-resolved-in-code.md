# 0011. The model names the product; code resolves it against the catalog
- **Status:** Accepted, implemented (Phase 1)
- **Date:** 2026-11-19

## Context
Before Phase 1, the extraction prompt listed the catalog. Python constants (`PRODUCT_TYPES`, `SERVED_CATEGORIES`, `NOT_SERVED`, `EXCLUDED_SUBCATEGORIES`) decided what we sell, and the model's own "not carried" answer was trusted. The result: wrong "we don't carry" replies for fitness trackers, laptop stands and geysers, and a 9.5% empty rate (Phase 0). Once Phase 1 typed the catalog (0005), the database could answer these questions itself.

## Decision
- The extraction model returns only plain words:
  - `product` (the shopper's product word);
  - `features` (words like "wireless" or "43 inch");
  - brand, price and rating.
  
  It sees one line per served type, read from `product_types`. No schemas or attribute lists go into the prompt.
- Code (`app/catalog/runtime.py`, `app/catalog/features.py`) resolves the words:
  - the product word becomes a type and a kind. Precedence is type name, then synonym, then kind value. A phrase made of known words resolves to served types only;
  - feature words become attribute filters, using the values, aliases and units in `data/catalog/product_types.yaml`. Words that don't match stay keywords;
  - brands resolve through aliases, then a fuzzy match on names of 4 or more characters.
- **The catalog decides "not carried", not the model.** A `served: false` type gets its YAML suggestion. If the model says "not carried" for a type we sell, it's overruled.
- Deviations from 0005, all measured in the Phase 1 plan:
  - 47 types instead of 30–40;
  - the LLM ran in batches (25 products per classify call, 15 per attributes call), not one call per product. That's about 350K tokens instead of 0.8M.

## Consequences
- A new type, alias or unit is a YAML edit plus `enrich_catalog.py apply`. Prompts and code don't change.
- Search quality now depends on the YAML vocabulary. A missing alias shows up as a keyword miss, so the fix goes in the data (0010).
- Measured: recall@5 0.874 → 0.958 and attribute queries 0.75 → 1.0, with the same tokens per query (Phase 1 Results).

## Alternatives considered
- Give the model the attribute schema and let it return filters: rejected. It needs a longer prompt (against 0010), and Groq rejects a whole call when an enum value is off-list.
- Keep the catalog list in the prompt: rejected. It goes stale when the catalog changes, and it was the cause of the wrong refusals.
