"""Typed catalog (Phase 1): YAML schema, regex matcher, validation and the enrichment script's
pure steps. No model calls and no Postgres: apply runs against in-memory SQLite."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.catalog.features import features_to_filters, match_attribute, match_attributes
from app.catalog.schema import (
    load_brand_merges,
    load_types,
    missing_required,
    parse_attribute,
    validate_attributes,
)
from app.db.database import Base
from app.models.product import Brand, Product, ProductType
from scripts import enrich_catalog as ec

TYPES = load_types()


# ── YAML ─────────────────────────────────────────────────────────────────────


def test_catalog_yaml_is_consistent():
    assert 30 <= len(TYPES) <= 50
    not_served = {t.name for t in TYPES.values() if not t.served}
    assert not_served == {"phone", "laptop", "tablet"}
    for t in TYPES.values():
        if not t.served:
            assert t.suggestion in TYPES and TYPES[t.suggestion].served
        assert len(t.attributes) <= 6, t.name


def test_product_words_resolve_to_one_type():
    """A shopper's product word (type name, synonym or kind) must not point at two different types."""
    owners = {}
    for t in TYPES.values():
        for word in (t.name, *t.synonyms, *t.kinds):
            owners.setdefault(word.lower(), set()).add(t.name)
    clashes = {w: o for w, o in owners.items() if len(o) > 1}
    assert not clashes


def test_brand_merges_include_user_decisions():
    merges = load_brand_merges()
    assert "Redmi" in merges["Xiaomi"]  # user decision 2026-11-18
    assert "AmazonBasics" in merges["Amazon"]


def test_parse_attribute_rejects_bad_specs():
    with pytest.raises(ValueError):
        parse_attribute("x", {"type": "text"})
    with pytest.raises(ValueError):
        parse_attribute("x", {"type": "enum"})
    with pytest.raises(ValueError):
        parse_attribute("x", {"type": "int"})


# ── Regex matcher ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "type_name, text, expected",
    [
        (
            "tv",
            "Mi 80 cm (32 inches) 5A Series HD Ready Smart Android LED TV",
            {"screen_inches": 32, "resolution": "hd"},
        ),
        (
            "tv",
            "Samsung 138 cm (55 inches) Crystal 4K Ultra HD Smart LED TV",
            {"screen_inches": 55, "resolution": "4k"},
        ),
        ("mouse", "Dell WM118 Wireless Mouse, 2.4 Ghz with USB Nano Receiver", {"connectivity": "wireless"}),
        ("cable", "Duracell Type C To Type C 5A (100W) Braided Cable, 3.9 Feet", {"watts": 100, "braided": True}),
        ("storage", "SanDisk Ultra microSDXC UHS-I Card, 256GB", {"kind": "memory card", "capacity_gb": 256}),
        ("storage", "Seagate Expansion 1TB External HDD", {"capacity_gb": 1000}),
        ("water heater", "Havells Zella Flap Auto Immersion Rod 1500 Watts", {"heater_type": "immersion rod"}),
    ],
)
def test_match_attributes_reads_names(type_name, text, expected):
    got = match_attributes(TYPES[type_name], text)
    assert expected.items() <= got.items()


def test_matcher_respects_word_boundaries_and_ambiguity():
    connectivity = TYPES["mouse"].attributes["connectivity"]
    assert match_attribute(connectivity, "Logitech wireless mouse") == "wireless"
    assert match_attribute(connectivity, "wired and wireless combo") is None  # ambiguous: left to the LLM
    assert match_attribute(TYPES["tv"].attributes["resolution"], "4K Ultra HD Smart TV") == "4k"
    assert match_attribute(TYPES["cable"].attributes["length_m"], "cable 3.9 feet") == pytest.approx(1.19, 0.01)


def test_features_to_filters_splits_filters_and_keywords():
    filters, rest = features_to_filters(TYPES["tv"], ["43 inch", "4k", "smart", "bezel-less"])
    assert filters == {"screen_inches": 43, "resolution": "4k", "smart": True}
    assert rest == ["bezel-less"]
    filters, rest = features_to_filters(TYPES["cable"], ["type c to lightning", "braided"])
    assert filters == {"connectors": ["lightning", "usb-c"], "braided": True}
    assert features_to_filters(None, ["gaming"]) == ({}, ["gaming"])


# ── Validation ───────────────────────────────────────────────────────────────


def test_validate_attributes_cleans_and_reports():
    clean, problems = validate_attributes(
        TYPES["tv"],
        {"screen_inches": "43 inches", "resolution": "Ultra HD", "smart": "yes", "os": "plan9", "colour": "black"},
    )
    assert clean == {"screen_inches": 43, "resolution": "4k", "smart": True}
    assert any("os" in p for p in problems) and any("colour" in p for p in problems)
    assert missing_required(TYPES["tv"], {"screen_inches": 43}) == ["resolution"]


def test_validate_list_and_numbers():
    clean, problems = validate_attributes(TYPES["cable"], {"connectors": ["Type C", "usb-a", "toaster"], "length_m": 0})
    assert clean == {"connectors": ["usb-a", "usb-c"]}
    assert len(problems) == 2


# ── Enrichment steps (no LLM) ────────────────────────────────────────────────


def test_resolve_classification_validates_type_and_kind():
    rec = ec.resolve_classification(
        TYPES,
        {
            "product_type": "Storage",
            "kind": "pendrive",
            "brand": " SanDisk ",
            "title": "SanDisk Cruzer",
            "confidence": 1.4,
        },
    )
    assert rec["type"] == "storage" and rec["kind"] == "pen drive" and rec["brand"] == "SanDisk"
    assert rec["confidence"] == 1.0 and not rec["classify_problems"]
    bad = ec.resolve_classification(TYPES, {"product_type": "spaceship", "confidence": "high"})
    assert bad["type"] is None and bad["confidence"] == 0.0 and bad["classify_problems"]


def test_merge_attributes_reports_disagreement():
    merged, problems, missing = ec.merge_attributes(
        TYPES["tv"], {"screen_inches": 43, "smart": True}, {"screen_inches": 50, "resolution": "4k"}, None
    )
    assert merged == {"screen_inches": 50, "smart": True, "resolution": "4k"}
    assert problems and not missing


def test_review_reasons():
    assert ec.review_reasons({"type": "tv", "confidence": 0.9}) == []
    reasons = ec.review_reasons({"type": None, "confidence": 0.3, "missing_required": ["resolution"]})
    assert "no type" in reasons and any("missing" in r for r in reasons)


def test_canonical_brands_folds_case_and_merges():
    records = {
        "a": {"brand": "ZEBRONICS"},
        "b": {"brand": "Zebronics"},
        "c": {"brand": "Zebronics"},
        "d": {"brand": "Redmi"},
        "e": {"brand": "MI"},
        "f": {"brand": None},
    }
    per_product, aliases = ec.canonical_brands(records, {"Xiaomi": ("MI", "Redmi")})
    assert per_product == {
        "a": "Zebronics",
        "b": "Zebronics",
        "c": "Zebronics",
        "d": "Xiaomi",
        "e": "Xiaomi",
        "f": None,
    }
    assert aliases["Zebronics"] == ["ZEBRONICS"]
    assert set(aliases) == {"Zebronics", "Xiaomi"}


@pytest.fixture
def sqlite_session(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all(
        [
            Product(product_id="P1", name="Mi 32 inch Smart TV", price=15000, brand="MI"),
            Product(product_id="P2", name="Redmi 20W charger", price=500, brand="Redmi"),
        ]
    )
    session.commit()
    monkeypatch.setattr(ec, "REVIEW", tmp_path / "review.csv")
    yield session
    session.close()


def test_apply_is_idempotent_and_uses_review_corrections(sqlite_session, tmp_path):
    records = {
        "P1": {
            "product_id": "P1",
            "type": "tv",
            "brand": "MI",
            "title": "Mi 5A 32",
            "confidence": 0.9,
            "attributes": {"screen_inches": 32},
            "classified_with": "m",
        },
        "P2": {
            "product_id": "P2",
            "type": "cable",
            "brand": "Redmi",
            "title": "Redmi charger",
            "confidence": 0.4,
            "attributes": {},
            "classified_with": "m",
        },
    }
    with (tmp_path / "review.csv").open("w", encoding="utf-8", newline="") as f:
        import csv

        writer = csv.DictWriter(f, fieldnames=ec.REVIEW_FIELDS)
        writer.writeheader()
        writer.writerow(
            {
                "product_id": "P2",
                "corrected_type": "charger",
                "corrected_attributes": json.dumps({"kind": "wall charger", "watts": 20}),
                "reviewer": "user",
            }
        )

    first = ec.run_apply(None, records, session=sqlite_session)
    second = ec.run_apply(None, records, session=sqlite_session)
    assert first == second
    p1, p2 = (sqlite_session.query(Product).filter_by(product_id=i).one() for i in ("P1", "P2"))
    types = {t.id: t for t in sqlite_session.query(ProductType)}
    assert types[p1.type_id].name == "tv" and p1.extracted_by == "llm"
    assert types[p2.type_id].name == "charger" and p2.extracted_by == "human" and p2.confidence == 1.0
    assert p2.attributes == {"kind": "wall charger", "watts": 20}
    brands = sqlite_session.query(Brand).all()
    assert [b.name for b in brands] == ["Xiaomi"] and p1.brand_id == p2.brand_id
    assert sqlite_session.query(ProductType).count() == len(TYPES)


def test_ask_in_parts_splits_a_rejected_batch(monkeypatch):
    """Groq sometimes rejects a whole batch (tool_use_failed): each half is asked again."""
    from types import SimpleNamespace

    monkeypatch.setattr(ec, "pace", lambda *a: 0)
    calls = []

    def ask(part):
        calls.append(len(part))
        if len(part) > 2 or "bad" in part:
            return None
        return SimpleNamespace(
            items=[SimpleNamespace(n=i, model_dump=lambda p=p: {"name": p}) for i, p in enumerate(part, 1)]
        )

    args = SimpleNamespace(tpm_budget=7600, call_estimate=1)
    answers = ec.ask_in_parts(["a", "b", "c", "bad", "e"], ask, args)
    assert answers == {1: {"name": "a"}, 2: {"name": "b"}, 3: {"name": "c"}, 5: {"name": "e"}}
    assert calls[0] == 5


def test_other_is_a_bucket_not_a_word():
    os_attr = TYPES["tv"].attributes["os"]
    assert match_attribute(os_attr, "Smart TV with Netflix and other apps") is None
    assert match_attribute(os_attr, "VIDAA smart tv") == "other"


def test_resolve_kind_accepts_the_models_own_wording():
    assert ec.resolve_kind(TYPES["vacuum cleaner"], "bagless vacuum") == "canister vacuum"
    assert ec.resolve_kind(TYPES["stationery"], "roller ball pen") == "roller pen"
    assert ec.resolve_kind(TYPES["fan"], "spaceship") is None
    assert ec.resolve_kind(TYPES["tv"], "anything") is None  # tv has no kinds


def test_sync_corrections_retypes_and_rematches_kinds(monkeypatch):
    review = {"A": {"corrected_type": "mixer grinder", "reviewer": "claude", "corrected_attributes": ""}}
    monkeypatch.setattr(ec, "read_review", lambda: review)
    records = {
        "A": {"type": "blender", "kind": None, "attributes": {"watts": 900}, "attributes_done": True},
        "B": {
            "type": "fan",
            "kind": None,
            "attributes": {},
            "classify_problems": ["unknown kind 'exhaust fan' for fan"],
        },
    }
    assert ec.sync_corrections(records, TYPES) == 2
    assert records["A"]["type"] == "mixer grinder" and "attributes_done" not in records["A"]
    assert records["B"]["kind"] == "exhaust fan" and records["B"]["attributes"] == {"kind": "exhaust fan"}
    assert records["B"]["classify_problems"] == []


def test_model_codes_and_negations_are_not_facts():
    cable, remote = TYPES["cable"], TYPES["tv remote"]
    assert match_attribute(cable.attributes["length_m"], "for Galaxy S20,M31S,A73 M51 (1M, Grey)") == 1.0
    assert match_attribute(TYPES["electric kettle"].attributes["capacity_l"], "iBELL MPK120L 1.2 Litre") == 1.2
    assert match_attribute(TYPES["mixer grinder"].attributes["watts"], "USHA RapidMix 500-Watt") == 500
    assert match_attribute(TYPES["room heater"].attributes["watts"], "heater 1,500 W") == 1500
    assert match_attribute(remote.attributes["voice"], "Remote (Without Voice Function)") is None
    assert match_attribute(remote.attributes["voice"], "Remote (Mouse & Voice Non-Support)") is None
    assert match_attribute(remote.attributes["voice"], "Bluetooth Voice Remote") is True


def test_product_in_prefers_types_we_sell(yaml_catalog):
    ptype, kind, word = yaml_catalog.product_in("breville electric kettle")
    assert (ptype.name, word) == ("electric kettle", "electric kettle")
    ptype, _, word = yaml_catalog.product_in("iphone 15")
    assert (ptype.name, ptype.served, word) == ("phone", False, "iphone")
    assert yaml_catalog.product_in("under 2000") == (None, None, None)


def test_an_unreachable_database_is_not_cached(monkeypatch):
    from tests.conftest import build_test_catalog

    import app.catalog.runtime as rt

    monkeypatch.setattr(rt, "_loaded", None)
    reads = iter([rt.Catalog(), build_test_catalog()])
    monkeypatch.setattr(rt, "_read_catalog", lambda: next(reads))
    assert not rt.get_catalog().types  # database still starting
    loaded = rt.get_catalog()  # next call reads again
    assert loaded.types and rt.get_catalog() is loaded  # and keeps it from then on
