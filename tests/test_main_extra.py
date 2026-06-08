"""
Extra tests for app/main.py — covers JWT auth path, session helpers,
expired session, the /messages endpoint, and per-turn feedback helpers.
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import (
    app,
    get_current_user_id,
    get_or_create_session,
    get_or_create_user,
    load_conversation_history,
    _get_langsmith_client,
    _submit_turn_feedback,
)
from app.core.jwt_utils import create_access_token

client = TestClient(app, raise_server_exceptions=False)


# ── get_current_user_id ──────────────────────────────────────────────────────


class TestGetCurrentUserId:
    def _make_request(self, headers=None):
        """Build a minimal Starlette Request mock."""
        req = MagicMock()
        req.headers = headers or {}
        return req

    def test_valid_jwt_returns_sub(self):
        token = create_access_token("user-123", "a@b.com", "Test User")
        req = self._make_request({"Authorization": f"Bearer {token}"})
        result = get_current_user_id(req)
        assert result == "user-123"

    def test_invalid_jwt_raises_401(self):
        from fastapi import HTTPException

        req = self._make_request({"Authorization": "Bearer invalid.token.here"})
        with pytest.raises(HTTPException) as exc_info:
            get_current_user_id(req)
        assert exc_info.value.status_code == 401

    def test_x_user_id_header_used_as_fallback(self):
        req = self._make_request({"x-user-id": "test-user-42"})
        result = get_current_user_id(req)
        assert result == "test-user-42"

    def test_anonymous_user_created_when_no_headers(self):
        req = self._make_request({})
        result = get_current_user_id(req)
        assert result.startswith("anon-")


# ── get_or_create_user ───────────────────────────────────────────────────────


class TestGetOrCreateUser:
    def test_returns_existing_user(self):
        from app.models.user import User

        existing = User(user_id="existing-user")
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = existing

        result = get_or_create_user(mock_db, "existing-user")
        assert result.user_id == "existing-user"
        mock_db.add.assert_not_called()

    def test_creates_new_user_when_missing(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        get_or_create_user(mock_db, "new-user-99")
        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()


# ── get_or_create_session ────────────────────────────────────────────────────


class TestGetOrCreateSession:
    def _fresh_session(self, session_id="sess-1", user_id="u1"):
        from app.models.session import Session

        sess = MagicMock(spec=Session)
        sess.session_id = session_id
        sess.user_id = user_id
        sess.last_active_at = datetime.now(timezone.utc)
        return sess

    def test_creates_new_session_when_no_id_given(self):
        mock_db = MagicMock()
        sess = get_or_create_session(mock_db, None, "user-1")
        mock_db.add.assert_called_once()
        assert sess.user_id == "user-1"

    def test_creates_session_with_provided_id_when_not_found(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        sess = get_or_create_session(mock_db, "custom-sess-id", "user-1")
        assert sess.session_id == "custom-sess-id"

    def test_returns_existing_active_session(self):
        existing = self._fresh_session("sess-active")
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = existing

        result = get_or_create_session(mock_db, "sess-active", "user-1")
        assert result.session_id == "sess-active"

    def test_raises_410_for_expired_session(self):
        from fastapi import HTTPException

        expired = self._fresh_session()
        expired.last_active_at = datetime.now(timezone.utc) - timedelta(hours=48)
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = expired

        with pytest.raises(HTTPException) as exc_info:
            get_or_create_session(mock_db, "old-sess", "user-1")
        assert exc_info.value.status_code == 410


# ── load_conversation_history ────────────────────────────────────────────────


class TestLoadConversationHistory:
    def test_returns_messages_as_dicts(self):
        from app.models.message import Message

        msg1 = MagicMock(spec=Message)
        msg1.role = "user"
        msg1.content = "Hello"
        msg2 = MagicMock(spec=Message)
        msg2.role = "assistant"
        msg2.content = "Hi there"

        mock_db = MagicMock()
        # desc() + limit returns newest-first; load_conversation_history reverses to chronological
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
            msg2,
            msg1,
        ]

        result = load_conversation_history(mock_db, "sess-1")
        assert result == [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi there"}]

    def test_returns_empty_for_no_messages(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        result = load_conversation_history(mock_db, "sess-empty")
        assert result == []


# ── /chat endpoint ────────────────────────────────────────────────────────────


class TestChatEndpoint:
    def test_chat_returns_response_with_session_id(self):
        mock_result = {"final_response": "Here are some headphones."}

        with patch("app.main.router_graph") as mock_graph:
            mock_graph.invoke.return_value = mock_result
            response = client.post(
                "/chat",
                json={"message": "show me headphones"},
                headers={"x-user-id": "test-user-1"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert "session_id" in data
        assert data["response"] == "Here are some headphones."

    def test_chat_reuses_session_across_turns(self):
        mock_result = {"final_response": "Order found."}

        with patch("app.main.router_graph") as mock_graph:
            mock_graph.invoke.return_value = mock_result
            resp1 = client.post(
                "/chat",
                json={"message": "my orders"},
                headers={"x-user-id": "test-user-session"},
            )
            session_id = resp1.json()["session_id"]

            resp2 = client.post(
                "/chat",
                json={"message": "track ORD-001"},
                headers={"x-user-id": "test-user-session", "x-session-id": session_id},
            )

        assert resp2.status_code == 200
        assert resp2.json()["session_id"] == session_id

    def test_chat_returns_500_on_agent_error(self):
        with patch("app.main.router_graph") as mock_graph:
            mock_graph.invoke.side_effect = RuntimeError("Agent crashed")
            response = client.post(
                "/chat",
                json={"message": "hello"},
                headers={"x-user-id": "test-user-err"},
            )

        assert response.status_code == 500

    def test_expired_session_returns_410(self):
        # Create a session then expire it via the DB
        mock_result = {"final_response": "Hello."}
        with patch("app.main.router_graph") as mock_graph:
            mock_graph.invoke.return_value = mock_result
            resp = client.post(
                "/chat",
                json={"message": "hi"},
                headers={"x-user-id": "expiry-test-user"},
            )
        session_id = resp.json()["session_id"]

        # Manually expire the session
        from app.db.database import SessionLocal as DBSession
        from app.models.session import Session as SessionModel

        db = DBSession()
        try:
            sess = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
            if sess:
                sess.last_active_at = datetime.now(timezone.utc) - timedelta(hours=48)
                db.commit()
        finally:
            db.close()

        with patch("app.main.router_graph") as mock_graph:
            mock_graph.invoke.return_value = mock_result
            response = client.post(
                "/chat",
                json={"message": "follow-up"},
                headers={"x-user-id": "expiry-test-user", "x-session-id": session_id},
            )

        assert response.status_code == 410


# ── /messages endpoint ────────────────────────────────────────────────────────


class TestMessagesEndpoint:
    def test_messages_returns_history(self):
        # Create a chat first so the session and messages exist
        mock_result = {"final_response": "Product shown."}
        with patch("app.main.router_graph") as mock_graph:
            mock_graph.invoke.return_value = mock_result
            resp = client.post(
                "/chat",
                json={"message": "show headphones"},
                headers={"x-user-id": "hist-user-1"},
            )
        session_id = resp.json()["session_id"]

        get_resp = client.get(f"/messages/{session_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["session_id"] == session_id
        assert isinstance(data["messages"], list)
        assert len(data["messages"]) >= 2  # user + assistant

    def test_messages_404_for_unknown_session(self):
        response = client.get("/messages/nonexistent-session-id-xyz")
        assert response.status_code == 404


# ── root redirect ─────────────────────────────────────────────────────────────


class TestRootEndpoint:
    def test_root_redirects_to_chat(self):
        response = client.get("/", follow_redirects=False)
        assert response.status_code in (302, 307, 308)
        assert "/static/chat.html" in response.headers.get("location", "")


# ── _get_langsmith_client ─────────────────────────────────────────────────────


class TestGetLangsmithClient:
    def setup_method(self):
        import app.main as m

        m._LANGSMITH_CLIENT = None  # reset singleton before each test

    def test_returns_client_when_key_set(self):
        mock_client = MagicMock()
        with patch.dict("os.environ", {"LANGCHAIN_API_KEY": "lsv2_test_key"}):
            with patch("langsmith.Client", return_value=mock_client):
                result = _get_langsmith_client()
        assert result is mock_client

    def test_returns_none_when_no_key(self):
        with patch.dict("os.environ", {}, clear=True):
            import app.main as m

            m._LANGSMITH_CLIENT = None
            # Remove both key vars from env
            with patch("os.getenv", return_value=None):
                result = _get_langsmith_client()
        assert result is None

    def test_singleton_not_reinitialised(self):
        existing = MagicMock()
        import app.main as m

        m._LANGSMITH_CLIENT = existing
        result = _get_langsmith_client()
        assert result is existing


# ── _submit_turn_feedback ────────────────────────────────────────────────────


class TestSubmitTurnFeedback:
    def _mock_client(self):
        return MagicMock()

    def test_calls_create_feedback_three_times(self):
        mock_client = self._mock_client()
        with patch("app.main._get_langsmith_client", return_value=mock_client):
            _submit_turn_feedback("run-id-001", "show headphones", "Here are three headphones you might like.")
        assert mock_client.create_feedback.call_count == 3

    def test_quality_zero_for_short_response(self):
        mock_client = self._mock_client()
        with patch("app.main._get_langsmith_client", return_value=mock_client):
            _submit_turn_feedback("run-id-002", "hi", "Ok")
        calls = {c.kwargs["key"]: c.kwargs["score"] for c in mock_client.create_feedback.call_args_list}
        assert calls["response_quality"] == 0.0

    def test_relevance_penalised_for_fallback_response(self):
        mock_client = self._mock_client()
        fallback = "I didn't quite understand your request. Are you looking for a product?"
        with patch("app.main._get_langsmith_client", return_value=mock_client):
            _submit_turn_feedback("run-id-003", "xyz", fallback)
        calls = {c.kwargs["key"]: c.kwargs["score"] for c in mock_client.create_feedback.call_args_list}
        assert calls["relevance"] == 0.5

    def test_conciseness_decays_for_long_response(self):
        mock_client = self._mock_client()
        long_text = "word " * 700  # ~3500 chars
        with patch("app.main._get_langsmith_client", return_value=mock_client):
            _submit_turn_feedback("run-id-004", "q", long_text)
        calls = {c.kwargs["key"]: c.kwargs["score"] for c in mock_client.create_feedback.call_args_list}
        assert calls["conciseness"] == 0.0

    def test_no_error_when_client_is_none(self):
        with patch("app.main._get_langsmith_client", return_value=None):
            _submit_turn_feedback("run-id-005", "hi", "response")  # must not raise

    def test_no_error_when_run_id_is_empty(self):
        mock_client = self._mock_client()
        with patch("app.main._get_langsmith_client", return_value=mock_client):
            _submit_turn_feedback("", "hi", "response")  # must not raise
        mock_client.create_feedback.assert_not_called()
