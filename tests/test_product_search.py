"""Product search: one relaxation loop, LLM ranking, three-factor score, plain replies."""

from unittest.mock import patch

import pytest

import app.agents.product_agent as pa
from app.agents.product_agent import Ranking


def _product(i, brand="Logitech", price=900, rating=4.4, name=None):
    return {
        "product_id": f"P{i}",
        "name": name or f"{brand} Wireless Mouse {i}",
        "brand": brand,
        "price": price,
        "rating": rating,
        "type": "mouse",
    }


@pytest.fixture(autouse=True)
def catalog(yaml_catalog):
    return yaml_catalog


class TestSearchFilters:
    def test_product_word_resolves_to_type_kind_and_attributes(self):
        f = pa.search_filters({"product": "geysers", "features": ["15 litre", "wifi"], "max_price": 9000})
        assert f["product_type"] == "water heater"
        assert f["attributes"] == {"capacity_l": 15}
        assert f["keywords"] == ["wifi"]  # not an attribute of water heaters: matched in names
        assert f["max_price"] == 9000

    def test_kind_and_product_word_attributes(self):
        assert pa.search_filters({"product": "pen drive"})["attributes"] == {"kind": "pen drive"}
        f = pa.search_filters({"product": "immersion rod"})
        assert (f["product_type"], f["attributes"]) == ("water heater", {"heater_type": "immersion rod"})

    def test_unknown_product_is_searched_by_name(self):
        f = pa.search_filters({"product": "drone", "features": ["4k"]})
        assert (f["product_type"], f["attributes"], f["keywords"]) == (None, {}, ["drone", "4k"])


class TestFindProducts:
    """The search loop subgraph: plan → search → loosen → search …"""

    def test_no_relaxation_when_first_search_matches(self):
        with patch.object(pa, "search_products", return_value=[_product(1)]) as search:
            out = pa.find_products.invoke({"preferences": {"product": "mouse", "max_price": 1000}})
        assert (out["search_results"], out["relaxed_filters"]) == ([_product(1)], [])
        assert search.call_count == 1
        assert search.call_args.kwargs["product_type"] == "mouse"

    def test_relaxes_in_order_and_never_touches_the_type(self):
        calls = []

        def fake_search(**kwargs):
            calls.append(kwargs)
            return [_product(1)] if kwargs["brand"] is None else []

        prefs = {"product": "mouse", "brand": "Bose", "max_price": 1000, "features": ["wireless"]}
        with patch.object(pa, "search_products", side_effect=fake_search):
            out = pa.find_products.invoke({"preferences": prefs})
        assert out["relaxed_filters"] == ["price", "brand"]
        assert calls[1]["max_price"] == 1250
        assert all(c["product_type"] == "mouse" for c in calls)
        assert calls[-1]["attributes"] == {"connectivity": "wireless"}
        assert prefs["brand"] == "Bose"  # the shopper's preferences are not modified

    def test_gives_up_after_the_last_step(self):
        with patch.object(pa, "search_products", return_value=[]) as search:
            out = pa.find_products.invoke({"preferences": {"product": "mouse", "features": ["silent", "pink"]}})
        assert (out["search_results"], out["relaxed_filters"]) == ([], ["attributes", "keywords"])
        assert search.call_count == 3  # first search + one per loosened filter

    def test_every_filter_set_means_at_most_five_searches(self):
        prefs = {"product": "mouse", "brand": "Bose", "max_price": 1000, "features": ["wireless", "pink"]}
        with patch.object(pa, "search_products", return_value=[]) as search:
            out = pa.find_products.invoke({"preferences": prefs})
        assert out["relaxed_filters"] == pa.RELAXATION_ORDER
        assert search.call_count == 1 + len(pa.RELAXATION_ORDER)

    def test_next_relaxation_skips_unset_filters(self):
        filters = {"max_price": None, "brand": None, "attributes": {"connectivity": "wireless"}, "keywords": []}
        assert pa.next_relaxation(filters, []) == "attributes"
        assert pa.next_relaxation({**filters, "attributes": {}}, ["attributes"]) is None


class TestRankProducts:
    def _rank(self, ranking, results, prefs=None):
        with patch.object(pa, "call_llm", return_value=ranking):
            return pa.rank_products({"search_results": results, "preferences": prefs or {}, "user_message": "x"})

    def test_exact_before_same_kind_and_other_kinds_dropped(self):
        results = [_product(1, rating=4.9), _product(2, rating=3.0), _product(3, name="Mouse Pad")]
        out = self._rank(Ranking(same_kind=[1, 2, 99], exact=[2]), results)
        assert [p["product_id"] for p in out["ranked_products"]] == ["P2", "P1"]
        assert [p["llm_tier"] for p in out["ranked_products"]] == [0, 1]

    def test_no_candidates_skips_the_llm(self):
        with patch.object(pa, "call_llm") as call:
            assert pa.rank_products({"search_results": []}) == {"ranked_products": []}
        call.assert_not_called()

    def test_unusable_ranking_keeps_search_order_as_maybe(self):
        out = self._rank(None, [_product(1), _product(2)])
        assert [p["llm_tier"] for p in out["ranked_products"]] == [1, 1]

    def test_route(self):
        assert pa.route_after_rank({"ranked_products": [1]}) == "recommend"
        assert pa.route_after_rank({"ranked_products": []}) == "no_results"


class TestScore:
    def test_brand_and_budget_fit_raise_the_score(self):
        prefs = {"brand": "Logitech", "max_price": 1000}
        assert pa.score(_product(1, price=900), prefs) > pa.score(_product(2, brand="HP", price=200), prefs)

    def test_over_budget_scores_lower(self):
        prefs = {"max_price": 1000}
        assert pa.score(_product(1, price=1200), prefs) < pa.score(_product(2, price=800), prefs)


class TestReplies:
    def _format(self, prefs, ranked, relaxed=()):
        with patch.object(pa, "search_products", return_value=[]):
            return pa.format_recommendations(
                {"preferences": prefs, "ranked_products": ranked, "relaxed_filters": list(relaxed)}
            )["final_response"]

    def test_plain_recommendations(self):
        text = self._format({"product": "mouse"}, [{**_product(1), "llm_tier": 0}])
        assert text.startswith("Here are my top recommendations")
        assert "**Logitech Wireless Mouse 1** — Logitech" in text and "₹900 · 4.4/5" in text

    def test_says_which_filters_were_widened(self):
        text = self._format({"product": "mouse"}, [{**_product(1), "llm_tier": 0}], relaxed=["price"])
        assert "I widened the price limit (+25%)" in text

    def test_brand_we_do_not_carry(self):
        text = self._format({"product": "speaker", "brand": "Bose"}, [{**_product(1, brand="JBL"), "llm_tier": 1}])
        assert text.startswith("We don't carry Bose speaker")

    def test_brand_we_carry_outside_the_filters(self):
        ranked = [{**_product(1, brand="boAt"), "llm_tier": 1}]
        with patch.object(pa, "search_products", return_value=[_product(9, brand="Sony")]):
            text = pa.format_recommendations(
                {"preferences": {"product": "headphones", "brand": "Sony"}, "ranked_products": ranked}
            )
        assert text["final_response"].startswith("I couldn't find Sony headphones within your filters")

    def test_only_maybe_results(self):
        text = self._format({"product": "mouse"}, [{**_product(1), "llm_tier": 1}])
        assert text.startswith("These don't match everything")

    @pytest.mark.parametrize(
        "stocked,prefix", [([], "We don't carry Bose speaker."), ([_product(1)], "I couldn't find")]
    )
    def test_no_results(self, stocked, prefix):
        with patch.object(pa, "search_products", return_value=stocked):
            text = pa.respond_no_results({"preferences": {"product": "speaker", "brand": "Bose"}})["final_response"]
        assert text.startswith(prefix)

    def test_ask_for_preferences_shows_catalog(self):
        with patch.object(pa, "CATALOG_BLURB", "• Electronics (3 products) — tv"):
            assert "Electronics" in pa.ask_for_preferences({})["final_response"]


def test_graph_end_to_end():
    prefs = pa.ProductSearch.model_validate({"product": "mouse", "features": ["wireless"]})
    with patch.object(pa, "call_llm", side_effect=[prefs, Ranking(same_kind=[1], exact=[1])]), patch.object(
        pa, "search_products", return_value=[_product(1)]
    ):
        out = pa.product_agent_graph.invoke({"user_message": "wireless mouse", "preferences": {}})
    assert out["final_response"].startswith("Here are my top recommendations")
    assert out["preferences"]["features"] == ["wireless"]
    # The subgraph hands back only its declared outputs; search internals stay inside it.
    assert set(out) <= {"preferences", "active_filters", "ranked_products", "relaxed_filters", "final_response"}


class TestProductPhrases:
    @pytest.mark.parametrize(
        "phrase, expected",
        [
            ("neckband headphones", ("headphones", "neckband")),
            ("tv remote cover", ("tv accessory", "remote cover")),
            ("laptop bag for 15 inch", ("laptop bag", None)),
            ("phone case", (None, None)),  # never "we don't carry phones"
            ("hoverboard", (None, None)),
        ],
    )
    def test_phrases_of_known_words(self, catalog, phrase, expected):
        ptype, kind = catalog.resolve_product(phrase)
        assert ((ptype.name if ptype else None), kind) == expected

    def test_bluetooth_counts_as_wireless_for_keyboards(self):
        assert pa.search_filters({"product": "keyboard", "features": ["bluetooth"]})["attributes"] == {
            "connectivity": "wireless"
        }
