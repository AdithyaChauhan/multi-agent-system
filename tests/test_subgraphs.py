import pytest
from unittest.mock import MagicMock, patch
from app.agents.state import AgentState


class TestOrderSubgraph:

    def test_fetch_tracking(self):
        """fetch_tracking fetches from carrier API"""
        mock_tracking = {
            "carrier": "FedEx",
            "status": "In Transit",
            "current_location": "Mumbai",
            "estimated_delivery": "2026-05-25"
        }

        with patch("app.agents.order_agent_subgraph.fetch_tracking_info", return_value=mock_tracking):
            from app.agents.order_agent_subgraph import fetch_tracking

            state = AgentState(
                user_message="track my order",
                user_id="test-user",
                session_id="test-session",
                order_data={"order_id": "ORD-2001", "tracking_id": "TRK-001", "carrier": "FedEx"},
                conversation_history=[]
            )
            result = fetch_tracking(state)

        assert "tracking_data" in result

    def test_fetch_tracking_no_tracking_id(self):
        """Handles missing tracking ID"""
        from app.agents.order_agent_subgraph import fetch_tracking

        state = AgentState(
            user_message="track my order",
            user_id="test-user",
            session_id="test-session",
            order_data={"order_id": "ORD-2001", "tracking_id": None, "carrier": None},
            conversation_history=[]
        )
        result = fetch_tracking(state)
        assert "tracking_data" in result

    def test_get_carrier_info(self):
        """get_carrier_info returns carrier details"""
        from app.agents.order_agent_subgraph import get_carrier_info

        state = AgentState(
            user_message="track my order",
            user_id="test-user",
            session_id="test-session",
            order_data={"order_id": "ORD-2001", "carrier": "FedEx", "tracking_id": "TRK-001"},
            conversation_history=[]
        )
        result = get_carrier_info(state)
        assert isinstance(result, dict)


class TestSupportSubgraph:

    def test_check_history_returns_history(self):
        """check_history fetches user ticket history"""
        with patch("app.agents.support_agent_subgraph.get_user_ticket_history", return_value=[]):
            from app.agents.support_agent_subgraph import check_history

            state = AgentState(
                user_message="product broken",
                user_id="test-user",
                session_id="test-session",
                conversation_history=[]
            )
            result = check_history(state)

        assert "ticket_history" in result
        assert "recent_critical_count" in result

    def test_assign_priority_critical(self):
        """Assigns HIGH priority for first-time high severity"""
        from app.agents.support_agent_subgraph import assign_priority

        state = AgentState(
            user_message="urgent",
            user_id="test-user",
            session_id="test-session",
            severity="high",
            recent_critical_count=0,
            conversation_history=[]
        )
        result = assign_priority(state)
        assert result["priority"] == "HIGH"

    def test_assign_priority_p0_for_repeat_critical(self):
        """Assigns URGENT priority for repeat high severity"""
        from app.agents.support_agent_subgraph import assign_priority

        state = AgentState(
            user_message="urgent again",
            user_id="test-user",
            session_id="test-session",
            severity="high",
            recent_critical_count=1,
            conversation_history=[]
        )
        result = assign_priority(state)
        assert result["priority"] == "URGENT"

    def test_assign_priority_medium(self):
        """Assigns MEDIUM priority for first-time medium severity"""
        from app.agents.support_agent_subgraph import assign_priority

        state = AgentState(
            user_message="product broken",
            user_id="test-user",
            session_id="test-session",
            severity="medium",
            recent_critical_count=0,
            conversation_history=[]
        )
        result = assign_priority(state)
        assert result["priority"] == "MEDIUM"


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
                conversation_history=[]
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
                conversation_history=[]
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
                {"product_id": "TOY-001", "name": "Toy A", "rating": 4.5, "avg_review_rating": 4.5, "price": 500, "specs_dict": {}, "description": "", "tags": [], "brand": ""},
                {"product_id": "TOY-002", "name": "Toy B", "rating": 3.0, "avg_review_rating": 3.0, "price": 300, "specs_dict": {}, "description": "", "tags": [], "brand": ""},
            ],
            preferences={"category": "Toys & Games"},
            conversation_history=[]
        )
        result = compute_score(state)
        assert "ranked_products" in result