import uuid
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
    """Only the seeded demo shoppers (demo-user-N) can sign in without a password."""

    @pytest.fixture
    def demo_user(self):
        from app.db.database import SessionLocal
        from app.models.user import User

        db = SessionLocal()
        if not db.query(User).filter(User.user_id == "demo-user-7").first():
            db.add(User(user_id="demo-user-7", auth_provider="demo"))
            db.commit()
        db.close()
        return "demo-user-7"

    def test_demo_account_gets_a_token(self, client, demo_user):
        response = client.post("/auth/demo-login", json={"user_id": demo_user})
        assert response.status_code == 200
        assert "access_token" in response.json()

    def test_missing_or_empty_id_is_refused(self, client):
        assert client.post("/auth/demo-login", json={}).status_code == 403
        assert client.post("/auth/demo-login", json={"user_id": "   "}).status_code == 403

    def test_other_ids_are_refused_and_not_created(self, client):
        fresh_id = f"fresh-{uuid.uuid4()}"
        assert client.post("/auth/demo-login", json={"user_id": fresh_id}).status_code == 403
        assert client.post("/auth/demo-login", json={"user_id": "existing-user"}).status_code == 403
