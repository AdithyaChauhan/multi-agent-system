import pytest
from unittest.mock import MagicMock, patch


class TestOrderTools:

    def test_fetch_order_returns_dict(self):
        """fetch_order_from_db returns order as dict"""
        mock_order = MagicMock()
        mock_order.order_id = "ORD-2001"
        mock_order.user_id = "test-user"
        mock_order.product_name = "AirPods"
        mock_order.status = "shipped"
        mock_order.carrier = "FedEx"
        mock_order.tracking_id = "TRK-001"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_order

        with patch("app.tools.order_tools.SessionLocal", return_value=mock_db):
            from app.tools.order_tools import fetch_order_from_db
            result = fetch_order_from_db("ORD-2001", "test-user")

        assert result["order_id"] == "ORD-2001"
        assert result["status"] == "shipped"

    def test_fetch_order_returns_none_when_not_found(self):
        """fetch_order_from_db returns None for missing order"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.tools.order_tools.SessionLocal", return_value=mock_db):
            from app.tools.order_tools import fetch_order_from_db
            result = fetch_order_from_db("ORD-9999", "test-user")

        assert result is None

    def test_fetch_user_orders_returns_list(self):
        """fetch_user_orders returns list of orders"""
        mock_order = MagicMock()
        mock_order.order_id = "ORD-2001"
        mock_order.product_name = "AirPods"
        mock_order.status = "shipped"
        mock_order.tracking_id = "TRK-001"
        mock_order.created_at = None

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_order]

        with patch("app.tools.order_tools.SessionLocal", return_value=mock_db):
            from app.tools.order_tools import fetch_user_orders
            result = fetch_user_orders("test-user")

        assert len(result) == 1
        assert result[0]["order_id"] == "ORD-2001"


class TestSupportTools:

    def test_create_support_ticket_returns_ticket(self):
        """create_support_ticket returns ticket with ID"""
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("app.tools.support_tools.SessionLocal") as mock_session:
            mock_session.return_value = mock_db
            from app.tools.support_tools import create_support_ticket
            result = create_support_ticket(
                user_id="test-user",
                severity="medium",
                category="defective_product",
                description="Product broken"
            )

        assert "ticket_id" in result
        assert result["ticket_id"].startswith("TKT-")

    def test_lookup_support_policy_medium_severity(self):
        """Returns correct policy for medium severity"""
        from app.tools.support_tools import lookup_support_policy
        result = lookup_support_policy("defective_product", "medium")
        assert "response_time" in result

    def test_lookup_support_policy_critical_severity(self):
        """Returns faster response time for critical severity"""
        from app.tools.support_tools import lookup_support_policy
        result = lookup_support_policy("defective_product", "critical")
        assert "response_time" in result

    def test_get_user_ticket_history_returns_list(self):
        """Returns list of tickets for user"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        with patch("app.tools.support_tools.SessionLocal", return_value=mock_db):
            from app.tools.support_tools import get_user_ticket_history
            result = get_user_ticket_history("test-user")

        assert isinstance(result, list)

class TestSupportTools:

    def test_create_support_ticket_returns_ticket(self):
        """create_support_ticket returns ticket with ID"""
        with patch("app.tools.support_tools.SessionLocal") as mock_session_class:
            mock_db = MagicMock()
            mock_session_class.return_value = mock_db
            mock_db.close = MagicMock()

            from app.tools.support_tools import create_support_ticket
            result = create_support_ticket(
                user_id="test-user",
                severity="medium",
                category="defective_product",
                description="Product broken"
            )

        assert "ticket_id" in result
        assert result["ticket_id"].startswith("TKT-")

    def test_lookup_support_policy_returns_dict(self):
        """lookup_support_policy returns policy dict"""
        from app.tools.support_tools import lookup_support_policy
        result = lookup_support_policy("defective_product", "medium")
        assert "response_time" in result

    def test_lookup_support_policy_critical_severity(self):
        """Returns faster response for critical severity"""
        from app.tools.support_tools import lookup_support_policy
        result = lookup_support_policy("defective_product", "critical")
        assert "response_time" in result

    def test_get_user_ticket_history_returns_list(self):
        """Returns list of tickets for user"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        with patch("app.tools.support_tools.SessionLocal", return_value=mock_db):
            from app.tools.support_tools import get_user_ticket_history
            result = get_user_ticket_history("test-user")

        assert isinstance(result, list)

class TestShipmentTools:

    def test_fetch_tracking_info_returns_dict(self):
        """fetch_tracking_info returns tracking dict"""
        with patch("app.tools.shipment_tools.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "carrier": "FedEx",
                "status": "In Transit",
                "location": "Mumbai"
            }
            mock_get.return_value = mock_response

            from app.tools.shipment_tools import fetch_tracking_info
            result = fetch_tracking_info("TRK-001")

        assert isinstance(result, dict)

    def test_fetch_tracking_info_returns_none_on_404(self):
        """fetch_tracking_info returns None on 404"""
        with patch("app.tools.shipment_tools.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_get.return_value = mock_response

            from app.tools.shipment_tools import fetch_tracking_info
            result = fetch_tracking_info("TRK-999")

        assert result is None

    def test_fetch_tracking_info_handles_connection_error(self):
        """fetch_tracking_info returns None on connection error"""
        import httpx
        with patch("app.tools.shipment_tools.httpx.get") as mock_get:
            mock_get.side_effect = httpx.RequestError("Connection failed")

            from app.tools.shipment_tools import fetch_tracking_info
            result = fetch_tracking_info("TRK-001")

        assert result is None


class TestSupportTools:

    def test_create_support_ticket_returns_ticket(self):
        """create_support_ticket returns ticket with ID"""
        mock_db = MagicMock()
        mock_ticket = MagicMock()
        mock_ticket.ticket_id = "TKT-ABCD1234"
        mock_ticket.severity.value = "medium"
        mock_ticket.category.value = "defective_product"

        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        with patch("app.tools.support_tools.SessionLocal", return_value=mock_db), \
             patch("app.tools.support_tools.SupportTicket", return_value=mock_ticket):
            from app.tools.support_tools import create_support_ticket
            result = create_support_ticket(
                user_id="test-user",
                severity="medium",
                category="defective_product",
                description="Product broken"
            )

        assert "ticket_id" in result

    def test_lookup_support_policy_returns_dict(self):
        """lookup_support_policy returns policy dict"""
        from app.tools.support_tools import lookup_support_policy
        result = lookup_support_policy("defective_product", "medium")
        assert "response_time" in result

    def test_lookup_support_policy_critical_severity(self):
        """Returns policy for critical severity"""
        from app.tools.support_tools import lookup_support_policy
        result = lookup_support_policy("defective_product", "critical")
        assert "response_time" in result

    def test_get_user_ticket_history_returns_list(self):
        """Returns list of tickets for user"""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        with patch("app.tools.support_tools.SessionLocal", return_value=mock_db):
            from app.tools.support_tools import get_user_ticket_history
            result = get_user_ticket_history("test-user")

        assert isinstance(result, list)