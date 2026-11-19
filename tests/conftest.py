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


TEST_BRANDS = [(1, "Xiaomi", ["MI", "Mi", "Redmi"]), (2, "Sony", []), (3, "Logitech", []), (4, "JBL", [])]


def build_test_catalog():
    """The real product types from data/catalog/product_types.yaml, with a few test brands."""
    from app.catalog.runtime import build_catalog
    from app.catalog.schema import load_types

    rows = [
        (i, t.name, t.category, t.served, list(t.synonyms), t.suggestion, t.attribute_schema())
        for i, t in enumerate(load_types().values(), 1)
    ]
    return build_catalog(rows, TEST_BRANDS)


@pytest.fixture
def yaml_catalog():
    """Patch the runtime catalog everywhere search reads it."""
    catalog = build_test_catalog()
    with patch("app.agents.product_agent.get_catalog", return_value=catalog), patch(
        "app.tools.product_tools.get_catalog", return_value=catalog
    ):
        yield catalog


@pytest.fixture
def mock_llm_response():
    """Mock LLM response for router"""
    mock = MagicMock()
    mock.content = '{"intent": "order", "confidence": 0.95, "order_id": null}'
    return mock


@pytest.fixture
def mock_groq():
    """Patch ChatGroq to avoid real LLM calls"""
    with patch("langchain_groq.ChatGroq") as mock:
        yield mock
