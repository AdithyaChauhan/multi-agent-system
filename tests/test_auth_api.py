import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.jwt_utils import create_access_token


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


class TestAuthMe:

    def test_me_returns_user_info(self, client):
        token = create_access_token("user-test-1", "test@example.com", "Test User")
        response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "user-test-1"
        assert data["email"] == "test@example.com"
        assert data["name"] == "Test User"

    def test_me_missing_header(self, client):
        response = client.get("/auth/me")
        assert response.status_code == 401

    def test_me_invalid_token(self, client):
        response = client.get("/auth/me", headers={"Authorization": "Bearer invalidtoken"})
        assert response.status_code == 401

    def test_me_malformed_header(self, client):
        response = client.get("/auth/me", headers={"Authorization": "notbearer token"})
        assert response.status_code == 401


class TestAuthLogout:

    def test_logout_returns_message(self, client):
        response = client.post("/auth/logout")
        assert response.status_code == 200
        assert "Logged out" in response.json()["message"]


class TestDemoLogin:

    def test_demo_login_returns_token(self, client):
        response = client.post("/auth/demo-login", json={"user_id": "demo-user-123"})
        assert response.status_code == 200
        assert "access_token" in response.json()

    def test_demo_login_missing_user_id(self, client):
        response = client.post("/auth/demo-login", json={})
        assert response.status_code == 400

    def test_demo_login_empty_user_id(self, client):
        response = client.post("/auth/demo-login", json={"user_id": "   "})
        assert response.status_code == 400

    def test_demo_login_existing_user(self, client):
        client.post("/auth/demo-login", json={"user_id": "existing-user"})
        response = client.post("/auth/demo-login", json={"user_id": "existing-user"})
        assert response.status_code == 200
        assert "access_token" in response.json()
