"""Give every product a type, clean title, canonical brand and typed attributes (Phase 1, ADR 0005).

Steps, each resumable. Results are saved to data/catalog/enriched_products.jsonl after every batch:

    classify    LLM, ~25 product names per call -> type, kind, brand, title, confidence
    attributes  regex on name + description, then LLM, ~15 products of one type per call with only
                that type's schema; regex/LLM disagreements are kept for review
    review      write data/catalog/review.csv (low confidence, disagreements, missing required
                attributes); corrections typed into it are kept on the next run
    apply       seed product_types and brands from the YAML files, then write the jsonl plus the
                review.csv corrections into the database. No LLM calls: this is the restore step
    status      counts and token use so far

    python scripts/enrich_catalog.py classify --model openai/gpt-oss-120b --max-batches 2   # pilot
    python scripts/enrich_catalog.py attributes --model openai/gpt-oss-120b --token-budget 150000
    python scripts/enrich_catalog.py review
    python scripts/enrich_catalog.py apply

The database defaults to multi_agent_baseline (eval/run_baseline.py DEFAULT_DB); pass
--database-url to target another one. Groq's daily cap stops a step cleanly; run it again to resume.
"""

import argparse
import collections
import csv
import json
import random
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from eval.run_baseline import DEFAULT_DB, METER, configure_environment, install_meter, pace  # noqa: E402

CATALOG = REPO / "data" / "catalog"
ENRICHED = CATALOG / "enriched_products.jsonl"
REVIEW = CATALOG / "review.csv"
CONFIDENCE_THRESHOLD = 0.7
NAME_CHARS = 200
DESCRIPTION_CHARS = 250
REVIEW_FIELDS = [
    "product_id",
    "name",
    "old_subcategory",
    "type",
    "kind",
    "brand",
    "title",
    "attributes",
    "confidence",
    "reasons",
    "corrected_type",
    "corrected_brand",
    "corrected_title",
    "corrected_attributes",
    "reviewer",
]


# ── Records ──────────────────────────────────────────────────────────────────


def load_records(path: Path = ENRICHED) -> dict:
    if not path.exists():
        return {}
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {r["product_id"]: r for r in records}


def save_records(records: dict, path: Path = ENRICHED) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    lines = [json.dumps(records[k], ensure_ascii=False, sort_keys=True) for k in sorted(records)]
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for attempt in range(20):  # OneDrive briefly locks a file it is syncing (WinError 5)
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.5)


def fetch_products(session) -> list:
    from app.models.product import Product

    rows = session.query(
        Product.product_id, Product.name, Product.description, Product.subcategory, Product.brand
    ).order_by(Product.product_id)
    return [
        {"product_id": r[0], "name": r[1] or "", "description": r[2] or "", "subcategory": r[3], "brand": r[4]}
        for r in rows
    ]


def batches(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


# ── Classify ─────────────────────────────────────────────────────────────────


def type_lines(types: dict) -> str:
    """One line per type. No category headings: in the pilot (2026-11-18) the model copied them into
    the type field, and the category follows from the type anyway."""
    return "\n".join(f"- {t.name}" + (f": {', '.join(t.kinds)}" if t.kinds else "") for t in types.values())


def classify_schema():
    from pydantic import BaseModel, Field

    class Classified(BaseModel):
        n: int = Field(description="the product's number")
        product_type: str = Field(description="a type name from the list")
        kind: Optional[str] = Field(None, description="one of that type's kinds, or null")
        brand: Optional[str] = None
        title: str = ""
        confidence: float = 0.0

    class ClassifyBatch(BaseModel):
        """Labels for every numbered product."""

        items: List[Classified]

    return ClassifyBatch


def resolve_kind(ptype, text: Optional[str]) -> Optional[str]:
    """The type's kind a model's wording names: exact value or alias, else an alias inside it
    ("bagless vacuum" -> canister vacuum)."""
    from app.catalog.features import match_attribute

    attr = ptype.attributes.get("kind")
    if attr is None or not text:
        return None
    return attr.canonical(text) or match_attribute(attr, text)


def sync_corrections(records: dict, types: dict) -> int:
    """Bring review.csv type corrections and newly matchable kinds into the records, so the
    attributes step works on the right type. Returns how many records changed. No model calls."""
    import re

    changed = 0
    for pid, row in read_review().items():
        new_type = (row.get("corrected_type") or "").strip()
        rec = records.get(pid)
        if not rec or not (row.get("reviewer") or "").strip() or new_type not in types or rec.get("type") == new_type:
            continue
        corrected = json.loads(row["corrected_attributes"]) if row.get("corrected_attributes") else {}
        rec.update(type=new_type, kind=resolve_kind(types[new_type], corrected.get("kind")), classify_problems=[])
        for key in ("attributes", "attributes_done", "attributes_with", "attribute_problems", "missing_required"):
            rec.pop(key, None)
        changed += 1
    for rec in records.values():  # kinds the model wrote in its own words, now matched leniently
        problems = rec.get("classify_problems") or []
        match = next((re.match(r"unknown kind '(.+)' for ", p) for p in problems if p.startswith("unknown kind")), None)
        kind = resolve_kind(types[rec["type"]], match.group(1)) if match and rec.get("type") in types else None
        if kind:
            rec["kind"] = kind
            rec["classify_problems"] = [p for p in problems if not p.startswith("unknown kind")]
            if rec.get("attributes") is not None:
                rec["attributes"]["kind"] = kind
            changed += 1
    return changed


def resolve_classification(types: dict, item: dict) -> dict:
    """Validate one classify answer against the type list."""
    from app.catalog.schema import norm

    problems = []
    ptype = next((t for t in types.values() if norm(t.name) == norm(item.get("product_type") or "")), None)
    if ptype is None:
        problems.append(f"unknown type {item.get('product_type')!r}")
    kind = None
    if ptype is not None and "kind" in ptype.attributes:
        kind = resolve_kind(ptype, item.get("kind"))
        if kind is None and item.get("kind"):
            problems.append(f"unknown kind {item.get('kind')!r} for {ptype.name}")
    title = (item.get("title") or "").strip()
    if len(title) > 80:
        title = title[:80].rsplit(" ", 1)[0]
    try:
        confidence = max(0.0, min(1.0, float(item.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    brand = (item.get("brand") or "").strip() or None
    return {
        "type": ptype.name if ptype else None,
        "kind": kind,
        "brand": brand,
        "title": title or None,
        "confidence": round(confidence, 2),
        "classify_problems": problems,
    }


def run_classify(args, products: list, records: dict) -> None:
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.catalog.schema import load_types
    from app.core.llm import call_llm
    from app.core.prompt_loader import load_prompt

    types = load_types()
    system = load_prompt("catalog_classify", types=type_lines(types))
    schema = classify_schema()
    # Products without a type yet (new, or no usable answer last time) are tried again.
    todo = [p for p in products if args.redo or not records.get(p["product_id"], {}).get("type")]
    print(f"classify: {len(todo)} of {len(products)} products to do")
    for count, batch in enumerate(batches(todo, args.batch_size), 1):
        if args.max_batches and count > args.max_batches:
            break
        if stop_for_budget(args):
            break

        def ask(part):
            listing = "\n".join(f"{i}. {p['name'][:NAME_CHARS]}" for i, p in enumerate(part, 1))
            messages = [SystemMessage(content=system), HumanMessage(content=listing)]
            return call_llm("catalog", "classify", messages, schema)

        before = METER.tokens
        answers = ask_in_parts(batch, ask, args)
        if answers is STOP:
            break
        for i, product in enumerate(batch, 1):
            rec = records.setdefault(product["product_id"], {"product_id": product["product_id"]})
            if i in answers:
                rec.update(resolve_classification(types, answers[i]))
            else:
                rec.update({"type": None, "classify_problems": ["no answer from the model"], "confidence": 0.0})
            rec["classified_with"] = args.model
            rec.pop("attributes_done", None)  # a new type invalidates old attributes
        save_records(records)
        print(f"  batch {count}: {len(batch)} products, {METER.tokens - before} tokens (total {METER.tokens})")


# ── Attributes ───────────────────────────────────────────────────────────────


def schema_lines(ptype) -> str:
    lines = []
    for name, attr in ptype.attributes.items():
        if attr.type in ("enum", "list"):
            many = "one or more of" if attr.type == "list" else "one of"
            lines.append(f"- {name}: {many} {', '.join(attr.values)}")
        elif attr.type == "bool":
            lines.append(f"- {name}: true/false")
        else:
            lines.append(f"- {name}: number in {attr.unit}")
    return "\n".join(lines)


def attributes_schema(ptype):
    from pydantic import BaseModel, Field, create_model

    # Plain types only: Groq rejects a whole call when one value falls outside a JSON-schema enum,
    # so values are checked afterwards by validate_attributes.
    python_types = {"enum": Optional[str], "list": Optional[List[str]], "int": Optional[float]}
    python_types.update({"float": Optional[float], "bool": Optional[bool]})
    fields = {name: (python_types[a.type], None) for name, a in ptype.attributes.items()}
    Item = create_model("ProductAttributes", n=(int, Field(description="the product's number")), **fields)

    class AttributeBatch(BaseModel):
        """Attributes for every numbered product."""

        items: List[Item]

    return AttributeBatch


def merge_attributes(ptype, regex: dict, llm: dict, kind: Optional[str]) -> tuple:
    """LLM values win; regex fills gaps; disagreements are reported for review."""
    from app.catalog.schema import missing_required

    merged = dict(regex)
    problems = []
    for key, value in llm.items():
        if key in regex and regex[key] != value:
            problems.append(f"{key}: regex {regex[key]!r} vs llm {value!r}")
        merged[key] = value
    if kind and "kind" in ptype.attributes:
        merged["kind"] = kind  # classify decided the kind
    missing = missing_required(ptype, merged)
    return merged, problems, missing


def run_attributes(args, products: list, records: dict) -> None:
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.catalog.features import match_attributes
    from app.catalog.schema import load_types, validate_attributes
    from app.core.llm import call_llm
    from app.core.prompt_loader import load_prompt

    types = load_types()
    if sync_corrections(records, types):
        save_records(records)
    by_id = {p["product_id"]: p for p in products}
    groups: dict = collections.defaultdict(list)
    for pid, rec in sorted(records.items()):
        if rec.get("type") and pid in by_id and (args.redo or not rec.get("attributes_done")):
            if not args.types or rec["type"] in args.types:
                groups[rec["type"]].append(pid)
    print(f"attributes: {sum(map(len, groups.values()))} products in {len(groups)} types to do")

    count = 0
    for type_name, ids in groups.items():
        ptype = types[type_name]
        llm_attrs = {k: a for k, a in ptype.attributes.items() if k != "kind"}
        for pid in ids:  # regex is free: run it for every product of the type first
            p = by_id[pid]
            # Names only: descriptions mention other models and features ("HD" in a 4K TV's text).
            records[pid]["regex_attributes"] = match_attributes(ptype, p["name"])
        if not llm_attrs or args.no_llm:
            for pid in ids:
                rec = records[pid]
                if rec.get("attributes_with"):
                    # Never overwrite LLM values: regex only fills gaps, and the review flags are
                    # recomputed with the current matcher (no model call).
                    kept, _ = validate_attributes(ptype, rec.get("attributes"))  # re-checked against the current YAML
                    merged, problems, missing = merge_attributes(ptype, rec["regex_attributes"], kept, rec.get("kind"))
                    rec.update(attributes=merged, attribute_problems=problems, missing_required=missing)
                    continue
                merged, problems, missing = merge_attributes(ptype, rec["regex_attributes"], {}, rec.get("kind"))
                rec.update(attributes=merged, attribute_problems=problems, missing_required=missing)
                rec["attributes_done"] = not llm_attrs  # regex-only runs stay open for the LLM
            save_records(records)
            continue
        system = load_prompt("catalog_attributes", type=type_name, schema=schema_lines(ptype))
        schema = attributes_schema(ptype)
        for batch in batches(ids, args.batch_size):
            count += 1
            if (args.max_batches and count > args.max_batches) or stop_for_budget(args):
                save_records(records)
                return

            def ask(part):
                listing = "\n".join(
                    f"{i}. {by_id[pid]['name'][:NAME_CHARS]}"
                    f" | {by_id[pid]['description'][:DESCRIPTION_CHARS]}"
                    f" | Regex found: {json.dumps(records[pid]['regex_attributes'], ensure_ascii=False)}"
                    for i, pid in enumerate(part, 1)
                )
                messages = [SystemMessage(content=system), HumanMessage(content=listing)]
                return call_llm("catalog", "attributes", messages, schema)

            before = METER.tokens
            answers = ask_in_parts(batch, ask, args)
            if answers is STOP:
                save_records(records)
                return
            for i, pid in enumerate(batch, 1):
                rec = records[pid]
                llm, problems = validate_attributes(ptype, {k: v for k, v in answers.get(i, {}).items() if k != "n"})
                if i not in answers:
                    problems.append("no answer from the model")
                merged, disagreements, missing = merge_attributes(ptype, rec["regex_attributes"], llm, rec.get("kind"))
                rec.update(
                    attributes=merged,
                    attribute_problems=problems + disagreements,
                    missing_required=missing,
                    attributes_done=i in answers,
                    attributes_with=args.model,
                )
            save_records(records)
            print(f"  {type_name}: {len(batch)} products, {METER.tokens - before} tokens (total {METER.tokens})")


# ── Shared LLM plumbing ──────────────────────────────────────────────────────

STOP = object()


def stop_for_budget(args) -> bool:
    if args.token_budget and METER.tokens >= args.token_budget:
        print(f"token budget reached ({METER.tokens} >= {args.token_budget}); run again to resume")
        return True
    return False


def ask_in_parts(items: list, ask, args, offset: int = 0):
    """{1-based position in items: answer dict}, or STOP at the daily cap.

    `ask(part)` returns a batch model with numbered `items`, or None when Groq rejected the whole
    tool call (tool_use_failed, seen in the pilot). Then each half is asked separately, down to
    single products, so one bad answer doesn't lose the batch.
    """
    if not items:
        return {}
    pace(args.tpm_budget, args.call_estimate)
    result = call_with_cap(lambda: ask(items))
    if result is STOP:
        return STOP
    if result is not None:
        return {offset + it.n: it.model_dump() for it in result.items if 1 <= it.n <= len(items)}
    if len(items) == 1:
        return {}
    middle = len(items) // 2
    answers = {}
    for part, start in ((items[:middle], offset), (items[middle:], offset + middle)):
        got = ask_in_parts(part, ask, args, start)
        if got is STOP:
            return STOP
        answers.update(got)
    print(f"    split a rejected batch of {len(items)}: {len(answers)} answered")
    return answers


def call_with_cap(fn):
    try:
        return fn()
    except Exception as exc:  # stop cleanly at Groq's daily cap; anything else is a real error
        text = str(exc).lower()
        if type(exc).__name__ == "RateLimitError" and ("per day" in text or "tpd" in text or "rpd" in text):
            print("Groq daily token cap reached; progress is saved, run the same command again later")
            return STOP
        raise


# ── Review ───────────────────────────────────────────────────────────────────


def review_reasons(rec: dict) -> list:
    reasons = []
    if not rec.get("type"):
        reasons.append("no type")
    if (rec.get("confidence") or 0) < CONFIDENCE_THRESHOLD:
        reasons.append(f"confidence {rec.get('confidence')}")
    reasons += rec.get("classify_problems") or []
    reasons += rec.get("attribute_problems") or []
    if rec.get("missing_required"):
        reasons.append("missing required: " + ", ".join(rec["missing_required"]))
    return reasons


def read_review(path: Optional[Path] = None) -> dict:
    path = path or REVIEW
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {row["product_id"]: row for row in csv.DictReader(f)}


def run_review(args, products: list, records: dict) -> None:
    by_id = {p["product_id"]: p for p in products}
    old = read_review()
    rows = []
    for pid, rec in sorted(records.items()):
        reasons = review_reasons(rec)
        kept = old.get(pid, {})
        if not reasons and not kept.get("reviewer"):
            continue
        p = by_id.get(pid, {})
        row = {
            "product_id": pid,
            "name": (p.get("name") or "")[:150],
            "old_subcategory": p.get("subcategory") or "",
            "type": rec.get("type") or "",
            "kind": rec.get("kind") or "",
            "brand": rec.get("brand") or "",
            "title": rec.get("title") or "",
            "attributes": json.dumps(rec.get("attributes") or {}, ensure_ascii=False),
            "confidence": rec.get("confidence"),
            "reasons": "; ".join(reasons),
        }
        for field in REVIEW_FIELDS[10:]:
            row[field] = kept.get(field, "")
        rows.append(row)
    with REVIEW.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    open_rows = sum(1 for r in rows if not r["reviewer"])
    print(f"review.csv: {len(rows)} rows, {open_rows} not yet reviewed")
    if args.sample:
        served = [r for r in records.values() if r.get("type")]
        picked = random.Random(args.seed).sample(served, min(args.sample, len(served)))
        sample_path = CATALOG / "review_sample.csv"
        with sample_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["product_id", "name", "type", "kind", "brand", "title", "attributes", "ok"])
            for r in picked:
                name = (by_id.get(r["product_id"], {}).get("name") or "")[:150]
                attrs = json.dumps(r.get("attributes") or {}, ensure_ascii=False)
                writer.writerow(
                    [r["product_id"], name, r["type"], r.get("kind"), r.get("brand"), r.get("title"), attrs, ""]
                )
        print(f"{sample_path.name}: {len(picked)} random products for the spot check")


# ── Apply ────────────────────────────────────────────────────────────────────


def apply_corrections(records: dict, corrections: dict, types: dict) -> dict:
    """Records with review.csv corrections applied (reviewed rows only)."""
    from app.catalog.schema import validate_attributes

    out = {}
    for pid, rec in records.items():
        rec = dict(rec)
        row = corrections.get(pid) or {}
        reviewer = (row.get("reviewer") or "").strip().lower()
        if reviewer:
            if row.get("corrected_type") and row["corrected_type"].strip() != rec.get("type"):
                rec["type"] = row["corrected_type"].strip()
                if rec["type"] in types:  # keep only attributes that fit the new type
                    rec["attributes"], _ = validate_attributes(types[rec["type"]], rec.get("attributes"))
            if row.get("corrected_brand"):
                rec["brand"] = row["corrected_brand"].strip()
            if row.get("corrected_title"):
                rec["title"] = row["corrected_title"].strip()
            if row.get("corrected_attributes") and rec.get("type") in types:
                clean, _ = validate_attributes(types[rec["type"]], json.loads(row["corrected_attributes"]))
                rec["attributes"] = {**(rec.get("attributes") or {}), **clean}  # a fix to one detail keeps the rest
            rec["extracted_by"] = "human" if reviewer == "user" else "review"
            rec["confidence"] = 1.0
        out[pid] = rec
    return out


def canonical_brands(records: dict, merges: dict) -> tuple:
    """(brand per product_id, {canonical: aliases}) from the YAML merges plus case/trademark folding."""
    import re

    def fold(name: str) -> str:
        return re.sub(r"[^a-z0-9+]", "", name.lower())

    alias_to = {fold(a): canon for canon, aliases in merges.items() for a in (canon, *aliases)}
    spellings: dict = collections.defaultdict(collections.Counter)
    for rec in records.values():
        if rec.get("brand"):
            spellings[fold(rec["brand"])][rec["brand"]] += 1
    canonical = {}
    for key, counter in spellings.items():
        canonical[key] = alias_to.get(key) or counter.most_common(1)[0][0]
    aliases: dict = {canon: set(a) for canon, a in merges.items()}
    for key, counter in spellings.items():
        aliases.setdefault(canonical[key], set()).update(counter)
    per_product = {pid: canonical[fold(r["brand"])] if r.get("brand") else None for pid, r in records.items()}
    used = set(per_product.values())
    return per_product, {c: sorted(a - {c}) for c, a in aliases.items() if c in used}


def run_apply(args, records: dict, session=None) -> dict:
    from app.catalog.schema import load_brand_merges, load_types
    from app.models.product import Brand, Product, ProductType

    types = load_types()
    records = apply_corrections(records, read_review(), types)
    own_session = session is None
    if own_session:
        from app.db.database import SessionLocal

        session = SessionLocal()
    try:
        existing = {t.name: t for t in session.query(ProductType)}
        for t in types.values():
            row = existing.get(t.name) or ProductType(name=t.name)
            row.category, row.served, row.suggestion = t.category, t.served, t.suggestion
            row.synonyms, row.attribute_schema = list(t.synonyms), t.attribute_schema()
            session.add(row)
        session.flush()
        type_ids = {t.name: t.id for t in session.query(ProductType)}

        per_product, brand_aliases = canonical_brands(records, load_brand_merges())
        existing_brands = {b.name: b for b in session.query(Brand)}
        for name, aliases in brand_aliases.items():
            row = existing_brands.get(name) or Brand(name=name)
            row.aliases = aliases
            session.add(row)
        session.flush()
        brand_ids = {b.name: b.id for b in session.query(Brand)}

        updated = 0
        for product in session.query(Product).filter(Product.product_id.in_(list(records))):
            rec = records[product.product_id]
            product.type_id = type_ids.get(rec.get("type"))
            product.brand_id = brand_ids.get(per_product.get(product.product_id))
            product.title = rec.get("title")
            product.attributes = rec.get("attributes") or {}
            product.extracted_by = rec.get("extracted_by") or ("llm" if rec.get("classified_with") else "regex")
            product.confidence = rec.get("confidence")
            updated += 1

        # Types and brands no longer in use (removed from the YAML, merged away) go last.
        used_types = {r.get("type") for r in records.values()} | set(types)
        for row in session.query(ProductType):
            if row.name not in used_types:
                session.delete(row)
        for row in session.query(Brand):
            if row.name not in brand_aliases:
                session.query(Product).filter(Product.brand_id == row.id).update({"brand_id": None})
                session.delete(row)
        session.commit()
        summary = {"types": len(types), "brands": len(brand_aliases), "products": updated}
        print(f"applied: {summary}")
        return summary
    finally:
        if own_session:
            session.close()


# ── Status ───────────────────────────────────────────────────────────────────


def run_status(records: dict, products: list) -> None:
    typed = [r for r in records.values() if r.get("type")]
    print(
        f"products {len(products)} | classified {len(typed)} | attributes done "
        f"{sum(1 for r in typed if r.get('attributes_done'))} | need review "
        f"{sum(1 for r in records.values() if review_reasons(r))}"
    )
    print(collections.Counter(r["type"] for r in typed).most_common())


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["classify", "attributes", "review", "apply", "status"])
    parser.add_argument("--model", default="openai/gpt-oss-120b")
    parser.add_argument("--database-url", default=DEFAULT_DB)
    parser.add_argument("--env-file", help="read the Groq key from this file (e.g. .env.eval)")
    parser.add_argument("--batch-size", type=int, help="products per call (classify 25, attributes 15)")
    parser.add_argument("--max-batches", type=int, default=0, help="stop after N calls (pilot)")
    parser.add_argument("--token-budget", type=int, default=0, help="stop after this many tokens")
    parser.add_argument("--tpm-budget", type=int, default=7600)
    parser.add_argument("--call-estimate", type=int, default=4000, help="tokens to reserve per call")
    parser.add_argument("--types", nargs="*", help="attributes: only these types")
    parser.add_argument("--no-llm", action="store_true", help="attributes: regex only, no tokens")
    parser.add_argument("--redo", action="store_true", help="redo products already done")
    parser.add_argument("--sample", type=int, default=0, help="review: also write N random products")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--cassette", help="record LLM answers here (default: a temp file)")
    args = parser.parse_args(argv)
    args.trace = False
    args.batch_size = args.batch_size or (25 if args.step == "classify" else 15)

    import os

    configure_environment(args)
    if args.step in ("classify", "attributes"):
        os.environ["LLM_CASSETTE_MODE"] = "record"
        default = Path(tempfile.gettempdir()) / f"mas_enrich_{args.model.replace('/', '-')}.json"
        os.environ["LLM_CASSETTE_PATH"] = str(args.cassette or default)
        install_meter()

    from app.db.database import SessionLocal

    session = SessionLocal()
    try:
        products = fetch_products(session)
    finally:
        session.close()
    records = load_records()
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if args.step == "classify":
        run_classify(args, products, records)
    elif args.step == "attributes":
        run_attributes(args, products, records)
    elif args.step == "review":
        run_review(args, products, records)
    elif args.step == "apply":
        run_apply(args, records)
    else:
        run_status(records, products)
    if args.step in ("classify", "attributes"):
        print(f"{args.step} finished; started {started}; tokens this run {METER.tokens}")


if __name__ == "__main__":
    main()
