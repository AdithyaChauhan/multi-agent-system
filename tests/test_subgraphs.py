import pytest
from unittest.mock import patch
from app.agents.state import AgentState


class TestProductSubgraph:

    def test_fetch_reviews_node(self):
        """fetch_reviews_node fetches reviews for ranked products"""
        mock_reviews = [{"rating": 4.5, "text": "Great!"}]

        with patch("app.agents.product_agent_subgraph.fetch_reviews", return_value=mock_reviews):
            from app.agents.product_agent_subgraph import fetch_reviews_node

            state = AgentState(
                user_message="show me toys",
                user_id="test-user",
                session_id="test-session",
                ranked_products=[{"product_id": "TOY-001", "name": "Toy"}],
                conversation_history=[],
            )
            result = fetch_reviews_node(state)

        assert "ranked_products" in result
        assert len(result["ranked_products"]) == 1

    def test_fetch_specs_node(self):
        """fetch_specs_node fetches specs for ranked products"""
        with patch("app.agents.product_agent_subgraph.fetch_specs", return_value=[]):
            from app.agents.product_agent_subgraph import fetch_specs_node

            state = AgentState(
                user_message="show me toys",
                user_id="test-user",
                session_id="test-session",
                ranked_products=[{"product_id": "TOY-001", "name": "Toy", "reviews": []}],
                conversation_history=[],
            )
            result = fetch_specs_node(state)

        assert "ranked_products" in result
        assert len(result["ranked_products"]) == 1

    def test_compute_score(self):
        """compute_score ranks products"""
        from app.agents.product_agent_subgraph import compute_score

        state = AgentState(
            user_message="show me toys",
            user_id="test-user",
            session_id="test-session",
            ranked_products=[
                {
                    "product_id": "TOY-001",
                    "name": "Toy A",
                    "rating": 4.5,
                    "avg_review_rating": 4.5,
                    "price": 500,
                    "specs_dict": {},
                    "description": "",
                    "tags": [],
                    "brand": "",
                },
                {
                    "product_id": "TOY-002",
                    "name": "Toy B",
                    "rating": 3.0,
                    "avg_review_rating": 3.0,
                    "price": 300,
                    "specs_dict": {},
                    "description": "",
                    "tags": [],
                    "brand": "",
                },
            ],
            preferences={"category": "Toys & Games"},
            conversation_history=[],
        )
        result = compute_score(state)
        assert "ranked_products" in result

    def test_compute_score_empty_products(self):
        from app.agents.product_agent_subgraph import compute_score

        state = AgentState(
            user_message="q",
            user_id="u",
            session_id="s",
            ranked_products=[],
            conversation_history=[],
        )
        result = compute_score(state)
        assert result == {"ranked_products": []}

    def test_compute_score_price_branches(self):
        from app.agents.product_agent_subgraph import compute_score

        products = [
            {
                "product_id": "P1",
                "name": "Cheap",
                "rating": 3.0,
                "avg_review_rating": 3.0,
                "price": 100,
                "specs_dict": {},
                "description": "",
                "tags": [],
                "brand": "",
            },
            {
                "product_id": "P2",
                "name": "Mid",
                "rating": 3.0,
                "avg_review_rating": 3.0,
                "price": 600,
                "specs_dict": {},
                "description": "",
                "tags": [],
                "brand": "",
            },
            {
                "product_id": "P3",
                "name": "Good",
                "rating": 3.0,
                "avg_review_rating": 3.0,
                "price": 800,
                "specs_dict": {},
                "description": "",
                "tags": [],
                "brand": "",
            },
            {
                "product_id": "P4",
                "name": "Over",
                "rating": 3.0,
                "avg_review_rating": 3.0,
                "price": 1500,
                "specs_dict": {},
                "description": "",
                "tags": [],
                "brand": "",
            },
        ]
        state = AgentState(
            user_message="q",
            user_id="u",
            session_id="s",
            ranked_products=products,
            preferences={"max_price": 1000},
            conversation_history=[],
        )
        result = compute_score(state)
        scores = {p["product_id"]: p["price_score"] for p in result["ranked_products"]}
        assert scores["P1"] == 0.4  # too cheap (<50%)
        assert scores["P2"] == 0.7  # 50-70% of budget
        assert scores["P3"] == 1.0  # 70-100% of budget
        assert scores["P4"] == 0.0  # over budget

    def test_compute_score_keywords_brand_type(self):
        from app.agents.product_agent_subgraph import compute_score

        products = [
            {
                "product_id": "P1",
                "name": "Sony Wireless Neckband",
                "rating": 4.0,
                "avg_review_rating": 4.0,
                "price": 1000,
                "specs_dict": {"connectivity": "wireless", "type": "neckband"},
                "description": "wireless neckband headphones",
                "tags": ["wireless", "neckband"],
                "brand": "Sony",
                "type": "neckband",
            }
        ]
        state = AgentState(
            user_message="q",
            user_id="u",
            session_id="s",
            ranked_products=products,
            preferences={"keywords": ["wireless"], "brand": "Sony", "type": "neckband"},
            conversation_history=[],
        )
        result = compute_score(state)
        p = result["ranked_products"][0]
        assert p["brand_match_score"] == 1.0
        assert p["spec_match_score"] > 0
        assert p["tag_match_score"] > 0
        assert p["title_match_score"] > 0
        assert p["type_match_score"] == 1.0

