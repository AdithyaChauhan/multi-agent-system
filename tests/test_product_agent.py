import pytest
from unittest.mock import MagicMock, patch
from app.agents.state import AgentState


class TestExtractPreferences:

    def test_extracts_category_from_message(self):
        mock_response = MagicMock()
        mock_response.content = '{"category": "Toys & Games", "keywords": ["toys"], "brand": null, "min_price": null, "max_price": null, "subcategory": null, "unavailable_request": false}'

        with patch("app.agents.product_agent.llm") as mock_llm:
            mock_llm.invoke.return_value = mock_response
            from app.agents.product_agent import extract_preferences

            state = AgentState(
                user_message="show me toys", user_id="test-user", session_id="test-session", conversation_history=[]
            )
            result = extract_preferences(state)

        assert "preferences" in result
        assert result["preferences"]["category"] == "Toys & Games"

    def test_handles_unavailable_request(self):
        mock_response = MagicMock()
        mock_response.content = '{"category": "electronics", "keywords": ["laptop"], "brand": null, "min_price": null, "max_price": null, "subcategory": null, "unavailable_request": true}'

        with patch("app.agents.product_agent.llm") as mock_llm:
            mock_llm.invoke.return_value = mock_response
            from app.agents.product_agent import extract_preferences

            state = AgentState(
                user_message="show me MacBook", user_id="test-user", session_id="test-session", conversation_history=[]
            )
            result = extract_preferences(state)

        assert result["preferences"]["unavailable_request"] is True

    def test_handles_invalid_json(self):
        mock_response = MagicMock()
        mock_response.content = "invalid json"

        with patch("app.agents.product_agent.llm") as mock_llm:
            mock_llm.invoke.return_value = mock_response
            from app.agents.product_agent import extract_preferences

            state = AgentState(
                user_message="show me something",
                user_id="test-user",
                session_id="test-session",
                conversation_history=[],
            )
            result = extract_preferences(state)

        assert "preferences" in result


class TestSearchProducts:

    def test_search_returns_search_results(self):
        """do_search_products is deterministic — returns search_results directly from DB."""
        products = [{"product_id": "P1", "name": "Speaker", "price": 1000, "rating": 4.5, "brand": "JBL"}]
        with patch("app.agents.product_agent.search_products", return_value=products):
            from app.agents.product_agent import do_search_products

            state = AgentState(
                user_message="show me speakers",
                user_id="test-user",
                session_id="test-session",
                preferences={"category": "Electronics", "subcategory": "speakers", "keywords": []},
                conversation_history=[],
            )
            result = do_search_products(state)

        assert "search_results" in result
        assert len(result["search_results"]) == 1

    def test_search_passes_preferences_to_db(self):
        """do_search_products maps preference fields correctly to search_products args."""
        with patch("app.agents.product_agent.search_products", return_value=[]) as mock_search:
            from app.agents.product_agent import do_search_products

            prefs = {
                "category": "Electronics",
                "subcategory": "headphones",
                "type": "neckband",
                "brand": "boAt",
                "max_price": 2000,
                "min_price": None,
                "keywords": ["calling"],
            }
            state = AgentState(
                user_message="boAt neckband",
                user_id="test-user",
                session_id="test-session",
                preferences=prefs,
                conversation_history=[],
            )
            do_search_products(state)

        mock_search.assert_called_once_with(
            category="Electronics",
            subcategory="headphones",
            product_type="neckband",
            brand="boAt",
            max_price=2000,
            min_price=None,
            keywords=["calling"],
            limit=10,
        )

    def test_search_empty_results(self):
        """do_search_products returns empty search_results when DB finds nothing."""
        with patch("app.agents.product_agent.search_products", return_value=[]):
            from app.agents.product_agent import do_search_products

            state = AgentState(
                user_message="obscure item",
                user_id="test-user",
                session_id="test-session",
                preferences={"category": "Electronics", "keywords": ["nonexistent"]},
                broaden_attempt=0,
                conversation_history=[],
            )
            result = do_search_products(state)

        assert result["search_results"] == []


class TestProductRouting:

    def test_route_after_extraction_unavailable(self):
        from app.agents.product_agent import route_after_extraction

        state = AgentState(
            user_message="show me MacBook",
            user_id="test-user",
            session_id="test-session",
            preferences={"unavailable_request": True, "category": "electronics"},
            conversation_history=[],
        )
        result = route_after_extraction(state)
        assert result == "unavailable"

    def test_route_after_extraction_search(self):
        from app.agents.product_agent import route_after_extraction

        state = AgentState(
            user_message="show me toys",
            user_id="test-user",
            session_id="test-session",
            preferences={"unavailable_request": False, "category": "Toys & Games"},
            conversation_history=[],
        )
        result = route_after_extraction(state)
        assert result == "search"

    def test_route_after_search_found(self):
        from app.agents.product_agent import route_after_search

        state = AgentState(
            user_message="show me toys",
            user_id="test-user",
            session_id="test-session",
            search_results=[{"product_id": "TOY-001"}],
            broaden_attempt=0,
            filters_exhausted=False,
            conversation_history=[],
        )
        result = route_after_search(state)
        assert result == "rank"

    def test_route_after_search_no_results(self):
        from app.agents.product_agent import route_after_search

        state = AgentState(
            user_message="show me toys",
            user_id="test-user",
            session_id="test-session",
            search_results=[],
            broaden_attempt=0,
            filters_exhausted=False,
            conversation_history=[],
        )
        result = route_after_search(state)
        assert result == "broaden"
