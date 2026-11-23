"""Hybrid search (ADR 0014): fusion, query text, the "we don't carry" check and product cards.

Unit tests run on SQLite with a fake embedder; the pgvector SQL itself is covered by the
integration test at the end (needs the local Postgres with embeddings loaded)."""

import os
from unittest.mock import patch

import pytest

import app.agents.product_agent as pa
from app.agents.state import ProductState
from app.core import config
from app.search import embeddings, hybrid


@pytest.fixture(autouse=True)
def catalog(yaml_catalog):
    return yaml_catalog


@pytest.fixture
def hybrid_on(monkeypatch):
    monkeypatch.setattr(config, "PRODUCT_SEARCH", "hybrid")
    monkeypatch.setattr(hybrid, "hybrid_available", lambda: True)


class TestFusion:
    def test_reciprocal_rank_fusion_rewards_agreement(self):
        order = hybrid.rrf({"vector": [1, 2, 3], "text": [2, 3, 4], "type": [2]}, {}, k=60)
        assert order[0] == 2  # in all three lists
        assert set(order) == {1, 2, 3, 4}

    def test_weights_and_repeatable_ties(self):
        assert hybrid.rrf({"vector": [1], "type": [2]}, {"type": 2.0}, k=60) == [2, 1]
        assert hybrid.rrf({"vector": [5], "text": [3]}, {}, k=60) == [3, 5]  # equal scores: lower id first

    def test_nothing_to_fuse(self):
        assert hybrid.rrf({}, {}, k=60) == []


class TestEmbeddingText:
    def test_product_document_uses_the_products_own_words_not_type_names(self):
        doc = embeddings.product_document(
            "Philips Lint Remover",
            "Philips GC026 Lint Remover for Woolens",
            {"kind": "fabric shaver", "rechargeable": True, "battery_mah": 1200, "colors": ["blue", "white"]},
        )
        assert doc.startswith("Philips Lint Remover. fabric shaver. Philips GC026")
        assert "rechargeable" in doc and "1200 battery mah" in doc and "blue white" in doc
        assert "Home & Kitchen" not in doc

    def test_empty_attributes(self):
        assert embeddings.product_document("Mouse", "", None) == "Mouse"

    def test_pgvector_text_form(self):
        assert embeddings.to_pgvector([0.5, -0.25]) == "[0.500000,-0.250000]"

    def test_query_gets_the_retrieval_instruction(self):
        class FakeModel:
            def embed(self, texts, **_):
                self.seen = texts
                return iter([[0.1, 0.2]])

        fake = FakeModel()
        with patch.object(embeddings, "_model", return_value=fake):
            assert embeddings.embed_query("heater") == [0.1, 0.2]
        assert fake.seen == [embeddings.QUERY_PREFIX + "heater"]


class TestQueryAndDispatch:
    def test_query_text_is_product_features_and_message(self, hybrid_on):
        f = pa.search_filters({"product": "headphones", "features": ["wireless"]}, "need wireless headphones")
        assert f["query"] == "headphones wireless need wireless headphones"

    def test_unknown_product_word_is_not_a_hard_keyword_under_hybrid(self, hybrid_on):
        f = pa.search_filters({"product": "pointing device"})
        assert (f["product_type"], f["keywords"], f["query"]) == (None, [], "pointing device")

    def test_type_search_keeps_the_name_keyword(self, monkeypatch):
        monkeypatch.setattr(config, "PRODUCT_SEARCH", "type")
        assert pa.search_filters({"product": "drone"})["keywords"] == ["drone"]

    def test_search_node_uses_hybrid_with_the_query(self, hybrid_on):
        with patch.object(hybrid, "hybrid_search", return_value=[{"product_id": "P1"}]) as fake:
            out = pa.find_products.invoke({"preferences": {"product": "tv"}, "user_message": "a tv"})
        assert out["search_results"] == [{"product_id": "P1"}]
        assert fake.call_args.kwargs["query"] == "tv a tv"
        assert fake.call_args.kwargs["product_type"] == "tv"

    def test_other_types_alone_dont_stop_the_loosening(self, hybrid_on):
        def fake(**kwargs):  # with the brand: only a Sony cable; without it: headphones
            if kwargs["brand"]:
                return [{"product_id": "C1", "type": "cable"}]
            return [{"product_id": "H1", "type": "headphones"}]

        prefs = {"product": "headphones", "brand": "Sony", "max_price": 500}
        with patch.object(hybrid, "hybrid_search", side_effect=fake):
            out = pa.find_products.invoke({"preferences": prefs, "user_message": "sony headphones under 500"})
        assert out["relaxed_filters"] == ["price", "brand"]
        assert out["search_results"][0]["product_id"] == "H1"

    def test_found_what_was_asked(self):
        assert pa.found_what_was_asked([{"type": "tv"}], {"product_type": "tv"})
        assert not pa.found_what_was_asked([{"type": "tv remote"}], {"product_type": "tv"})
        assert pa.found_what_was_asked([{"type": "tv remote"}], {"product_type": None})
        assert not pa.found_what_was_asked([], {"product_type": None})

    def test_falls_back_to_type_search_without_embeddings(self, monkeypatch):
        monkeypatch.setattr(config, "PRODUCT_SEARCH", "hybrid")
        monkeypatch.setattr(hybrid, "hybrid_available", lambda: False)
        with patch.object(pa, "search_products", return_value=[]) as fake:
            pa.find_products.invoke({"preferences": {"product": "tv"}})
        assert "query" not in fake.call_args.kwargs

    def test_not_available_on_sqlite(self):
        assert hybrid.hybrid_available() is False
        assert hybrid.catalog_match("lint remover") is None


def _extract(message, model_output, matches):
    parsed = pa.ProductSearch.model_validate(model_output)
    with patch.object(pa, "call_llm", return_value=parsed), patch.object(hybrid, "catalog_match", side_effect=matches):
        return pa.extract_preferences(ProductState(user_message=message, preferences={}))


class TestNotCarriedCheck:
    def test_close_catalog_match_searches_instead_of_refusing(self, hybrid_on):
        close = {"type": "lint remover", "word": "lint remover", "similarity": 0.81}
        result = _extract("remove fuzz balls from my sweaters", {"not_carried": "clothing"}, [None, close])
        assert result["not_carried"] is None
        assert result["preferences"]["product"] == "lint remover"

    def test_distant_match_still_refuses(self, hybrid_on):
        far = {"type": "laptop stand", "word": "laptop table", "similarity": 0.70}
        result = _extract("sofa", {"not_carried": "sofa"}, [far, far])
        assert result["not_carried"] == {"item": "sofa", "suggestion": None}

    def test_types_we_dont_sell_are_never_rescued(self, hybrid_on):
        with patch.object(hybrid, "catalog_match") as match:
            result = _extract("laptop", {"product": "laptop"}, [])
        assert result["not_carried"]["suggestion"] == "laptop bag"
        match.assert_not_called()

    def test_off_with_type_search(self, monkeypatch):
        monkeypatch.setattr(config, "PRODUCT_SEARCH", "type")
        result = _extract("sofa", {"not_carried": "sofa"}, [])
        assert result["not_carried"]["item"] == "sofa"


class TestRankerOff:
    def test_keeps_the_search_order_without_a_model_call(self, monkeypatch):
        monkeypatch.setattr(config, "PRODUCT_RANKER", "off")
        candidates = [{"product_id": f"P{i}", "name": f"n{i}", "price": 100, "rating": 4.0} for i in range(7)]
        with patch.object(pa, "call_llm") as llm:
            out = pa.rank_products(ProductState(search_results=candidates, preferences={}))
        llm.assert_not_called()
        assert [p["product_id"] for p in out["ranked_products"]] == ["P0", "P1", "P2", "P3", "P4"]


class TestProductCards:
    def test_cards_carry_photo_price_rating_and_link(self):
        from app.main import product_cards

        ranked = [
            {
                "product_id": f"P{i}",
                "title": f"T{i}",
                "brand": "B",
                "price": 999,
                "rating": 4.2,
                "image": "https://img/x.jpg",
                "link": "https://shop/x",
                "description": "long text",
            }
            for i in range(5)
        ]
        cards = product_cards({"ranked_products": ranked})
        assert len(cards) == 3  # the reply lists the top 3
        assert cards[0] == {
            "product_id": "P0",
            "title": "T0",
            "brand": "B",
            "price": 999,
            "rating": 4.2,
            "image": "https://img/x.jpg",
            "link": "https://shop/x",
        }
        assert product_cards({"ranked_products": []}) is None
        assert product_cards({}) is None


@pytest.mark.integration
def test_hybrid_search_on_postgres():
    """Live pgvector SQL against the local baseline database (embeddings loaded)."""
    url = os.getenv("HYBRID_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set HYBRID_TEST_DATABASE_URL to a Postgres database with embeddings")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(url)
    with patch.object(hybrid, "engine", engine), patch.object(hybrid, "SessionLocal", sessionmaker(bind=engine)):
        hybrid._ready = False
        assert hybrid.hybrid_available()
        results = hybrid.hybrid_search(query="remove fuzz balls from my sweaters", limit=5)
        assert results and all(r["type"] == "lint remover" for r in results[:3])
        assert hybrid.catalog_match("lint remover")["similarity"] > 0.75
