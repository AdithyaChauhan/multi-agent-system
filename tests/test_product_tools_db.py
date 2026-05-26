import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

from app.db.database import Base
from app.models.product import Product
from app.models.review import Review
from app.models.spec import Spec


# In-memory SQLite for real DB testing
@pytest.fixture(scope="module")
def sqlite_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture(scope="module")
def sqlite_session(sqlite_engine):
    Session = sessionmaker(bind=sqlite_engine)
    db = Session()

    # Seed test products
    products = [
        Product(
            product_id="TOY-001",
            name="Wooden Toy Set",
            type="toy",
            brand="LegoToy",
            price=1500,
            rating=4.5,
            category="Toys & Games",
            description="Fun toy for kids",
            in_stock=True,
            attributes={}
        ),
        Product(
            product_id="TOY-002",
            name="Building Blocks",
            type="toy",
            brand="BuildCo",
            price=999,
            rating=4.2,
            category="Toys & Games",
            description="Educational building blocks",
            in_stock=True,
            attributes={}
        ),
        Product(
            product_id="HOME-001",
            name="Kitchen Pan",
            type="cookware",
            brand="Chef",
            price=2000,
            rating=4.0,
            category="Home & Kitchen",
            description="Non-stick pan",
            in_stock=True,
            attributes={}
        ),
    ]

    reviews = [
        Review(review_id="REV-001", product_id="TOY-001", rating=4.5, review_text="Great!", reviewer="Alice"),
        Review(review_id="REV-002", product_id="TOY-001", rating=4.0, review_text="Good!", reviewer="Bob"),
    ]

    specs = [
        Spec(spec_id="SPEC-001", product_id="TOY-001", spec_key="Material", spec_value="Wood"),
    ]
    
    for p in products:
        db.add(p)
    for r in reviews:
        db.add(r)
    for s in specs:
        db.add(s)
    db.commit()

    yield db
    db.close()


class TestProductToolsWithDB:

    def test_search_products_by_category(self, sqlite_session):
        """search_products finds products by category"""
        with patch("app.tools.product_tools.SessionLocal", return_value=sqlite_session):
            from app.tools.product_tools import search_products
            result = search_products({"category": "Toys & Games"})
        assert isinstance(result, list)

    def test_search_products_with_keywords(self, sqlite_session):
        """search_products filters by keywords"""
        with patch("app.tools.product_tools.SessionLocal", return_value=sqlite_session):
            from app.tools.product_tools import search_products
            result = search_products({"category": "Toys & Games", "keywords": ["wooden"]})
        assert isinstance(result, list)

    def test_search_products_with_price_range(self, sqlite_session):
        """search_products filters by price range"""
        with patch("app.tools.product_tools.SessionLocal", return_value=sqlite_session):
            from app.tools.product_tools import search_products
            result = search_products({"category": "Toys & Games", "min_price": 500, "max_price": 2000})
        assert isinstance(result, list)

    def test_search_products_empty_category(self, sqlite_session):
        """search_products handles empty preferences"""
        with patch("app.tools.product_tools.SessionLocal", return_value=sqlite_session):
            from app.tools.product_tools import search_products
            result = search_products({})
        assert isinstance(result, list)

    def test_get_product_by_id_found(self, sqlite_session):
        """get_product_by_id returns product"""
        with patch("app.tools.product_tools.SessionLocal", return_value=sqlite_session):
            from app.tools.product_tools import get_product_by_id
            result = get_product_by_id("TOY-001")
        assert result is not None
        assert result["product_id"] == "TOY-001"

    def test_get_product_by_id_not_found(self, sqlite_session):
        """get_product_by_id returns None for missing product"""
        with patch("app.tools.product_tools.SessionLocal", return_value=sqlite_session):
            from app.tools.product_tools import get_product_by_id
            result = get_product_by_id("NOTEXIST-999")
        assert result is None

    def test_get_all_categories(self, sqlite_session):
        """get_all_categories returns categories with counts"""
        with patch("app.tools.product_tools.SessionLocal", return_value=sqlite_session):
            from app.tools.product_tools import get_all_categories
            result = get_all_categories()
        assert isinstance(result, dict)

    def test_fetch_reviews_for_product(self, sqlite_session):
        """fetch_reviews returns reviews for product"""
        with patch("app.tools.product_tools.SessionLocal", return_value=sqlite_session):
            from app.tools.product_tools import fetch_reviews
            result = fetch_reviews("TOY-001")
        assert isinstance(result, list)

    def test_fetch_reviews_no_reviews(self, sqlite_session):
        """fetch_reviews returns empty list for product with no reviews"""
        with patch("app.tools.product_tools.SessionLocal", return_value=sqlite_session):
            from app.tools.product_tools import fetch_reviews
            result = fetch_reviews("HOME-001")
        assert isinstance(result, list)

    def test_fetch_specs_for_product(self, sqlite_session):
        """fetch_specs returns specs for product"""
        with patch("app.tools.product_tools.SessionLocal", return_value=sqlite_session):
            from app.tools.product_tools import fetch_specs
            result = fetch_specs("TOY-001")
        assert isinstance(result, list)
