# 0005. Typed product catalog: types, brands and attributes as data
- **Status:** Accepted
- **Date:** 2026-11-18

## Context
Audit of `products` in `multi_agent_baseline` on 2026-11-18 (1,350 rows of Amazon India listings):
- `attributes`, meant for type-specific fields, is empty on all 1,350 rows.
- `type` is null on 977 rows (72%), and "smart tv" is applied to TVs that aren't smart.
- There are 91 subcategories in two mixed vocabularies: "mouse" and "tv" sit next to "Accessories", "Cameras & Photography" and "CarAccessories". Some are duplicates ("microphone" and "Microphones"), and 29 have 3 items or fewer.
- Specs exist only inside product names, which average 127 characters (855 are over 100): wattage, cable length, screen size, connectivity.
- Tags are unreliable (a micro-USB cable is tagged "bluetooth"), and brands are duplicated ("MI" and "Redmi", "Amazon" and "AmazonBasics").
- Cables are 16% of the catalog. Phones, laptops and tablets are present but not sold.

Because the data doesn't say what a product is or what features it has, the code compensates:
- `PRODUCT_TYPES`, `SERVED_CATEGORIES` and `NOT_SERVED` constants;
- the catalog list in the extraction prompt;
- keyword matching for words like "wireless";
- the relaxation loop;
- an LLM ranker that removes items of the wrong kind.

## Decision
- New tables: `product_types` (name, category, `served`, synonyms, `attribute_schema`) and `brands` (name, aliases).
- `products` gains:
  - `type_id` and `brand_id`;
  - a short, clean `title`;
  - `attributes` as JSONB, validated against the type's schema;
  - provenance: `extracted_by` (regex, llm or human) and `confidence`.

  The raw name and description stay.
- About 30–40 types with 3–6 attributes each. A type with fewer than 5 products merges into its parent.
- One offline enrichment run fills these fields: regex first, then one structured LLM call per product, with low-confidence rows sent to a CSV for human review. The output is saved as a versioned file, so a fresh restore re-applies it without LLM calls.
- Type schemas are defined in a versioned file in the repo and seeded into the database. At runtime the database is the source of truth.

## Consequences
- The catalog constants and the catalog list in prompts can go. "Wireless" becomes an attribute filter.
- Restoring the data needs the migration plus the enrichment apply step.
- One-time cost of about 0.8M tokens for the LLM pass: run it on the gpt-oss models over more than one day, or once with a paid key.

## Alternatives considered
- Keep compensating in prompts and code: rejected, because that caps search quality.
- Fully normalised attribute tables (EAV): rejected. JSONB validated against a per-type schema is simpler at this size.
