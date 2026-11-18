"""Product search: one relaxation loop, LLM ranking, three-factor score, plain replies."""

from unittest.mock import patch

import pytest

import app.agents.product_agent as pa
from app.agents.product_agent import Ranking


def _product(i, brand="Logitech", price=900, rating=4.4, subcategory="mouse", name=None):
    return {
        "product_id": f"P{i}",
        "name": name or f"{brand} Wireless Mouse {i}",
        "brand": brand,
        "price": price,
        "rating": rating,
        "subcategory": subcategory,
        "type": None,
    }


class TestFindProducts:
    def test_no_relaxation_when_first_search_matches(self):
        with patch.object(pa, "search_products", return_value=[_product(1)]) as search:
            out = pa.find_products({"preferences": {"subcategory": "mouse", "max_price": 1000}})
        assert out == {"search_results": [_product(1)], "relaxed_filters": []}
        assert search.call_count == 1

    def test_relaxes_in_order_and_never_touches_subcategory(self):
        calls = []

        def fake_search(**kwargs):
            calls.append(kwargs)
            return [_product(1)] if kwargs["brand"] is None else []

        prefs = {"subcategory": "mouse", "brand": "Bose", "max_price": 1000, "keywords": ["rgb"]}
        with patch.object(pa, "search_products", side_effect=fake_search):
            out = pa.find_products({"preferences": prefs})
        assert out["relaxed_filters"] == ["price", "brand"]
        assert calls[1]["max_price"] == 1250
        assert all(c["subcategory"] == "mouse" for c in calls)
        assert prefs["brand"] == "Bose"  # the shopper's preferences are not modified

    def test_gives_up_after_the_last_step(self):
        with patch.object(pa, "search_products", return_value=[]):
            out = pa.find_products({"preferences": {"subcategory": "mouse", "keywords": ["x"], "type": "y"}})
        assert out == {"search_results": [], "relaxed_filters": ["type", "keywords"]}


class TestRankProducts:
    def _rank(self, ranking, results, prefs=None):
        with patch.object(pa, "call_llm", return_value=ranking):
            return pa.rank_products({"search_results": results, "preferences": prefs or {}, "user_message": "x"})

    def test_relevant_before_maybe_and_rejects_dropped(self):
        results = [_product(1, rating=4.9), _product(2, rating=3.0), _product(3, name="Mouse Pad")]
        out = self._rank(Ranking(relevant=[2], maybe=[1, 99]), results)
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
        text = self._format({"subcategory": "mouse"}, [{**_product(1), "llm_tier": 0}])
        assert text.startswith("Here are my top recommendations")
        assert "**Logitech Wireless Mouse 1** — Logitech" in text and "₹900 · 4.4/5" in text

    def test_says_which_filters_were_widened(self):
        text = self._format({"subcategory": "mouse"}, [{**_product(1), "llm_tier": 0}], relaxed=["price"])
        assert "I widened the price limit (+25%)" in text

    def test_brand_we_do_not_carry(self):
        text = self._format({"subcategory": "speakers", "brand": "Bose"}, [{**_product(1, brand="JBL"), "llm_tier": 1}])
        assert text.startswith("We don't carry Bose speakers")

    def test_brand_we_carry_outside_the_filters(self):
        ranked = [{**_product(1, brand="boAt"), "llm_tier": 1}]
        with patch.object(pa, "search_products", return_value=[_product(9, brand="Sony")]):
            text = pa.format_recommendations({"preferences": {"subcategory": "headphones", "brand": "Sony"}, "ranked_products": ranked})
        assert text["final_response"].startswith("I couldn't find Sony headphones within your filters")

    def test_only_maybe_results(self):
        text = self._format({"subcategory": "mouse"}, [{**_product(1), "llm_tier": 1}])
        assert text.startswith("These don't match everything")

    @pytest.mark.parametrize("stocked,prefix", [([], "We don't carry Bose."), ([_product(1)], "I couldn't find")])
    def test_no_results(self, stocked, prefix):
        with patch.object(pa, "search_products", return_value=stocked):
            text = pa.respond_no_results({"preferences": {"subcategory": "speakers", "brand": "Bose"}})["final_response"]
        assert text.startswith(prefix)

    def test_ask_for_preferences_shows_catalog(self):
        with patch.object(pa, "CATALOG_BLURB", "• Electronics (3 products) — tv"):
            assert "Electronics" in pa.ask_for_preferences({})["final_response"]


def test_graph_end_to_end():
    schema = pa.search_schema()
    prefs = schema.model_validate({"category": "Computers & Accessories", "keywords": ["wireless mouse"]})
    with patch.object(pa, "call_llm", side_effect=[prefs, Ranking(relevant=[1])]), patch.object(
        pa, "search_products", return_value=[_product(1)]
    ):
        out = pa.product_agent_graph.invoke({"user_message": "wireless mouse", "preferences": {}})
    assert out["final_response"].startswith("Here are my top recommendations")
    assert out["preferences"]["keywords"] == ["wireless mouse"]
