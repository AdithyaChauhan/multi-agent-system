"""Product extraction: one structured call returns the complete filters; the catalog decides what we sell."""

from unittest.mock import patch

import pytest

import app.agents.product_agent as pa
from app.agents.state import ProductState


@pytest.fixture(autouse=True)
def catalog(yaml_catalog):
    return yaml_catalog


def _state(message, previous=None):
    return ProductState(user_message=message, preferences=previous or {})


def _extract(message, model_output, previous=None):
    parsed = pa.ProductSearch.model_validate(model_output) if model_output is not None else None
    with patch.object(pa, "call_llm", return_value=parsed) as call:
        result = pa.extract_preferences(_state(message, previous))
    return result, call


class TestSchema:
    def test_blank_values_become_null_and_features_a_clean_list(self):
        s = pa.ProductSearch.model_validate({"product": "  ", "brand": 3, "features": ["4k", "", None, " smart "]})
        assert (s.product, s.brand, s.features) == (None, None, ["4k", "smart"])


class TestExtractPreferences:
    def test_previous_filters_are_sent_and_complete_filters_returned(self):
        previous = {"product": "tv", "max_price": 15000, "brand": None}
        out = {"product": "tv", "brand": "Samsung", "max_price": 15000}
        result, call = _extract("what about Samsung", out, previous)

        human = call.call_args.args[2][1].content
        assert '"product": "tv"' in human and '"brand"' not in human  # only non-empty previous filters
        assert "what about Samsung" in human
        prefs = result["preferences"]
        assert (prefs["product"], prefs["brand"], prefs["max_price"]) == ("tv", "Samsung", 15000)
        assert result["not_carried"] is None

    def test_prompt_lists_served_types_from_the_catalog(self):
        _, call = _extract("hi", {})
        system = call.call_args.args[2][0].content
        assert "- tv" in system and "- storage: pen drive" in system
        assert "- laptop\n" not in system and "other computer accessory" not in system

    def test_a_type_we_do_not_sell_gets_its_suggestion(self):
        result, _ = _extract("laptop under 50000", {"product": "laptops", "max_price": 50000})
        assert result["not_carried"] == {"item": "laptops", "suggestion": "laptop bag"}

    def test_model_not_carried_that_names_an_unsold_type(self):
        result, _ = _extract("iphone", {"not_carried": "smartphone"})
        assert result["not_carried"] == {"item": "smartphone", "suggestion": "phone holder"}

    def test_model_not_carried_for_something_we_sell_is_overruled(self):
        result, _ = _extract("geyser", {"not_carried": "geyser"})
        assert result["not_carried"] is None
        assert result["preferences"]["product"] == "geyser"

    def test_not_carried_outside_the_catalog(self):
        result, _ = _extract("sofa", {"not_carried": "sofas"})
        assert result["not_carried"] == {"item": "sofas", "suggestion": None}

    def test_unparseable_reply_gives_empty_filters(self):
        result, _ = _extract("???", None)
        assert result["preferences"]["product"] is None
        assert result["preferences"]["features"] == []
        assert result["not_carried"] is None


class TestRouting:
    def test_not_carried_goes_to_unavailable(self):
        assert pa.route_after_extraction({"not_carried": {"item": "chairs"}, "preferences": {}}) == "unavailable"

    def test_no_signal_asks(self):
        assert pa.route_after_extraction({"preferences": {"max_price": 500}}) == "ask"

    def test_any_signal_searches(self):
        assert pa.route_after_extraction({"preferences": {"features": ["calculator"]}}) == "search"


class TestRespondUnavailable:
    def test_offers_the_suggestion(self):
        reply = pa.respond_unavailable({"not_carried": {"item": "laptops", "suggestion": "laptop bag"}})
        assert (
            reply["final_response"]
            == "Sorry, we don't carry laptops. Would you like to see our laptop bag range instead?"
        )

    def test_without_suggestion_shows_the_catalog(self):
        with patch.object(pa, "CATALOG_BLURB", "• Electronics (3 products) — tv"):
            reply = pa.respond_unavailable({"not_carried": {"item": "chairs", "suggestion": None}})
        assert reply["final_response"].startswith("Sorry, we don't carry chairs.")
        assert "Electronics" in reply["final_response"]
