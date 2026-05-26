import pytest
from unittest.mock import MagicMock, patch
from app.core.jwt_utils import create_access_token, verify_access_token


class TestJWTUtils:

    def test_create_token_structure(self):
        """JWT token has 3 parts separated by dots"""
        token = create_access_token("user-1", "test@test.com", "Test User")
        parts = token.split(".")
        assert len(parts) == 3

    def test_verify_token_contains_correct_sub(self):
        """Verified token contains correct user_id"""
        token = create_access_token("user-123", "test@test.com", "Test")
        payload = verify_access_token(token)
        assert payload["sub"] == "user-123"

    def test_verify_token_contains_email(self):
        """Verified token contains email"""
        token = create_access_token("user-1", "hello@test.com", "Test")
        payload = verify_access_token(token)
        assert payload["email"] == "hello@test.com"

    def test_verify_token_contains_name(self):
        """Verified token contains name"""
        token = create_access_token("user-1", "test@test.com", "John Doe")
        payload = verify_access_token(token)
        assert payload["name"] == "John Doe"

    def test_verify_tampered_token(self):
        """Tampered token returns None"""
        token = create_access_token("user-1", "test@test.com", "Test")
        tampered = token[:-5] + "XXXXX"
        result = verify_access_token(tampered)
        assert result is None

    def test_verify_empty_token(self):
        """Empty token returns None"""
        result = verify_access_token("")
        assert result is None

    def test_verify_random_string(self):
        """Random string returns None"""
        result = verify_access_token("not.a.jwt")
        assert result is None
