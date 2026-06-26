"""
Unit tests for product_agent.py node functions.
Covers extract_preferences branches, ask_for_preferences,
handle_unavailable_products, do_search_products, broaden_search,
respond_no_results, format_recommendations, and routing helpers.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.state import AgentState


def _state(**kwargs):
    defaults = dict(
        user_message="show me headphones",
        user_id="u1",
        session_id="s1",
        conversation_history=[],
    )
    defaults.update(kwargs)
    return AgentState(**defaults)


def _mock_llm(content: str):
    m = MagicMock()
    m.invoke.return_value = MagicMock(
        content=content,
        response_metadata={"token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
    )
    m.bind_tools.return_value = m
    return m


# ── extract_preferences ───────────────────────────────────────────────────────


class TestExtractPreferencesBranches:
    def _run(self, llm_json: dict, user_message: str = "show me headphones", previous_prefs: dict = None):
        from app.agents.product_agent import extract_preferences

        state = _state(user_message=user_message, preferences=previous_prefs or {})
        mock_llm = _mock_llm(json.dumps(llm_json))
        with patch("app.agents.product_agent.load_prompt", return_value=(None, None)), patch(
            "app.agents.product_agent.llm", mock_llm
        ):
            return extract_preferences(state)

    def test_brand_only_override_clears_unavailable_flag(self):
        # LLM says unavailable + brand + no keywords, but we have prev subcategory
        # → should clear unavailable_request so the merge can inherit subcategory
        result = self._run(
            llm_json={
                "category": None,
                "subcategory": None,
                "type": None,
                "brand": "Bajaj",
                "max_price": None,
                "min_price": None,
                "min_rating": None,
                "keywords": [],
                "unavailable_request": True,
            },
            user_message="what about Bajaj",
            previous_prefs={
                "category": "Home & Kitchen",
                "subcategory": "mixer grinder",
                "brand": None,
                "keywords": [],
            },
        )
        assert result["preferences"]["unavailable_request"] is False

    def test_vague_browse_resets_all_preferences(self):
        # LLM extracts nothing at all → vague browse → full reset
        result = self._run(
            llm_json={
                "category": None,
                "subcategory": None,
                "type": None,
                "brand": None,
                "max_price": None,
                "min_price": None,
                "min_rating": None,
                "keywords": [],
                "unavailable_request": False,
            },
            user_message="show me something",
            previous_prefs={
                "category": "Electronics",
                "subcategory": "headphones",
                "max_price": 2000,
                "brand": "Sony",
                "keywords": [],
            },
        )
        prefs = result["preferences"]
        assert prefs["category"] is None
        assert prefs["subcategory"] is None
        assert prefs["max_price"] is None
        assert prefs["brand"] is None

    def test_subcategory_changed_resets_filters(self):
        # New subcategory ≠ prev → reset filter inheritance
        result = self._run(
            llm_json={
                "category": "Computers & Accessories",
                "subcategory": "monitor",
                "type": None,
                "brand": None,
                "max_price": None,
                "min_price": None,
                "min_rating": None,
                "keywords": [],
                "unavailable_request": False,
            },
            user_message="show me monitors",
            previous_prefs={
                "category": "Electronics",
                "subcategory": "headphones",
                "max_price": 2000,
                "brand": "Sony",
                "keywords": [],
            },
        )
        prefs = result["preferences"]
        assert prefs["subcategory"] == "monitor"

    def test_category_changed_resets_filters(self):
        result = self._run(
            llm_json={
                "category": "Home & Kitchen",
                "subcategory": "air fryer",
                "type": None,
                "brand": None,
                "max_price": None,
                "min_price": None,
                "min_rating": None,
                "keywords": [],
                "unavailable_request": False,
            },
            user_message="air fryer",
            previous_prefs={
                "category": "Electronics",
                "subcategory": "tv",
                "max_price": 50000,
                "brand": None,
                "keywords": [],
            },
        )
        prefs = result["preferences"]
        assert prefs["category"] == "Home & Kitchen"

    def test_same_subcategory_brand_refinement_inherits(self):
        # Brand refinement on same subcategory → inherits prev subcategory
        result = self._run(
            llm_json={
                "category": "Electronics",
                "subcategory": None,
                "type": None,
                "brand": "Sony",
                "max_price": None,
                "min_price": None,
                "min_rating": None,
                "keywords": [],
                "unavailable_request": False,
            },
            user_message="what about Sony",
            previous_prefs={
                "category": "Electronics",
                "subcategory": "headphones",
                "max_price": 2000,
                "brand": None,
                "keywords": [],
            },
        )
        prefs = result["preferences"]
        assert prefs["brand"] == "Sony"

    def test_code_fence_json_stripped(self):
        # LLM wraps response in ```json ... ``` — should still parse
        from app.agents.product_agent import extract_preferences

        raw = '```json\n{"category":"Electronics","subcategory":"tv","type":null,"brand":null,"max_price":null,"min_price":null,"min_rating":null,"keywords":[],"unavailable_request":false}\n```'
        state = _state(user_message="show me a tv")
        mock_llm = _mock_llm(raw)
        with patch("app.agents.product_agent.load_prompt", return_value=(None, None)), patch(
            "app.agents.product_agent.llm", mock_llm
        ):
            result = extract_preferences(state)
        assert result["preferences"]["subcategory"] == "tv"

    def test_invalid_json_falls_back_gracefully(self):
        from app.agents.product_agent import extract_preferences

        state = _state(user_message="show me something")
        mock_llm = _mock_llm("not valid json at all {{{{")
        with patch("app.agents.product_agent.load_prompt", return_value=(None, None)), patch(
            "app.agents.product_agent.llm", mock_llm
        ):
            result = extract_preferences(state)
        assert result["preferences"]["category"] is None


# ── ask_for_preferences ───────────────────────────────────────────────────────


class TestAskForPreferences:
    def test_returns_catalog_blurb(self):
        from app.agents.product_agent import ask_for_preferences

        result = ask_for_preferences(_state())
        assert "final_response" in result
        assert len(result["final_response"]) > 20


# ── handle_unavailable_products ───────────────────────────────────────────────


class TestHandleUnavailableProducts:
    def test_phone_keyword_shortcut(self):
        from app.agents.product_agent import handle_unavailable_products

        result = handle_unavailable_products(_state(user_message="I want an iPhone"))
        assert "smartphone" in result["final_response"].lower() or "phone" in result["final_response"].lower()
        assert "don't carry" in result["final_response"]

    def test_laptop_keyword_shortcut(self):
        from app.agents.product_agent import handle_unavailable_products

        result = handle_unavailable_products(_state(user_message="show me MacBook laptops"))
        assert "laptop" in result["final_response"].lower()

    def test_tablet_keyword_shortcut(self):
        from app.agents.product_agent import handle_unavailable_products

        result = handle_unavailable_products(_state(user_message="I need an iPad tablet"))
        assert "tablet" in result["final_response"].lower()

    def test_generic_falls_back_to_llm(self):
        from app.agents.product_agent import handle_unavailable_products

        mock_llm = _mock_llm("We don't carry furniture. Would you like to see our Home & Kitchen appliances?")
        with patch("app.agents.product_agent.llm", mock_llm):
            result = handle_unavailable_products(_state(user_message="I need a dining table"))
        assert "final_response" in result
        mock_llm.invoke.assert_called_once()


# ── do_search_products ────────────────────────────────────────────────────────


class TestDoSearchProducts:
    def test_passes_prefs_to_search_and_returns_results(self):
        from app.agents.product_agent import do_search_products

        mock_products = [{"product_id": "P1", "name": "boAt Headphone", "price": 1500}]
        state = _state(
            user_message="wireless headphones",
            preferences={
                "category": "Electronics",
                "subcategory": "headphones",
                "brand": None,
                "max_price": 2000,
                "keywords": ["wireless"],
            },
        )
        with patch("app.agents.product_agent.search_products", return_value=mock_products) as mock_search:
            result = do_search_products(state)
        assert result["search_results"] == mock_products
        mock_search.assert_called_once()

    def test_empty_results_propagated(self):
        from app.agents.product_agent import do_search_products

        state = _state(preferences={"category": "Electronics", "subcategory": "headphones"})
        with patch("app.agents.product_agent.search_products", return_value=[]):
            result = do_search_products(state)
        assert result["search_results"] == []


# ── broaden_search ────────────────────────────────────────────────────────────


class TestBroadenSearch:
    def _state_with_prefs(self, prefs, attempt=0, relaxed=None):
        return _state(
            preferences=prefs,
            broaden_attempt=attempt,
            relaxed_filters=relaxed or [],
        )

    def test_increases_max_price(self):
        from app.agents.product_agent import broaden_search

        state = self._state_with_prefs(
            {
                "category": "Electronics",
                "subcategory": "headphones",
                "type": None,
                "brand": None,
                "max_price": 2000,
                "min_rating": None,
                "keywords": [],
            }
        )
        result = broaden_search(state)
        assert result["preferences"]["max_price"] == 2500
        assert result["filters_exhausted"] is False

    def test_relaxes_brand_filter(self):
        from app.agents.product_agent import broaden_search

        # Skip type (None) and price_increase (no max_price), then relax brand
        state = self._state_with_prefs(
            {
                "category": "Electronics",
                "subcategory": "headphones",
                "type": None,
                "brand": "Sony",
                "max_price": None,
                "min_rating": None,
                "keywords": [],
            },
            attempt=2,  # skip type + price_increase, land on brand
        )
        result = broaden_search(state)
        assert result["preferences"]["brand"] is None
        assert "brand" in result["relaxed_filters"]

    def test_exhausted_when_no_specificity_remains(self):
        from app.agents.product_agent import broaden_search

        # After relaxation, only category remains → exhausted
        state = self._state_with_prefs(
            {
                "category": "Electronics",
                "subcategory": None,
                "type": None,
                "brand": None,
                "max_price": None,
                "min_rating": None,
                "keywords": [],
            },
            attempt=4,  # land on subcategory
        )
        result = broaden_search(state)
        assert result["filters_exhausted"] is True

    def test_exhausted_when_all_relaxation_steps_done(self):
        from app.agents.product_agent import broaden_search

        state = self._state_with_prefs(
            {
                "category": "Electronics",
                "subcategory": None,
                "type": None,
                "brand": None,
                "max_price": None,
                "min_rating": None,
                "keywords": [],
            },
            attempt=10,  # past end of RELAXATION_ORDER
        )
        result = broaden_search(state)
        assert result["filters_exhausted"] is True


# ── respond_no_results ────────────────────────────────────────────────────────


class TestRespondNoResults:
    def test_returns_message(self):
        from app.agents.product_agent import respond_no_results

        result = respond_no_results(_state())
        assert "couldn't find" in result["final_response"].lower()


# ── format_recommendations ────────────────────────────────────────────────────


class TestFormatRecommendations:
    def _ranked_products(self, n=2):
        return [
            {
                "product_id": f"P{i}",
                "name": f"Product {i}",
                "brand": "TestBrand",
                "price": 1000 * i,
                "rating": 4.0,
                "reviews": [{"rating": 4.5, "review_text": "Great product", "reviewer": "Alice"}],
            }
            for i in range(1, n + 1)
        ]

    def test_empty_ranked_returns_fallback(self):
        from app.agents.product_agent import format_recommendations

        result = format_recommendations(_state(ranked_products=[]))
        assert "could not rank" in result["final_response"].lower()

    def test_formats_products_with_reviews(self):
        from app.agents.product_agent import format_recommendations

        state = _state(ranked_products=self._ranked_products(2), relaxed_filters=[])
        result = format_recommendations(state)
        assert "Here are my top recommendations" in result["final_response"]
        assert "Product 1" in result["final_response"]
        assert "₹" in result["final_response"]

    def test_relaxed_filters_shown_in_prefix(self):
        from app.agents.product_agent import format_recommendations

        state = _state(ranked_products=self._ranked_products(1), relaxed_filters=["brand"])
        result = format_recommendations(state)
        assert "I relaxed" in result["final_response"] or "relaxed" in result["final_response"].lower()

    def test_keyword_relaxed_but_generic_shows_products(self):
        # "keywords" in relaxed, but original keywords are all GENERIC_WORDS → show products
        from app.agents.product_agent import format_recommendations

        state = _state(
            ranked_products=self._ranked_products(1),
            relaxed_filters=["keywords"],
            original_preferences={"keywords": ["best", "items"]},  # all generic
        )
        result = format_recommendations(state)
        assert "final_response" in result
        assert "Product 1" in result["final_response"]

    def test_no_reviews_product_still_formats(self):
        from app.agents.product_agent import format_recommendations

        products = [{"product_id": "P1", "name": "Widget", "brand": "Acme", "price": 500, "rating": 3.5, "reviews": []}]
        state = _state(ranked_products=products, relaxed_filters=[])
        result = format_recommendations(state)
        assert "Widget" in result["final_response"]


# ── routing ───────────────────────────────────────────────────────────────────


class TestProductRoutingFunctions:
    def test_route_after_broaden_retry(self):
        from app.agents.product_agent import route_after_broaden

        assert route_after_broaden(_state(filters_exhausted=False)) == "retry_search"

    def test_route_after_broaden_no_results(self):
        from app.agents.product_agent import route_after_broaden

        assert route_after_broaden(_state(filters_exhausted=True)) == "no_results"
