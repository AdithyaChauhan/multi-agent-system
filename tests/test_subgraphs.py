import pytest
from unittest.mock import patch
from app.agents.state import AgentState


class TestOrderSubgraph:

    def test_fetch_tracking(self):
        """fetch_tracking fetches from carrier API"""
        mock_tracking = {
            "carrier": "FedEx",
            "status": "In Transit",
            "current_location": "Mumbai",
            "estimated_delivery": "2026-05-25",
        }

        with patch("app.agents.order_agent_subgraph.fetch_tracking_info", return_value=mock_tracking):
            from app.agents.order_agent_subgraph import fetch_tracking

            state = AgentState(
                user_message="track my order",
                user_id="test-user",
                session_id="test-session",
                order_data={"order_id": "ORD-2001", "tracking_id": "TRK-001", "carrier": "FedEx"},
                conversation_history=[],
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
            conversation_history=[],
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
            conversation_history=[],
        )
        result = get_carrier_info(state)
        assert isinstance(result, dict)


class TestSupportSubgraph:

    def test_check_history_returns_history(self):
        """check_history fetches user ticket history"""
        with patch("app.agents.support_agent_subgraph.get_user_ticket_history", return_value=[]):
            from app.agents.support_agent_subgraph import check_history

            state = AgentState(
                user_message="product broken", user_id="test-user", session_id="test-session", conversation_history=[]
            )
            result = check_history(state)

        assert "ticket_history" in result
        assert "recent_critical_count" in result

    def test_assign_priority_critical(self):
        """Assigns P1 priority for critical severity"""
        from app.agents.support_agent_subgraph import assign_priority

        state = AgentState(
            user_message="urgent",
            user_id="test-user",
            session_id="test-session",
            severity="critical",
            recent_critical_count=0,
            conversation_history=[],
        )
        result = assign_priority(state)
        assert result["priority"] == "P1"

    def test_assign_priority_p0_for_repeat_critical(self):
        """Assigns P0 for repeat critical users"""
        from app.agents.support_agent_subgraph import assign_priority

        state = AgentState(
            user_message="urgent again",
            user_id="test-user",
            session_id="test-session",
            severity="critical",
            recent_critical_count=2,
            conversation_history=[],
        )
        result = assign_priority(state)
        assert result["priority"] == "P0"

    def test_assign_priority_medium(self):
        """Assigns P2 for medium severity"""
        from app.agents.support_agent_subgraph import assign_priority

        state = AgentState(
            user_message="product broken",
            user_id="test-user",
            session_id="test-session",
            severity="medium",
            recent_critical_count=0,
            conversation_history=[],
        )
        result = assign_priority(state)
        assert result["priority"] == "P2"


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


class TestSupportSubgraph:

    def _make_state(self, **kwargs):
        defaults = dict(
            user_message="damaged item",
            user_id="u1",
            session_id="s1",
            conversation_history=[],
            support_issue={"category": "defective", "order_id": None},
            support_order={},
        )
        defaults.update(kwargs)
        return AgentState(**defaults)

    def test_assign_priority_critical_single(self):
        from app.agents.support_agent_subgraph import assign_priority

        result = assign_priority(self._make_state(severity="critical", recent_critical_count=0))
        assert result["priority"] == "P1"

    def test_assign_priority_low(self):
        from app.agents.support_agent_subgraph import assign_priority

        result = assign_priority(self._make_state(severity="low", recent_critical_count=0))
        assert result["priority"] == "P3"

    def test_create_ticket_bare_digit_order_normalised(self):
        from app.agents.support_agent_subgraph import create_ticket_node

        with patch("app.agents.support_agent_subgraph.get_open_ticket_for_order", return_value=None), patch(
            "app.agents.support_agent_subgraph.create_support_ticket",
            return_value={"ticket_id": "TKT-001", "status": "open"},
        ):
            result = create_ticket_node(
                self._make_state(
                    support_issue={"category": "defective", "order_id": "2001", "description": "broken"},
                    support_order={"order_id": "2001"},
                    severity="medium",
                    priority="P2",
                    policy={},
                )
            )
        assert "final_response" in result

    def test_create_ticket_duplicate_suppressed(self):
        from app.agents.support_agent_subgraph import create_ticket_node

        existing_ticket = {"ticket_id": "TKT-EXISTING"}
        with patch("app.agents.support_agent_subgraph.get_open_ticket_for_order", return_value=existing_ticket):
            result = create_ticket_node(
                self._make_state(
                    support_issue={"category": "defective", "order_id": "ORD-2001"},
                    support_order={"order_id": "ORD-2001"},
                    severity="medium",
                    priority="P2",
                    policy={},
                )
            )
        assert "TKT-EXISTING" in result["final_response"]
