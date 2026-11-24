#!/usr/bin/env python3
"""Turn the SQL label rules in eval/product_queries.json into frozen product-id labels.

    python eval/label_queries.py                 # one summary line per query (counts + examples)
    python eval/label_queries.py --show q041     # every product a query's rules match
    python eval/label_queries.py --write         # store the ids in each query's "expect"

Rules use raw product name, price and rating only (never category columns), so the frozen ids stay
valid when Phase 1 rebuilds the taxonomy. Products that are never sold (phones, laptops, tablets) are
excluded from every label. Writing resets "reviewed" to false for any query whose ids changed.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parent.parent
QUERIES_FILE = REPO / "eval" / "product_queries.json"
sys.path.insert(0, str(REPO))

from eval.run_baseline import DEFAULT_DB  # noqa: E402

# Never a correct answer: product kinds the store doesn't sell, wherever the catalog filed them.
NOT_SOLD = (
    "subcategory ~* '^(smartphones?|laptops?|tablets?)$' "
    "OR name ~* '\\d+\\s?gb ram|dual sim|\\mlaptop\\M.*\\m(core|ryzen|intel|celeron)\\M'"
)
MACRO = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")  # {NAME}; leaves regex counts such as {4} alone


def expand(rule: str, macros: dict, depth: int = 0) -> str:
    if depth > 6:
        raise ValueError(f"macro nesting too deep: {rule[:80]}")
    expanded = MACRO.sub(lambda m: macros[m.group(1)], rule)
    return expanded if expanded == rule else expand(expanded, macros, depth + 1)


def matches(conn, rule: str, macros: dict) -> list:
    sql = f"SELECT product_id, name, price FROM products WHERE NOT ({NOT_SOLD}) AND ({expand(rule, macros)}) ORDER BY product_id"
    return [tuple(r) for r in conn.execute(text(sql))]


def label(conn, query: dict, macros: dict) -> dict:
    rules = query.get("label") or {}
    exact = matches(conn, rules["exact"], macros) if rules.get("exact") else []
    exact_ids = {r[0] for r in exact}
    ok = [r for r in matches(conn, rules["ok"], macros) if r[0] not in exact_ids] if rules.get("ok") else []
    return {"exact": exact, "ok": ok}


def warnings(query: dict, found: dict) -> list:
    if query.get("expect_none"):
        return []
    tags = set(query.get("tags", []))
    out = []
    if "brand_missing" in tags and found["exact"]:
        out.append("brand_missing query has exact matches (is the brand carried after all?)")
    if "brand_missing" not in tags and not found["exact"]:
        out.append("no exact matches")
    if "brand_missing" in tags and not found["ok"]:
        out.append("brand_missing query has no ok matches")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=os.getenv("BASELINE_DATABASE_URL", DEFAULT_DB))
    parser.add_argument("--show", default="", help="query id: print every matching product")
    parser.add_argument("--write", action="store_true", help="store the matched ids in the file")
    args = parser.parse_args()

    data = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))
    macros = data["macros"]
    engine = create_engine(args.database_url)
    changed = 0
    problems = 0
    with engine.connect() as conn:
        for q in data["queries"]:
            if args.show and q["id"] != args.show:
                continue
            if q.get("expect_none"):
                print(f"{q['id']} | expect none | {q['query']}")
                continue
            found = label(conn, q, macros)
            if args.show:
                for kind in ("exact", "ok"):
                    print(f"--- {kind} ({len(found[kind])})")
                    for pid, name, price in found[kind]:
                        print(f"{pid} | {price:>6} | {name[:90]}")
                continue
            notes = warnings(q, found)
            problems += bool(notes)
            sample = " ;; ".join(n[:38] for _, n, _ in found["exact"][:3]) or "-"
            flag = f"  !! {'; '.join(notes)}" if notes else ""
            print(
                f"{q['id']} | {len(found['exact']):>3} exact | {len(found['ok']):>3} ok | {q['query'][:34]:<34} | {sample}{flag}"
            )
            if args.write:
                expect = {"exact": [r[0] for r in found["exact"]], "ok": [r[0] for r in found["ok"]]}
                if q.get("expect") != expect:
                    q["expect"] = expect
                    q["reviewed"] = False
                    changed += 1
    if args.write:
        QUERIES_FILE.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {QUERIES_FILE.relative_to(REPO)}: {changed} queries changed")
    if not args.show:
        print(f"{problems} queries with warnings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
