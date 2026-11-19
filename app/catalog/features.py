"""Match text against a product type's attribute schema, with no model call.

One matcher, two uses:
- offline, `scripts/enrich_catalog.py regex` reads easy facts out of product names ("43 inch",
  "1000W", "wireless") as hints and as a cross-check on the LLM;
- at search time, `features_to_filters` turns the shopper's feature words into attribute filters.

Everything is driven by data/catalog/product_types.yaml (values, aliases, units), so a new type or
alias needs no code change.
"""

import re
from functools import lru_cache
from typing import Optional

from app.catalog.schema import Attribute, ProductType, norm

# Units that convert into an attribute's canonical unit: (canonical, written) -> factor.
CONVERSIONS = {
    ("gb", "tb"): 1000,
    ("m", "ft"): 0.3048,
    ("m", "feet"): 0.3048,
    ("m", "foot"): 0.3048,
    ("m", "cm"): 0.01,
}
_NUMBER = r"(\d+(?:\.\d+)?)"
_NEGATION = re.compile(r"(?<![a-z])(without|non|no|not)(?![a-z])")


@lru_cache(maxsize=4096)
def _phrase(word: str) -> re.Pattern:
    """Whole-phrase pattern: 'wired' must not match inside 'wireless'."""
    return re.compile(r"(?<![a-z0-9])" + re.escape(norm(word)) + r"(?![a-z0-9])")


def _mentions(text: str, attr: Attribute) -> list:
    """Enum/list values whose name or an alias appears in the text.

    A match inside a longer match of another value doesn't count: "4K Ultra HD" is 4k, not also hd.
    """
    spans = {
        # "other" is a bucket, not a word to look for ("works with other apps" isn't os=other)
        value: [m.span() for w in (value if value != "other" else "", *aliases) if w for m in _phrase(w).finditer(text)]
        for value, aliases in attr.values.items()
    }
    spans = {v: s for v, s in spans.items() if s}

    def covered(span, value):
        return any(o[0] <= span[0] and span[1] <= o[1] and o != span for v, s in spans.items() if v != value for o in s)

    return [v for v, s in spans.items() if not all(covered(span, v) for span in s)]


def _number(text: str, attr: Attribute) -> Optional[float]:
    units = sorted({*attr.units, *(w for (c, w) in CONVERSIONS if c == attr.unit)}, key=len, reverse=True)
    # A number glued to letters is a model code ("S20", "MPK120L"), not a measurement; "500-Watt" is.
    pattern = (
        r"(?<![a-z0-9.])" + _NUMBER + r"\s*-?\s*(" + "|".join(re.escape(norm(u)) for u in units) + r")(?![a-z0-9])"
    )
    match = re.search(pattern, re.sub(r"(?<=\d),(?=\d{3}\b)", "", text))  # "1,500 w", but not "s20,m31"
    if not match:
        return None
    value = float(match.group(1)) * CONVERSIONS.get((attr.unit, match.group(2)), 1)
    if value <= 0:
        return None
    return int(round(value)) if attr.type == "int" else round(value, 2)


def match_attribute(attr: Attribute, text: str):
    """The value the text states for one attribute, or None if it says nothing or is ambiguous."""
    text = norm(text)
    if attr.type == "bool":
        hits = [m for a in attr.aliases for m in _phrase(a).finditer(text)]
        # "without voice function", "(non - voice)", "voice non-support": a negation next to it
        stated = [m for m in hits if not _NEGATION.search(text[max(0, m.start() - 12) : m.end() + 12])]
        return True if stated else None
    if attr.type in ("int", "float"):
        return _number(text, attr)
    found = _mentions(text, attr)
    if attr.type == "list":
        return sorted(found) or None
    return found[0] if len(found) == 1 else None  # two candidates: let the LLM or the shopper decide


def match_attributes(ptype: ProductType, text: str) -> dict:
    """Every attribute of the type that the text states unambiguously."""
    out = {}
    for name, attr in ptype.attributes.items():
        value = match_attribute(attr, text)
        if value is not None:
            out[name] = value
    return out


def attributes_match(attributes: Optional[dict], filters: dict) -> bool:
    """Does a product's attribute dict satisfy every filter? Numbers match within 5%; a list filter
    ("type c to lightning") needs all its values; a missing attribute never matches."""
    attributes = attributes or {}
    for key, wanted in filters.items():
        have = attributes.get(key)
        if have is None:
            return False
        if isinstance(wanted, list):
            if not set(wanted) <= set(have if isinstance(have, list) else [have]):
                return False
        elif isinstance(wanted, bool) or isinstance(have, bool):
            if have is not wanted:
                return False
        elif isinstance(wanted, (int, float)):
            if not isinstance(have, (int, float)) or abs(have - wanted) > 0.05 * wanted:
                return False
        elif have != wanted:
            return False
    return True


def features_to_filters(ptype: Optional[ProductType], features: list) -> tuple:
    """Shopper feature words -> (attribute filters, leftover keywords).

    A feature that names an attribute value becomes a filter ("wireless" -> connectivity=wireless,
    "43 inch" -> screen_inches=43). Anything else stays a keyword and is matched against the name.
    """
    filters: dict = {}
    leftovers: list = []
    for feature in features or []:
        matched = match_attributes(ptype, feature) if ptype else {}
        if not matched:
            leftovers.append(feature)
            continue
        for name, value in matched.items():
            if isinstance(value, list):
                filters[name] = sorted({*filters.get(name, []), *value})
            else:
                filters[name] = value
    return filters, leftovers
