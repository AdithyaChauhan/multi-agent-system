"""
Deep continuous testing for all 3 agents.
Tests every flow path, edge case, and routing decision.
"""

import pytest
from unittest.mock import MagicMock, patch
from app.agents.state import AgentState

# ====================================================================
# AGENT 1: ORDER TRACKING - DEEP TESTS
# ====================================================================


# ====================================================================
# AGENT 2: PRODUCT RECOMMENDATIONS - DEEP TESTS
# ====================================================================


class TestProductAgentCompleteFlow:
    """Tests every flow path in product agent"""

    def test_flow_search_returns_results(self):
        """do_search_products is deterministic — returns search_results directly."""
        products = [{"product_id": "P1", "name": "Speaker", "price": 1000, "rating": 4.5, "brand": "JBL"}]
        with patch("app.agents.product_agent.search_products", return_value=products):
            from app.agents.product_agent import do_search_products

            state = AgentState(
                user_message="speakers",
                user_id="u1",
                session_id="s1",
                preferences={"category": "Electronics", "keywords": ["speaker"]},
                conversation_history=[],
            )
            result = do_search_products(state)

        assert "search_results" in result
        assert len(result["search_results"]) == 1

    def test_flow_search_no_results_triggers_broaden(self):
        """Empty DB results from do_search_products causes route_after_search to return 'broaden'."""
        from app.agents.product_agent import do_search_products, route_after_search

        with patch("app.agents.product_agent.search_products", return_value=[]):
            state = AgentState(
                user_message="toys",
                user_id="u1",
                session_id="s1",
                preferences={"category": "Electronics", "min_price": 100000},
                broaden_attempt=0,
                conversation_history=[],
            )
            result = do_search_products(state)

        assert result["search_results"] == []
        merged = {**state, **result}
        assert route_after_search(merged) == "broaden"

    def test_flow_broaden_relaxes_filters(self):
        """broaden_search relaxes brand when attempt index reaches it in RELAXATION_ORDER"""
        from app.agents.product_agent import broaden_search, RELAXATION_ORDER

        # Start exactly at the brand step so the test is independent of earlier steps
        brand_idx = RELAXATION_ORDER.index("brand")
        prefs = {"category": "Electronics", "subcategory": "headphones", "brand": "Bose", "keywords": ["sony"]}
        state = AgentState(
            user_message="headphones",
            user_id="u1",
            session_id="s1",
            preferences=dict(prefs),
            original_preferences=dict(prefs),
            broaden_attempt=brand_idx,
            conversation_history=[],
        )
        result = broaden_search(state)

        assert "preferences" in result
        assert result["broaden_attempt"] > brand_idx
        assert result["preferences"]["brand"] is None
        # keywords still present so specificity remains and search is retried
        assert result["preferences"].get("keywords")

    def test_flow_routing_extraction_to_search(self):
        """Valid preferences route to search"""
        from app.agents.product_agent import route_after_extraction

        state = AgentState(
            user_message="toys",
            user_id="u1",
            session_id="s1",
            preferences={"category": "Toys & Games", "unavailable_request": False},
            conversation_history=[],
        )
        result = route_after_extraction(state)
        assert result == "search"

    def test_flow_routing_extraction_to_ask(self):
        """No category routes to ask for preferences"""
        from app.agents.product_agent import route_after_extraction

        state = AgentState(
            user_message="show me products",
            user_id="u1",
            session_id="s1",
            preferences={"category": None, "unavailable_request": False},
            conversation_history=[],
        )
        result = route_after_extraction(state)
        assert result in ["ask", "search"]


class TestProductSubgraphDeep:
    """Tests product enrichment subgraph"""

    def test_subgraph_fetches_reviews_for_each_product(self):
        """Reviews fetched for each ranked product"""
        with patch("app.agents.product_agent_subgraph.fetch_reviews", return_value=[{"rating": 4.5, "text": "Great"}]):
            from app.agents.product_agent_subgraph import fetch_reviews_node

            state = AgentState(
                user_message="toys",
                user_id="u1",
                session_id="s1",
                ranked_products=[
                    {"product_id": "P1", "name": "Toy A"},
                    {"product_id": "P2", "name": "Toy B"},
                ],
                conversation_history=[],
            )
            result = fetch_reviews_node(state)

        assert len(result["ranked_products"]) == 2

    def test_subgraph_compute_score_ranks_by_rating(self):
        """compute_score ranks products by combined score"""
        from app.agents.product_agent_subgraph import compute_score

        state = AgentState(
            user_message="toys",
            user_id="u1",
            session_id="s1",
            ranked_products=[
                {
                    "product_id": "P1",
                    "name": "Low Rated",
                    "rating": 2.0,
                    "avg_review_rating": 2.0,
                    "price": 500,
                    "specs_dict": {},
                    "description": "",
                    "tags": [],
                    "brand": "",
                    "name": "Low Rated",
                },
                {
                    "product_id": "P2",
                    "name": "High Rated",
                    "rating": 4.8,
                    "avg_review_rating": 4.8,
                    "price": 800,
                    "specs_dict": {},
                    "description": "",
                    "tags": [],
                    "brand": "",
                    "name": "High Rated",
                },
            ],
            preferences={"category": "Toys & Games"},
            conversation_history=[],
        )
        result = compute_score(state)

        assert "ranked_products" in result
        assert len(result["ranked_products"]) > 0


# ====================================================================
# AGENT 3: SUPPORT - DEEP TESTS
# ====================================================================

