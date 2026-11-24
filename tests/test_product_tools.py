"""search_products over a real typed catalog in in-memory SQLite, seeded the way production is:
products, then `scripts/enrich_catalog.py apply` with enrichment records."""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.catalog.runtime import build_catalog
from app.db.database import Base
from app.models.product import Brand, Product, ProductType
from app.tools.product_tools import search_products
from scripts import enrich_catalog as ec

PRODUCTS = [
    # product_id, raw name, raw brand, price, rating, enrichment record
    (
        "TV1",
        "Mi 43 inch 4K Smart TV",
        "MI",
        25000,
        4.4,
        {
            "type": "tv",
            "brand": "MI",
            "title": "Mi 43 4K TV",
            "attributes": {"screen_inches": 43, "resolution": "4k", "smart": True},
        },
    ),
    (
        "TV2",
        "Redmi 32 inch HD TV",
        "Redmi",
        12000,
        4.2,
        {
            "type": "tv",
            "brand": "Redmi",
            "title": "Redmi 32 HD TV",
            "attributes": {"screen_inches": 32, "resolution": "hd", "smart": False},
        },
    ),
    (
        "TV3",
        "Sony 43 inch Full HD TV",
        "Sony",
        30000,
        4.6,
        {
            "type": "tv",
            "brand": "Sony",
            "title": "Sony 43 FHD TV",
            "attributes": {"screen_inches": 43, "resolution": "fhd", "smart": True},
        },
    ),
    (
        "M1",
        "Logitech M235 Wireless Mouse",
        "Logitech",
        700,
        4.3,
        {"type": "mouse", "brand": "Logitech", "title": "Logitech M235", "attributes": {"connectivity": "wireless"}},
    ),
    (
        "C1",
        "Wayona USB C to Lightning Cable 1m",
        "Wayona",
        300,
        4.0,
        {
            "type": "cable",
            "brand": "Wayona",
            "title": "Wayona C to Lightning",
            "attributes": {"connectors": ["lightning", "usb-c"], "length_m": 1.0},
        },
    ),
    (
        "P1",
        "Redmi Note 12 phone",
        "Redmi",
        15000,
        4.5,
        {"type": "phone", "brand": "Redmi", "title": "Redmi Note 12", "attributes": {}},
    ),
    ("X1", "Untyped gadget", "Acme", 100, 5.0, None),
]


@pytest.fixture(scope="module")
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add_all(Product(product_id=i, name=n, brand=b, price=p, rating=r) for i, n, b, p, r, _ in PRODUCTS)
    db.commit()
    records = {i: {"product_id": i, "confidence": 0.9, **rec} for i, _, _, _, _, rec in PRODUCTS if rec}
    with patch.object(ec, "read_review", return_value={}):
        ec.run_apply(None, records, session=db)
    yield db
    db.close()


@pytest.fixture(autouse=True)
def wired(session):
    types = [
        (t.id, t.name, t.category, t.served, t.synonyms, t.suggestion, t.attribute_schema)
        for t in session.query(ProductType)
    ]
    catalog = build_catalog(types, [(b.id, b.name, b.aliases) for b in session.query(Brand)])
    session.close = lambda: None  # search_products closes its session; keep the shared one open
    with patch("app.tools.product_tools.SessionLocal", return_value=session), patch(
        "app.tools.product_tools.get_catalog", return_value=catalog
    ):
        yield


def ids(results):
    return [r["product_id"] for r in results]


def test_type_filter_and_best_rated_first():
    assert ids(search_products(product_type="tv")) == ["TV3", "TV1", "TV2"]


def test_unsold_and_untyped_products_never_appear():
    assert "P1" not in ids(search_products(brand="redmi")) and "X1" not in ids(search_products())


def test_attribute_filters():
    assert ids(search_products(product_type="tv", attributes={"screen_inches": 43, "resolution": "4k"})) == ["TV1"]
    assert ids(search_products(product_type="tv", attributes={"smart": False})) == ["TV2"]
    assert ids(search_products(product_type="cable", attributes={"connectors": ["usb-c"]})) == ["C1"]
    assert search_products(product_type="mouse", attributes={"gaming": True}) == []  # unknown is not a match


def test_brand_aliases_typos_and_unknown_brands():
    assert ids(search_products(product_type="tv", brand="redmi")) == ["TV1", "TV2"]  # Redmi counts as Xiaomi
    assert ids(search_products(brand="sonny")) == ["TV3"]
    assert search_products(brand="Bose") == []


def test_result_shape_uses_clean_title_and_canonical_brand():
    tv = search_products(product_type="tv", brand="MI", limit=1)[0]
    assert (tv["title"], tv["brand"], tv["type"]) == ("Mi 43 4K TV", "Xiaomi", "tv")
    assert tv["name"] == "Mi 43 inch 4K Smart TV"  # raw name kept for the ranker and evals


def test_price_rating_keywords_and_limit():
    assert ids(search_products(product_type="tv", max_price=26000, min_price=20000)) == ["TV1"]
    assert ids(search_products(min_rating=4.5)) == ["TV3"]
    assert ids(search_products(keywords=["m235"])) == ["M1"]
    assert len(search_products(product_type="tv", limit=2)) == 2
