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

    def _mock_search_llm(self, mock_llm, tool_call=True):
        """Set up llm.bind_tools(...).invoke() mock for do_search_products."""
        mock_response = MagicMock()
        mock_response.content = ""
        mock_response.response_metadata = {
            "token_usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}
        }
        if tool_call:
            mock_response.tool_calls = [
                {"id": "c1", "function": {"name": "search_product_catalog", "arguments": "{}"}, "type": "function"}
            ]
        else:
            mock_response.tool_calls = []
        mock_llm.bind_tools.return_value.invoke.return_value = mock_response
        return mock_response

    def test_search_returns_messages(self):
        """do_search_products now returns messages (LLM tool-caller node)."""
        with patch("app.agents.product_agent.llm") as mock_llm:
            self._mock_search_llm(mock_llm)
            from app.agents.product_agent import do_search_products

            state = AgentState(
                user_message="show me toys",
                user_id="test-user",
                session_id="test-session",
                preferences={"category": "Toys & Games", "keywords": ["toys"]},
                conversation_history=[],
            )
            result = do_search_products(state)

        assert "messages" in result

    def test_parse_search_results_extracts_products(self):
        """parse_search_results reads ToolMessage content into search_results."""
        import json
        from langchain_core.messages import ToolMessage
        from app.agents.product_agent import parse_search_results

        products = [{"product_id": "P1", "name": "Speaker", "price": 1000, "rating": 4.5, "brand": "JBL"}]
        tool_msg = ToolMessage(content=json.dumps(products), tool_call_id="c1")

        state = AgentState(
            user_message="show me speakers",
            user_id="test-user",
            session_id="test-session",
            conversation_history=[],
            messages=[tool_msg],
        )
        result = parse_search_results(state)
        assert "search_results" in result
        assert len(result["search_results"]) == 1

    def test_parse_search_results_empty(self):
        """parse_search_results returns empty list when no ToolMessage."""
        import json
        from langchain_core.messages import ToolMessage
        from app.agents.product_agent import parse_search_results

        tool_msg = ToolMessage(content=json.dumps([]), tool_call_id="c1")
        state = AgentState(
            user_message="show me toys",
            user_id="test-user",
            session_id="test-session",
            conversation_history=[],
            messages=[tool_msg],
        )
        result = parse_search_results(state)
        assert result["search_results"] == []

    def test_search_with_no_results(self):
        """do_search_products with no-tool-call response returns messages."""
        with patch("app.agents.product_agent.llm") as mock_llm:
            self._mock_search_llm(mock_llm, tool_call=False)
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

        assert "messages" in result


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
