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
    def test_filters_so_far_are_sent_and_only_the_change_comes_back(self):
        previous = {"product": "tv", "max_price": 15000, "brand": None}
        result, call = _extract("what about Samsung", {"brand": "Samsung"}, previous)

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


class TestMergePreferences:
    """Code keeps the conversation's filters; the model reports only what the message changes."""

    PREV = {"product": "tv", "features": ["4k"], "brand": "Sony", "max_price": 30000}

    def test_a_refinement_keeps_the_product(self):
        merged = pa.merge_preferences(self.PREV, {"brand": "Samsung"})
        assert (merged["product"], merged["brand"], merged["max_price"], merged["features"]) == (
            "tv",
            "Samsung",
            30000,
            ["4k"],
        )

    def test_a_product_of_another_type_starts_fresh(self):
        merged = pa.merge_preferences(self.PREV, {"product": "headphones", "max_price": 2000})
        assert merged == {**pa.EMPTY_PREFERENCES, "product": "headphones", "max_price": 2000}

    def test_the_same_type_in_other_words_keeps_the_filters(self):
        merged = pa.merge_preferences(self.PREV, {"product": "television"})
        assert (merged["product"], merged["brand"]) == ("television", "Sony")

    def test_clear_drops_filters_and_features_accumulate(self):
        merged = pa.merge_preferences(
            self.PREV, {"clear": ["brand", "product", "nonsense"], "features": ["4K", "55 inch"]}
        )
        assert merged["brand"] is None and merged["product"] == "tv"  # the product can't be cleared
        assert merged["features"] == ["4k", "55 inch"]  # "4K" is already there

    def test_a_brand_before_any_product_is_kept(self):
        assert pa.merge_preferences({"brand": "Sony"}, {"product": "headphones"})["brand"] == "Sony"


class TestFilterChips:
    def test_chips_for_every_filter_and_the_product_is_fixed(self):
        prefs = {**pa.EMPTY_PREFERENCES, "product": "tv", "features": ["4k"], "brand": "Sony", "max_price": 30000}
        chips = pa.active_filters({**prefs, "min_rating": 4.0})
        assert [c["label"] for c in chips] == ["tv", "4k", "Sony", "under ₹30,000", "4★ and up"]
        assert [c["removable"] for c in chips] == [False, True, True, True, True]

    def test_removing_a_chip_drops_that_filter_only(self):
        prefs = {"product": "tv", "features": ["4k", "smart"], "brand": "Sony"}
        out = pa.apply_filter_edit({"preferences": prefs, "filter_edit": {"field": "features", "value": "4k"}})
        assert out["preferences"]["features"] == ["smart"] and out["preferences"]["brand"] == "Sony"
        out = pa.apply_filter_edit({"preferences": prefs, "filter_edit": {"field": "brand"}})
        assert out["preferences"]["brand"] is None

    def test_a_chip_for_an_unknown_field_changes_nothing(self):
        prefs = {"product": "tv", "brand": "Sony"}
        out = pa.apply_filter_edit({"preferences": prefs, "filter_edit": {"field": "product"}})
        assert out["preferences"]["product"] == "tv" and out["preferences"]["brand"] == "Sony"

    def test_chip_removal_searches_again_without_the_model(self):
        tv = {"product_id": "T1", "name": "Sony TV", "brand": "Sony", "price": 20000, "rating": 4.1, "type": "tv"}
        state = {"preferences": {"product": "tv", "brand": "Sony"}, "filter_edit": {"field": "brand"}}
        with patch.object(pa, "call_llm") as model, patch.object(pa, "search_products", return_value=[tv]) as search:
            out = pa.product_agent_graph.invoke(state)
        model.assert_not_called()
        assert search.call_args.kwargs["brand"] is None
        assert out["ranked_products"][0]["product_id"] == "T1" and "Sony TV" in out["final_response"]
        assert [c["field"] for c in out["active_filters"]] == ["product"]
