"""
Mocked tests for app/tools/product_tools.py.
No real database is needed — SessionLocal is patched with a mock session.
"""

import pytest
from unittest.mock import MagicMock, patch


def _make_product(
    product_id="PROD-001",
    name="Test Headphones",
    category="Electronics",
    subcategory="headphones",
    product_type="wireless",
    brand="Sony",
    price=5000,
    rating=4.5,
    description="Great headphones",
    attributes=None,
):
    p = MagicMock()
    p.product_id = product_id
    p.name = name
    p.category = category
    p.subcategory = subcategory
    p.type = product_type
    p.brand = brand
    p.price = price
    p.rating = rating
    p.description = description
    p.attributes = attributes or {}
    return p


def _make_review(review_id="REV-001", product_id="PROD-001", rating=4.5, text="Great!", reviewer="Alice"):
    r = MagicMock()
    r.review_id = review_id
    r.product_id = product_id
    r.rating = rating
    r.review_text = text
    r.reviewer = reviewer
    return r


def _make_spec(spec_id="SPEC-001", product_id="PROD-001", key="Color", value="Black"):
    s = MagicMock()
    s.spec_id = spec_id
    s.product_id = product_id
    s.spec_key = key
    s.spec_value = value
    return s


def _make_mock_db(query_result):
    """Return a mock DB session whose .query().filter*().limit().all() returns query_result."""
    mock_db = MagicMock()
    mock_chain = MagicMock()
    mock_db.query.return_value = mock_chain
    mock_chain.filter.return_value = mock_chain
    mock_chain.limit.return_value = mock_chain
    mock_chain.all.return_value = query_result
    mock_chain.first.return_value = query_result[0] if query_result else None
    return mock_db


class TestSearchProducts:
    def test_returns_list(self):
        product = _make_product()
        mock_db = _make_mock_db([product])

        with patch("app.tools.product_tools.SessionLocal", return_value=mock_db):
            from app.tools.product_tools import search_products

            results = search_products(category="Electronics")

        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0]["product_id"] == "PROD-001"
        assert results[0]["name"] == "Test Headphones"
        assert results[0]["rating"] == 4.5

    def test_no_results(self):
        mock_db = _make_mock_db([])

        with patch("app.tools.product_tools.SessionLocal", return_value=mock_db):
            from app.tools.product_tools import search_products

            results = search_products(category="Books")

        assert results == []

    def test_with_subcategory_filter(self):
        product = _make_product(subcategory="speakers")
        mock_db = _make_mock_db([product])

        with patch("app.tools.product_tools.SessionLocal", return_value=mock_db):
            from app.tools.product_tools import search_products

            results = search_products(category="Electronics", subcategory="speakers")

        assert len(results) == 1

    def test_with_brand_filter(self):
        product = _make_product(brand="boAt")
        mock_db = _make_mock_db([product])

        with patch("app.tools.product_tools.SessionLocal", return_value=mock_db):
            from app.tools.product_tools import search_products

            results = search_products(brand="boAt")

        assert results[0]["brand"] == "boAt"

    def test_with_price_range(self):
        product = _make_product(price=3000)
        mock_db = _make_mock_db([product])

        with patch("app.tools.product_tools.SessionLocal", return_value=mock_db):
            from app.tools.product_tools import search_products

            results = search_products(min_price=1000, max_price=5000)

        assert len(results) == 1

    def test_with_keywords(self):
        product = _make_product(name="Wireless Noise Cancelling Headphones")
        mock_db = _make_mock_db([product])

        with patch("app.tools.product_tools.SessionLocal", return_value=mock_db):
            from app.tools.product_tools import search_products

            results = search_products(keywords=["wireless", "noise"])

        assert len(results) == 1

    def test_with_product_type(self):
        product = _make_product(product_type="tws earbuds")
        mock_db = _make_mock_db([product])

        with patch("app.tools.product_tools.SessionLocal", return_value=mock_db):
            from app.tools.product_tools import search_products

            results = search_products(product_type="tws earbuds")

        assert results[0]["type"] == "tws earbuds"

    def test_rating_none_returns_none(self):
        """Products with no rating return None for rating field."""
        product = _make_product(rating=None)
        mock_db = _make_mock_db([product])

        with patch("app.tools.product_tools.SessionLocal", return_value=mock_db):
            from app.tools.product_tools import search_products

            results = search_products(category="Electronics")

        assert results[0]["rating"] is None

    def test_short_brand_not_split(self):
        """Brand words with 3 or fewer chars keep full brand as search term."""
        product = _make_product(brand="LG")
        mock_db = _make_mock_db([product])

        with patch("app.tools.product_tools.SessionLocal", return_value=mock_db):
            from app.tools.product_tools import search_products

            results = search_products(brand="LG")

        assert len(results) == 1


class TestGetProductById:
    def test_found(self):
        product = _make_product()
        mock_db = _make_mock_db([product])

        with patch("app.tools.product_tools.SessionLocal", return_value=mock_db):
            from app.tools.product_tools import get_product_by_id

            result = get_product_by_id("PROD-001")

        assert result is not None
        assert result["product_id"] == "PROD-001"

    def test_not_found(self):
        mock_db = _make_mock_db([])

        with patch("app.tools.product_tools.SessionLocal", return_value=mock_db):
            from app.tools.product_tools import get_product_by_id

            result = get_product_by_id("NONEXISTENT")

        assert result is None


class TestGetAllCategories:
    def test_returns_dict_with_expected_keys(self):
        from app.tools.product_tools import get_all_categories

        result = get_all_categories()

        assert isinstance(result, dict)
        assert "headphones" in result
        assert "laptop" in result
        assert "clothes" in result

    def test_headphones_has_form_factor_options(self):
        from app.tools.product_tools import get_all_categories

        result = get_all_categories()
        assert "form_factor_options" in result["headphones"]


class TestFetchReviews:
    def test_returns_reviews(self):
        review = _make_review()
        mock_db = _make_mock_db([review])

        with patch("app.tools.product_tools.SessionLocal", return_value=mock_db):
            from app.tools.product_tools import fetch_reviews

            result = fetch_reviews("PROD-001")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["review_id"] == "REV-001"
        assert result[0]["rating"] == 4.5
        assert result[0]["reviewer"] == "Alice"

    def test_returns_empty_for_no_reviews(self):
        mock_db = _make_mock_db([])

        with patch("app.tools.product_tools.SessionLocal", return_value=mock_db):
            from app.tools.product_tools import fetch_reviews

            result = fetch_reviews("PROD-999")

        assert result == []

    def test_multiple_reviews(self):
        reviews = [
            _make_review("REV-001", rating=5.0, text="Excellent!", reviewer="Bob"),
            _make_review("REV-002", rating=3.0, text="Average", reviewer="Carol"),
        ]
        mock_db = _make_mock_db(reviews)

        with patch("app.tools.product_tools.SessionLocal", return_value=mock_db):
            from app.tools.product_tools import fetch_reviews

            result = fetch_reviews("PROD-001")

        assert len(result) == 2


class TestFetchSpecs:
    def test_returns_specs(self):
        spec = _make_spec()
        mock_db = _make_mock_db([spec])

        with patch("app.tools.product_tools.SessionLocal", return_value=mock_db):
            from app.tools.product_tools import fetch_specs

            result = fetch_specs("PROD-001")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["spec_key"] == "Color"
        assert result[0]["spec_value"] == "Black"

    def test_returns_empty_for_no_specs(self):
        mock_db = _make_mock_db([])

        with patch("app.tools.product_tools.SessionLocal", return_value=mock_db):
            from app.tools.product_tools import fetch_specs

            result = fetch_specs("PROD-999")

        assert result == []
