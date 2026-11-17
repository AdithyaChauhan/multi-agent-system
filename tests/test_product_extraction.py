"""Product extraction: one structured call returns the complete filters; the code only validates."""

from unittest.mock import patch

import pytest

from app.agents.state import AgentState

CATALOG = {
    "Computers & Accessories": ["adapter", "laptop bag", "mouse"],
    "Electronics": ["adapter", "headphones", "tv"],
    "Office Products": ["office electronics"],
}


@pytest.fixture(autouse=True)
def fake_catalog():
    import app.agents.product_agent as pa

    pa.search_schema.cache_clear()
    with patch.object(pa, "load_catalog", return_value=CATALOG):
        yield pa
    pa.search_schema.cache_clear()


def _state(message, previous=None):
    return AgentState(user_message=message, user_id="anon-1", session_id="s1", preferences=previous or {})


def _extract(pa, message, model_output, previous=None):
    schema = pa.search_schema()
    parsed = schema.model_validate(model_output) if model_output is not None else None
    with patch.object(pa, "call_llm", return_value=parsed) as call:
        result = pa.extract_preferences(_state(message, previous))
    return result, call


class TestSchema:
    def test_enum_values_are_matched_case_insensitively(self, fake_catalog):
        s = fake_catalog.search_schema().model_validate({"subcategory": "TV", "category": "electronics"})
        assert (s.subcategory, s.category) == ("tv", "Electronics")

    def test_values_outside_the_catalog_become_null(self, fake_catalog):
        s = fake_catalog.search_schema().model_validate(
            {"subcategory": "smartinputs", "type": "gaming", "suggestion": "gaming chairs", "keywords": None}
        )
        assert (s.subcategory, s.type, s.suggestion, s.keywords) == (None, None, None, [])

    def test_suggestion_must_be_a_catalog_subcategory(self, fake_catalog):
        assert fake_catalog.search_schema().model_validate({"suggestion": "Laptop Bag"}).suggestion == "laptop bag"


class TestExtractPreferences:
    def test_previous_filters_are_sent_and_complete_filters_returned(self, fake_catalog):
        previous = {"category": "Electronics", "subcategory": "tv", "max_price": 15000, "brand": None}
        out = {"category": "Electronics", "subcategory": "tv", "brand": "Samsung", "max_price": 15000}
        result, call = _extract(fake_catalog, "what about Samsung", out, previous)

        human = call.call_args.args[2][1].content
        assert '"subcategory": "tv"' in human and '"brand"' not in human  # only non-empty previous filters
        assert "what about Samsung" in human
        prefs = result["preferences"]
        assert (prefs["subcategory"], prefs["brand"], prefs["max_price"]) == ("tv", "Samsung", 15000)
        assert result["original_preferences"] == prefs
        assert result["not_carried"] is None

    def test_category_comes_from_the_catalog_not_the_model(self, fake_catalog):
        result, _ = _extract(fake_catalog, "calculator", {"category": "Electronics", "subcategory": "office electronics"})
        assert result["preferences"]["category"] == "Office Products"

    def test_shared_subcategory_keeps_a_matching_category(self, fake_catalog):
        result, _ = _extract(fake_catalog, "usb adapter", {"category": "Electronics", "subcategory": "adapter"})
        assert result["preferences"]["category"] == "Electronics"

    def test_not_carried_is_reported(self, fake_catalog):
        result, _ = _extract(fake_catalog, "laptop", {"not_carried": "laptops", "suggestion": "laptop bag"})
        assert result["not_carried"] == {"item": "laptops", "suggestion": "laptop bag"}

    def test_unparseable_reply_gives_empty_filters(self, fake_catalog):
        result, _ = _extract(fake_catalog, "???", None)
        assert result["preferences"]["subcategory"] is None
        assert result["preferences"]["keywords"] == []
        assert result["not_carried"] is None


class TestRouting:
    def test_not_carried_goes_to_unavailable(self, fake_catalog):
        assert fake_catalog.route_after_extraction({"not_carried": {"item": "chairs"}, "preferences": {}}) == "unavailable"

    def test_no_signal_asks(self, fake_catalog):
        assert fake_catalog.route_after_extraction({"preferences": {"max_price": 500}}) == "ask"

    def test_any_signal_searches(self, fake_catalog):
        assert fake_catalog.route_after_extraction({"preferences": {"keywords": ["calculator"]}}) == "search"


class TestRespondUnavailable:
    def test_offers_the_suggestion(self, fake_catalog):
        reply = fake_catalog.respond_unavailable({"not_carried": {"item": "laptops", "suggestion": "laptop bag"}})
        assert reply["final_response"] == "Sorry, we don't carry laptops. Would you like to see our laptop bag range instead?"

    def test_without_suggestion_shows_the_catalog(self, fake_catalog):
        with patch.object(fake_catalog, "CATALOG_BLURB", "• Electronics (3 products) — tv"):
            reply = fake_catalog.respond_unavailable({"not_carried": {"item": "chairs", "suggestion": None}})
        assert reply["final_response"].startswith("Sorry, we don't carry chairs.")
        assert "Electronics" in reply["final_response"]
