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

    def test_search_returns_products(self):
        mock_products = [
            {"product_id": "TOY-001", "name": "Lego", "category": "Toys & Games", "price": 1500, "rating": 4.5}
        ]

        with patch("app.agents.product_agent.search_products", return_value=mock_products):
            from app.agents.product_agent import do_search_products

            state = AgentState(
                user_message="show me toys",
                user_id="test-user",
                session_id="test-session",
                preferences={"category": "Toys & Games", "keywords": ["toys"]},
                conversation_history=[],
            )
            result = do_search_products(state)

        assert "search_results" in result

    def test_search_with_no_results(self):
        with patch("app.agents.product_agent.search_products", return_value=[]):
            from app.agents.product_agent import do_search_products

            state = AgentState(
                user_message="show me toys",
                user_id="test-user",
                session_id="test-session",
                preferences={"category": "Toys & Games", "keywords": ["toys"]},
                broaden_attempt=0,
                conversation_history=[],
            )
            result = do_search_products(state)

        assert "search_results" in result
        assert len(result["search_results"]) == 0


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
