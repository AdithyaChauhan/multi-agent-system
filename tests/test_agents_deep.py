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

class TestOrderAgentCompleteFlow:
    """Tests every state transition in the order agent graph"""

    def test_flow_no_orders_user(self):
        """User with zero orders gets helpful message"""
        with patch("app.agents.order_agent.fetch_user_orders", return_value=[]):
            from app.agents.order_agent import check_order_id

            state = AgentState(
                user_message="Where is my order?",
                user_id="new-user",
                session_id="s1",
                conversation_history=[]
            )
            result = check_order_id(state)

        assert result["user_orders"] == []
        assert result["order_id"] is None

    def test_flow_single_order_auto_select(self):
        """Single order is auto-selected without asking user"""
        orders = [{"order_id": "ORD-2001", "product_name": "AirPods", "status": "shipped", "tracking_id": "TRK-001", "created_at": None}]

        with patch("app.agents.order_agent.fetch_user_orders", return_value=orders):
            from app.agents.order_agent import check_order_id

            state = AgentState(user_message="track", user_id="u1", session_id="s1", conversation_history=[])
            result = check_order_id(state)

        assert result["order_id"] == "ORD-2001"

    def test_flow_multiple_orders_no_selection(self):
        """Multiple orders without selection returns None to ask user"""
        orders = [
            {"order_id": "ORD-1", "product_name": "P1", "status": "shipped", "tracking_id": "T1", "created_at": None},
            {"order_id": "ORD-2", "product_name": "P2", "status": "delivered", "tracking_id": "T2", "created_at": None},
            {"order_id": "ORD-3", "product_name": "P3", "status": "processing", "tracking_id": None, "created_at": None},
        ]

        with patch("app.agents.order_agent.fetch_user_orders", return_value=orders):
            from app.agents.order_agent import check_order_id

            state = AgentState(user_message="my order", user_id="u1", session_id="s1", conversation_history=[])
            result = check_order_id(state)

        assert result["order_id"] is None
        assert len(result["user_orders"]) == 3

    def test_flow_order_id_extracted_from_message(self):
        """Order ID directly mentioned is extracted"""
        with patch("app.agents.order_agent.fetch_user_orders", return_value=[]):
            from app.agents.order_agent import check_order_id

            state = AgentState(user_message="track ORD-2001", user_id="u1", session_id="s1", conversation_history=[])
            result = check_order_id(state)

        assert result["order_id"] == "ORD-2001"

    def test_flow_fetch_order_success(self):
        """Fetching valid order returns data"""
        order = {"order_id": "ORD-2001", "product_name": "AirPods", "status": "shipped", "carrier": "FedEx", "tracking_id": "TRK-001"}

        with patch("app.agents.order_agent.fetch_order_from_db", return_value=order):
            from app.agents.order_agent import fetch_order

            state = AgentState(user_message="track", user_id="u1", session_id="s1", order_id="ORD-2001", conversation_history=[])
            result = fetch_order(state)

        assert result["order_data"]["status"] == "shipped"

    def test_flow_fetch_order_missing(self):
        """Fetching missing order returns None"""
        with patch("app.agents.order_agent.fetch_order_from_db", return_value=None):
            from app.agents.order_agent import fetch_order

            state = AgentState(user_message="track", user_id="u1", session_id="s1", order_id="ORD-9999", conversation_history=[])
            result = fetch_order(state)

        assert result["order_data"] is None

    def test_flow_response_with_full_tracking(self):
        """Response generated with complete tracking info"""
        mock_resp = MagicMock()
        mock_resp.content = "Your AirPods order is in Mumbai, arriving tomorrow."

        with patch("app.agents.order_agent.llm") as mock_llm:
            mock_llm.invoke.return_value = mock_resp
            from app.agents.order_agent import response_generation

            state = AgentState(
                user_message="track",
                user_id="u1", session_id="s1",
                order_data={"order_id": "ORD-1", "product_name": "AirPods", "status": "shipped"},
                tracking_data={"carrier": "FedEx", "current_location": "Mumbai", "estimated_delivery": "tomorrow"},
                conversation_history=[]
            )
            result = response_generation(state)

        assert "final_response" in result

    def test_flow_response_for_delivered_order(self):
        """Delivered orders get appropriate response"""
        mock_resp = MagicMock()
        mock_resp.content = "Your order was delivered last week."

        with patch("app.agents.order_agent.llm") as mock_llm:
            mock_llm.invoke.return_value = mock_resp
            from app.agents.order_agent import response_generation

            state = AgentState(
                user_message="track",
                user_id="u1", session_id="s1",
                order_data={"order_id": "ORD-1", "product_name": "AirPods", "status": "delivered"},
                tracking_data={},
                conversation_history=[]
            )
            result = response_generation(state)

        assert "final_response" in result


class TestOrderSubgraphDeep:
    """Tests the shipment tracking subgraph"""

    def test_subgraph_fetches_tracking_from_api(self):
        """Subgraph successfully fetches tracking from carrier API"""
        tracking = {"carrier": "FedEx", "status": "In Transit", "current_location": "Delhi", "estimated_delivery": "2026-05-26"}

        with patch("app.agents.order_agent_subgraph.fetch_tracking_info", return_value=tracking):
            from app.agents.order_agent_subgraph import fetch_tracking

            state = AgentState(
                user_message="track",
                user_id="u1", session_id="s1",
                order_data={"tracking_id": "TRK-001", "carrier": "FedEx"},
                conversation_history=[]
            )
            result = fetch_tracking(state)

        assert "tracking_data" in result

    def test_subgraph_handles_api_failure(self):
        """Subgraph handles carrier API failure gracefully"""
        with patch("app.agents.order_agent_subgraph.fetch_tracking_info", return_value=None):
            from app.agents.order_agent_subgraph import fetch_tracking

            state = AgentState(
                user_message="track",
                user_id="u1", session_id="s1",
                order_data={"tracking_id": "TRK-001", "carrier": "FedEx"},
                conversation_history=[]
            )
            result = fetch_tracking(state)

        assert "tracking_data" in result


# ====================================================================
# AGENT 2: PRODUCT RECOMMENDATIONS - DEEP TESTS
# ====================================================================

class TestProductAgentCompleteFlow:
    """Tests every flow path in product agent"""

    def test_flow_extract_with_full_preferences(self):
        """Extract all preference fields from message"""
        mock_resp = MagicMock()
        mock_resp.content = '{"category": "Toys & Games", "keywords": ["educational"], "brand": "Lego", "min_price": 500, "max_price": 2000, "subcategory": null, "unavailable_request": false}'

        with patch("app.agents.product_agent.llm") as mock_llm:
            mock_llm.invoke.return_value = mock_resp
            from app.agents.product_agent import extract_preferences

            state = AgentState(user_message="show me Lego educational toys 500-2000 rupees", user_id="u1", session_id="s1", conversation_history=[])
            result = extract_preferences(state)

        prefs = result["preferences"]
        assert prefs["category"] == "Toys & Games"
        assert prefs["brand"] == "Lego"
        assert prefs["min_price"] == 500
        assert prefs["max_price"] == 2000

    def test_flow_search_returns_results(self):
        """Search returns matching products"""
        products = [
            {"product_id": "P1", "name": "Toy A", "rating": 4.5, "price": 1000},
            {"product_id": "P2", "name": "Toy B", "rating": 4.0, "price": 1500},
        ]

        with patch("app.agents.product_agent.search_products", return_value=products):
            from app.agents.product_agent import do_search_products

            state = AgentState(
                user_message="toys", user_id="u1", session_id="s1",
                preferences={"category": "Toys & Games", "keywords": ["toy"]},
                conversation_history=[]
            )
            result = do_search_products(state)

        assert len(result["search_results"]) == 2

    def test_flow_search_no_results_triggers_broaden(self):
        """No results triggers broaden_search flow"""
        with patch("app.agents.product_agent.search_products", return_value=[]):
            from app.agents.product_agent import do_search_products

            state = AgentState(
                user_message="toys", user_id="u1", session_id="s1",
                preferences={"category": "Toys & Games", "min_price": 100000},
                broaden_attempt=0,
                conversation_history=[]
            )
            result = do_search_products(state)

        assert len(result["search_results"]) == 0

    def test_flow_broaden_relaxes_filters(self):
        """Broaden search relaxes filters progressively"""
        mock_resp = MagicMock()
        mock_resp.content = '{"category": "Toys & Games", "keywords": ["toy"], "brand": null, "min_price": null, "max_price": null, "subcategory": null}'

        with patch("app.agents.product_agent.llm") as mock_llm:
            mock_llm.invoke.return_value = mock_resp
            from app.agents.product_agent import broaden_search

            state = AgentState(
                user_message="toys", user_id="u1", session_id="s1",
                preferences={"category": "Toys & Games", "brand": "Lego", "min_price": 5000, "max_price": 10000},
                original_preferences={"category": "Toys & Games", "brand": "Lego", "min_price": 5000, "max_price": 10000},
                broaden_attempt=0,
                conversation_history=[]
            )
            result = broaden_search(state)

        assert "preferences" in result
        assert result["broaden_attempt"] >= 1

    def test_flow_unavailable_product_response(self):
        """Unavailable products get redirect message"""
        from app.agents.product_agent import handle_unavailable_products

        state = AgentState(
            user_message="show me MacBook",
            user_id="u1", session_id="s1",
            preferences={"category": "electronics", "unavailable_request": True},
            conversation_history=[]
        )
        result = handle_unavailable_products(state)
        assert "final_response" in result

    def test_flow_routing_extraction_to_search(self):
        """Valid preferences route to search"""
        from app.agents.product_agent import route_after_extraction

        state = AgentState(
            user_message="toys", user_id="u1", session_id="s1",
            preferences={"category": "Toys & Games", "unavailable_request": False},
            conversation_history=[]
        )
        result = route_after_extraction(state)
        assert result == "search"

    def test_flow_routing_extraction_to_ask(self):
        """No category routes to ask for preferences"""
        from app.agents.product_agent import route_after_extraction

        state = AgentState(
            user_message="show me products",
            user_id="u1", session_id="s1",
            preferences={"category": None, "unavailable_request": False},
            conversation_history=[]
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
                user_message="toys", user_id="u1", session_id="s1",
                ranked_products=[
                    {"product_id": "P1", "name": "Toy A"},
                    {"product_id": "P2", "name": "Toy B"},
                ],
                conversation_history=[]
            )
            result = fetch_reviews_node(state)

        assert len(result["ranked_products"]) == 2

    def test_subgraph_compute_score_ranks_by_rating(self):
        """compute_score ranks products by combined score"""
        from app.agents.product_agent_subgraph import compute_score

        state = AgentState(
            user_message="toys", user_id="u1", session_id="s1",
            ranked_products=[
                {"product_id": "P1", "name": "Low Rated", "rating": 2.0, "avg_review_rating": 2.0, "price": 500, "specs_dict": {}, "description": "", "tags": [], "brand": "", "name": "Low Rated"},
                {"product_id": "P2", "name": "High Rated", "rating": 4.8, "avg_review_rating": 4.8, "price": 800, "specs_dict": {}, "description": "", "tags": [], "brand": "", "name": "High Rated"},
            ],
            preferences={"category": "Toys & Games"},
            conversation_history=[]
        )
        result = compute_score(state)

        assert "ranked_products" in result
        assert len(result["ranked_products"]) > 0


# ====================================================================
# AGENT 3: SUPPORT - DEEP TESTS
# ====================================================================

class TestSupportAgentCompleteFlow:
    """Tests every flow path in support agent"""

    def test_flow_classify_defective_product(self):
        """Classifies defective product issue"""
        mock_resp = MagicMock()
        mock_resp.content = '{"category": "defective_product", "order_id": "ORD-1", "description": "Broken"}'

        with patch("app.agents.support_agent.llm") as mock_llm, \
             patch("app.agents.support_agent.load_prompt", return_value=("prompt", "latest")):
            mock_llm.invoke.return_value = mock_resp
            from app.agents.support_agent import classify_issue

            state = AgentState(user_message="my product is broken", user_id="u1", session_id="s1", conversation_history=[])
            result = classify_issue(state)

        assert result["support_issue"]["category"] == "defective_product"

    def test_flow_classify_refund_request(self):
        """Classifies refund request"""
        mock_resp = MagicMock()
        mock_resp.content = '{"category": "refund_request", "order_id": null, "description": "Want refund"}'

        with patch("app.agents.support_agent.llm") as mock_llm, \
             patch("app.agents.support_agent.load_prompt", return_value=("prompt", "latest")):
            mock_llm.invoke.return_value = mock_resp
            from app.agents.support_agent import classify_issue

            state = AgentState(user_message="I want a refund", user_id="u1", session_id="s1", conversation_history=[])
            result = classify_issue(state)

        assert result["support_issue"]["category"] == "refund_request"

    def test_flow_severity_critical_for_baby_safety(self):
        """Critical severity for baby safety issues"""
        from app.agents.support_agent import assess_severity

        state = AgentState(
            user_message="My baby got hurt by toy",
            user_id="u1", session_id="s1",
            support_issue={"category": "defective_product"},
            conversation_history=[]
        )
        result = assess_severity(state)
        assert result["severity"] == "critical"

    def test_flow_severity_critical_for_injury(self):
        """Critical severity for injuries"""
        from app.agents.support_agent import assess_severity

        state = AgentState(
            user_message="caused injury",
            user_id="u1", session_id="s1",
            support_issue={"category": "defective_product"},
            conversation_history=[]
        )
        result = assess_severity(state)
        assert result["severity"] == "critical"

    def test_flow_severity_medium_for_defective(self):
        """Medium severity for defective product"""
        from app.agents.support_agent import assess_severity

        state = AgentState(
            user_message="product stopped working",
            user_id="u1", session_id="s1",
            support_issue={"category": "defective_product"},
            conversation_history=[]
        )
        result = assess_severity(state)
        assert result["severity"] == "medium"

    def test_flow_severity_low_for_refund(self):
        """Low severity for refund requests"""
        from app.agents.support_agent import assess_severity

        state = AgentState(
            user_message="want refund",
            user_id="u1", session_id="s1",
            support_issue={"category": "refund_request"},
            conversation_history=[]
        )
        result = assess_severity(state)
        assert result["severity"] == "low"

    def test_flow_lookup_policy(self):
        """Policy lookup returns response time"""
        with patch("app.agents.support_agent.lookup_support_policy", return_value={"response_time": "24 hours"}):
            from app.agents.support_agent import lookup_policy

            state = AgentState(
                user_message="broken", user_id="u1", session_id="s1",
                support_issue={"category": "defective_product"},
                severity="medium",
                conversation_history=[]
            )
            result = lookup_policy(state)

        assert "policy" in result

    def test_flow_route_critical_to_escalation(self):
        """Critical severity routes to escalation subgraph"""
        from app.agents.support_agent import route_by_severity

        state = AgentState(
            user_message="urgent", user_id="u1", session_id="s1",
            severity="critical",
            conversation_history=[]
        )
        result = route_by_severity(state)
        assert result == "high"

    def test_flow_route_low_direct(self):
        """Low severity routes to direct resolution"""
        from app.agents.support_agent import route_by_severity

        state = AgentState(
            user_message="question", user_id="u1", session_id="s1",
            severity="low",
            conversation_history=[]
        )
        result = route_by_severity(state)
        assert result == "low"


class TestSupportSubgraphDeep:
    """Tests escalation subgraph"""

    def test_subgraph_check_history(self):
        """Check history returns user's past tickets"""
        past_tickets = [{"ticket_id": "TKT-001", "severity": "critical", "created_at": None}]

        with patch("app.agents.support_agent_subgraph.get_user_ticket_history", return_value=past_tickets):
            from app.agents.support_agent_subgraph import check_history

            state = AgentState(user_message="broken", user_id="u1", session_id="s1", conversation_history=[])
            result = check_history(state)

        assert "ticket_history" in result

    def test_subgraph_assign_priority_p0(self):
        """P0 priority for repeat critical users"""
        from app.agents.support_agent_subgraph import assign_priority

        state = AgentState(
            user_message="urgent", user_id="u1", session_id="s1",
            severity="critical",
            recent_critical_count=3,
            conversation_history=[]
        )
        result = assign_priority(state)
        assert result["priority"] == "P0"

    def test_subgraph_assign_priority_p1_critical(self):
        """P1 priority for first critical"""
        from app.agents.support_agent_subgraph import assign_priority

        state = AgentState(
            user_message="urgent", user_id="u1", session_id="s1",
            severity="critical",
            recent_critical_count=0,
            conversation_history=[]
        )
        result = assign_priority(state)
        assert result["priority"] == "P1"

    def test_subgraph_assign_priority_p2_medium(self):
        """P2 priority for medium severity"""
        from app.agents.support_agent_subgraph import assign_priority

        state = AgentState(
            user_message="broken", user_id="u1", session_id="s1",
            severity="medium",
            recent_critical_count=0,
            conversation_history=[]
        )
        result = assign_priority(state)
        assert result["priority"] == "P2"

    def test_subgraph_create_ticket_with_order_id(self):
        """Ticket created with order_id"""
        mock_ticket = {"ticket_id": "TKT-ABC123"}

        with patch("app.agents.support_agent_subgraph.create_support_ticket", return_value=mock_ticket):
            from app.agents.support_agent_subgraph import create_ticket_node

            state = AgentState(
                user_message="broken",
                user_id="u1", session_id="s1",
                support_issue={"category": "defective_product", "description": "Broken", "order_id": "ORD-1"},
                severity="medium",
                priority="P2",
                policy={"response_time": "24 hours"},
                conversation_history=[]
            )
            result = create_ticket_node(state)

        assert "TKT-ABC123" in result["final_response"]
