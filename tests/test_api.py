import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


class TestHealthEndpoint:

    def test_health_check(self, client):
        """Health endpoint returns 200"""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestChatEndpoint:

    def test_chat_requires_message(self, client):
        """Chat endpoint requires message field"""
        response = client.post("/chat", json={})
        assert response.status_code == 422

    def test_chat_with_anonymous_user(self, client):
        """Chat works with anonymous user"""
        mock_result = {"final_response": "How can I help you?"}

        with patch("app.main.router_graph.invoke", return_value=mock_result):
            response = client.post(
                "/chat",
                json={"message": "Hello"},
            )
        assert response.status_code == 200
        assert "response" in response.json()

    def test_chat_returns_session_id(self, client):
        """Chat response includes session_id"""
        mock_result = {"final_response": "Hello!"}

        with patch("app.main.router_graph.invoke", return_value=mock_result):
            response = client.post(
                "/chat",
                json={"message": "Hello"},
            )
        assert "session_id" in response.json()

    def test_chat_with_user_id_header(self, client):
        """Chat works with X-User-ID header"""
        mock_result = {"final_response": "How can I help?"}

        with patch("app.main.router_graph.invoke", return_value=mock_result):
            response = client.post(
                "/chat",
                json={"message": "Hello"},
                headers={"x-user-id": "demo-user-1"}
            )
        assert response.status_code == 200
        assert response.json()["user_id"] == "demo-user-1"
