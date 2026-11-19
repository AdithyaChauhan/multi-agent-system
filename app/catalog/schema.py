"""Product types and brands, loaded from data/catalog/*.yaml (ADR 0005).

The YAML files are the versioned definition; `scripts/enrich_catalog.py apply` seeds them into the
product_types and brands tables, which the app reads at runtime. This module is shared by both sides:
it parses a type's attribute schema and validates attribute values against it.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

CATALOG_DIR = Path(__file__).resolve().parents[2] / "data" / "catalog"
ATTRIBUTE_TYPES = ("enum", "list", "int", "float", "bool")
_SPACES = re.compile(r"\s+")


def norm(text: str) -> str:
    """Lowercase and collapse whitespace: the form every vocabulary lookup uses."""
    return _SPACES.sub(" ", str(text).strip().lower())


@dataclass(frozen=True)
class Attribute:
    name: str
    type: str
    values: dict = field(default_factory=dict)  # enum/list: {value: (aliases...)}
    unit: Optional[str] = None  # int/float
    units: tuple = ()
    aliases: tuple = ()  # bool: words that mean true
    required: bool = False

    def canonical(self, word: str) -> Optional[str]:
        """The enum/list value a word names (the value itself or one of its aliases), else None."""
        w = norm(word)
        for value, aliases in self.values.items():
            if w == norm(value) or w in (norm(a) for a in aliases):
                return value
        return None

    def to_dict(self) -> dict:
        out: dict = {"type": self.type}
        if self.values:
            out["values"] = {v: list(a) for v, a in self.values.items()}
        if self.unit:
            out["unit"], out["units"] = self.unit, list(self.units)
        if self.aliases:
            out["aliases"] = list(self.aliases)
        if self.required:
            out["required"] = True
        return out


@dataclass(frozen=True)
class ProductType:
    name: str
    category: str
    served: bool = True
    synonyms: tuple = ()
    suggestion: Optional[str] = None
    attributes: dict = field(default_factory=dict)  # {name: Attribute}

    @property
    def kinds(self) -> tuple:
        """Values of the `kind` attribute that are product words (never `other`)."""
        kind = self.attributes.get("kind")
        return tuple(v for v in kind.values if v != "other") if kind else ()

    @property
    def required(self) -> tuple:
        return tuple(a.name for a in self.attributes.values() if a.required)

    def attribute_schema(self) -> dict:
        """JSON-serialisable form stored in product_types.attribute_schema."""
        return {name: a.to_dict() for name, a in self.attributes.items()}


def parse_attribute(name: str, spec: dict) -> Attribute:
    kind = spec.get("type")
    if kind not in ATTRIBUTE_TYPES:
        raise ValueError(f"attribute {name!r}: type must be one of {ATTRIBUTE_TYPES}, not {kind!r}")
    values = {str(v): tuple(a or ()) for v, a in (spec.get("values") or {}).items()}
    if kind in ("enum", "list") and not values:
        raise ValueError(f"attribute {name!r}: {kind} needs values")
    if kind in ("int", "float") and not (spec.get("unit") and spec.get("units")):
        raise ValueError(f"attribute {name!r}: {kind} needs unit and units")
    return Attribute(
        name=name,
        type=kind,
        values=values,
        unit=spec.get("unit"),
        units=tuple(spec.get("units") or ()),
        aliases=tuple(spec.get("aliases") or ()),
        required=bool(spec.get("required", False)),
    )


def parse_type(spec: dict) -> ProductType:
    attributes = {n: parse_attribute(n, s) for n, s in (spec.get("attributes") or {}).items()}
    return ProductType(
        name=spec["name"],
        category=spec["category"],
        served=bool(spec.get("served", True)),
        synonyms=tuple(spec.get("synonyms") or ()),
        suggestion=spec.get("suggestion"),
        attributes=attributes,
    )


def load_types(path: Optional[Path] = None) -> dict:
    """{name: ProductType} from product_types.yaml, in file order."""
    data = yaml.safe_load(Path(path or CATALOG_DIR / "product_types.yaml").read_text(encoding="utf-8"))
    types = [parse_type(t) for t in data["types"]]
    names = [t.name for t in types]
    if len(set(names)) != len(names):
        raise ValueError("product_types.yaml: duplicate type names")
    return {t.name: t for t in types}


def load_brand_merges(path: Optional[Path] = None) -> dict:
    """{canonical brand: (aliases...)} from brands.yaml."""
    data = yaml.safe_load(Path(path or CATALOG_DIR / "brands.yaml").read_text(encoding="utf-8"))
    return {name: tuple(aliases or ()) for name, aliases in (data.get("brands") or {}).items()}


@lru_cache(maxsize=1)
def catalog_types() -> dict:
    return load_types()


# ── Validation ───────────────────────────────────────────────────────────────


def _number(value: Any, kind: str) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        match = re.search(r"\d+(?:\.\d+)?", value.replace(",", ""))
        if not match:
            return None
        value = match.group()
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return int(round(number)) if kind == "int" else round(number, 2)


def _boolean(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and norm(value) in ("true", "yes", "1"):
        return True
    if isinstance(value, str) and norm(value) in ("false", "no", "0"):
        return False
    return None


def validate_attributes(ptype: ProductType, raw: Optional[dict]) -> tuple:
    """Clean a model's attribute dict against the type's schema.

    Returns (clean, problems): unknown keys and values that don't fit the schema are dropped and
    reported, so they can be sent to review instead of reaching the database.
    """
    clean: dict = {}
    problems: list = []
    for key, value in (raw or {}).items():
        attr = ptype.attributes.get(key)
        if attr is None:
            if value not in (None, "", [], False):
                problems.append(f"unknown attribute {key}")
            continue
        if value is None or value == "" or value == []:
            continue
        if attr.type == "enum":
            out = attr.canonical(value) if isinstance(value, str) else None
        elif attr.type == "list":
            items = value if isinstance(value, list) else [value]
            mapped = [attr.canonical(v) for v in items if isinstance(v, str)]
            out = sorted({m for m in mapped if m}) or None
            if out and len(out) != len(items):
                problems.append(f"{key}: dropped values outside the schema from {items}")
        elif attr.type == "bool":
            out = _boolean(value)
        else:
            out = _number(value, attr.type)
        if out is None:
            problems.append(f"{key}: {value!r} doesn't fit the schema")
        else:
            clean[key] = out
    return clean, problems


def missing_required(ptype: ProductType, attributes: dict) -> list:
    return [name for name in ptype.required if name not in attributes]
