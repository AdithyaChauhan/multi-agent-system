"""The catalog as the app sees it at runtime: product types and brands, read from the database.

`scripts/enrich_catalog.py apply` seeds both tables from data/catalog/*.yaml (ADR 0005). Search
uses this module to turn the shopper's product word into a type ("geyser" -> water heater) and
their brand into a brand id ("redmi" -> Xiaomi). Nothing here calls a model.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from rapidfuzz import fuzz, process

from app.catalog.schema import norm, parse_type
from app.core.logger import get_logger

logger = get_logger("app.catalog.runtime")


def fold_brand(name: str) -> str:
    """Brand comparison key: case, spaces and trademark signs don't matter ("ZEBRONICS®" = "Zebronics")."""
    return re.sub(r"[^a-z0-9+]", "", str(name).lower())


@dataclass(frozen=True)
class Catalog:
    types: dict = field(default_factory=dict)  # name -> ProductType
    type_ids: dict = field(default_factory=dict)  # name -> id
    words: dict = field(default_factory=dict)  # product word -> (type name, kind or None)
    brands: dict = field(default_factory=dict)  # folded name or alias -> (id, canonical name)

    def resolve_product(self, word: Optional[str]) -> tuple:
        """(ProductType, kind) for a shopper's product word, or (None, None) if it names no type."""
        if not word:
            return None, None
        w = norm(word)
        for candidate in (w, w[:-1] if w.endswith("s") else w, w[:-2] if w.endswith("es") else w):
            if candidate in self.words:
                type_name, kind = self.words[candidate]
                return self.types[type_name], kind
        # A phrase made of known words: "neckband headphones" is headphones, kind neckband. Only types
        # we sell: "phone case" must not become "we don't carry phones".
        ptype, kind, _ = self._phrase(w, served=True)
        return ptype, kind

    def _phrase(self, text: str, served: bool) -> tuple:
        """(type, kind, word) named by known words inside the text; the longest word wins when they
        name different types ("tv remote cover" -> tv accessory)."""
        found = [
            (v, k)
            for k, v in self.words.items()
            if self.types[v[0]].served is served and re.search(rf"(?<![a-z0-9]){re.escape(k)}s?(?![a-z0-9])", text)
        ]
        if not found:
            return None, None, None
        (type_name, _), word = max(found, key=lambda f: len(f[1]))
        kinds = [kind for (t, kind), _ in found if t == type_name and kind]
        kind = kinds[0] if len(set(kinds)) == 1 else None
        return self.types[type_name], kind, word

    def product_in(self, message: str) -> tuple:
        """(type, kind, word) for a product the message itself names: a type we sell first, then one we
        don't ("iphone 15"). Used when the model's answer has no product, so code can still tell."""
        w = norm(message or "")
        found = self._phrase(w, served=True)
        return found if found[0] is not None else self._phrase(w, served=False)

    def resolve_brand(self, brand: Optional[str]) -> Optional[tuple]:
        """(id, canonical name) for a brand as the shopper wrote it, typos included, or None."""
        if not brand or not self.brands:
            return None
        key = fold_brand(brand)
        if key in self.brands:
            return self.brands[key]
        # Edit distance on folded names: "sonny" -> sony, "lojitec" -> logitech. Short keys only match
        # exactly, so a brand we don't carry isn't snapped to a different one.
        if len(key) < 4:
            return None
        match = process.extractOne(key, list(self.brands), scorer=fuzz.ratio, score_cutoff=80)
        return self.brands[match[0]] if match else None

    def type_lines(self) -> str:
        """One line per served type, with its kinds: the vocabulary shown to the extraction model."""
        return "\n".join(
            f"- {t.name}" + (f": {', '.join(t.kinds)}" if t.kinds else "")
            for t in self.types.values()
            if t.served and not t.name.startswith("other ")
        )


def build_catalog(type_rows: list, brand_rows: list) -> Catalog:
    """type_rows: (id, name, category, served, synonyms, suggestion, attribute_schema);
    brand_rows: (id, name, aliases)."""
    types, type_ids = {}, {}
    for tid, name, category, served, synonyms, suggestion, schema in type_rows:
        types[name] = parse_type(
            {
                "name": name,
                "category": category,
                "served": served,
                "synonyms": synonyms or [],
                "suggestion": suggestion,
                "attributes": schema or {},
            }
        )
        type_ids[name] = tid
    # Precedence when a word appears twice: type name > synonym > kind value (see product_types.yaml).
    words: dict = {}
    for t in types.values():
        for kind in t.kinds:
            words.setdefault(norm(kind), (t.name, kind))
    for t in types.values():
        for synonym in t.synonyms:
            words[norm(synonym)] = (t.name, None)
    for t in types.values():
        words[norm(t.name)] = (t.name, None)
    brands = {}
    for bid, name, aliases in brand_rows:
        for alias in (*(aliases or []), name):
            brands[fold_brand(alias)] = (bid, name)
    return Catalog(types=types, type_ids=type_ids, words=words, brands=brands)


_loaded: Optional[Catalog] = None


def get_catalog() -> Catalog:
    """Read once per process. Only a catalog that has types is kept: if the database isn't reachable
    yet (the app starting before Postgres), the next call tries again instead of running without a
    catalog until a restart."""
    global _loaded
    if _loaded is None:
        catalog = _read_catalog()
        if not catalog.types:
            return catalog
        _loaded = catalog
    return _loaded


def _read_catalog() -> Catalog:
    from app.db.database import SessionLocal
    from app.models.product import Brand, ProductType as ProductTypeRow

    db = SessionLocal()
    try:
        type_rows = db.query(
            ProductTypeRow.id,
            ProductTypeRow.name,
            ProductTypeRow.category,
            ProductTypeRow.served,
            ProductTypeRow.synonyms,
            ProductTypeRow.suggestion,
            ProductTypeRow.attribute_schema,
        ).order_by(ProductTypeRow.id)
        brand_rows = db.query(Brand.id, Brand.name, Brand.aliases)
        return build_catalog(list(type_rows), list(brand_rows))
    except Exception as exc:  # DB not reachable or not migrated
        logger.warning(f"catalog not loaded, will retry: {type(exc).__name__}")
        return Catalog()
    finally:
        db.close()


def catalog_blurb() -> str:
    """Short summary of what we sell, for "what do you have?" and "we don't carry" replies."""
    from sqlalchemy import func

    from app.db.database import SessionLocal
    from app.models.product import Product, ProductType as ProductTypeRow

    db = SessionLocal()
    try:
        rows = (
            db.query(ProductTypeRow.category, ProductTypeRow.name, func.count(Product.id))
            .join(Product, Product.type_id == ProductTypeRow.id)
            .filter(ProductTypeRow.served.is_(True))
            .group_by(ProductTypeRow.category, ProductTypeRow.name)
            .order_by(func.count(Product.id).desc())
            .all()
        )
    except Exception:  # pragma: no cover
        return ""
    finally:
        db.close()
    totals: dict = {}
    examples: dict = {}
    for category, name, count in rows:
        totals[category] = totals.get(category, 0) + count
        if not name.startswith("other ") and len(examples.setdefault(category, [])) < 3:
            examples[category].append(name)
    ordered = sorted(totals, key=totals.get, reverse=True)
    return "\n".join(f"• {c} ({totals[c]} products) — {', '.join(examples.get(c, []))}" for c in ordered)
