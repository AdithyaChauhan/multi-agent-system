import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.main import app

# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite:///./test.db"

@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def test_db(test_engine):
    TestingSessionLocal = sessionmaker(bind=test_engine)
    db = TestingSessionLocal()
    yield db
    db.rollback()
    db.close()

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture
def mock_llm_response():
    """Mock LLM response for router"""
    mock = MagicMock()
    mock.content = '{"intent": "order", "confidence": 0.95, "order_id": null}'
    return mock

@pytest.fixture
def mock_openai():
    """Patch ChatOpenAI to avoid real LLM calls"""
    with patch("langchain_openai.ChatOpenAI") as mock:
        yield mock
