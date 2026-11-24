"""Where conversation state lives: memory in tests, a checked connection pool on Postgres."""

import langgraph.checkpoint.postgres as lg_postgres
import psycopg_pool
from langgraph.checkpoint.memory import InMemorySaver

from app.core import checkpoint


def test_without_postgres_the_state_lives_in_memory(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    assert isinstance(checkpoint.make_checkpointer(), InMemorySaver)


def test_postgres_pool_replaces_connections_a_serverless_database_closed(monkeypatch):
    # Neon's free plan suspends after 5 idle minutes and closes every connection. The pool must
    # check a connection before handing it out, and drop idle ones before the server does
    # (reproduced on 2026-11-24: two turns failed with a 500 after a suspend).
    created = {}

    class FakePool:
        @staticmethod
        def check_connection(conn):
            return None

        def __init__(self, conninfo, **kwargs):
            created.update(conninfo=conninfo, **kwargs)

    class FakeSaver:
        def __init__(self, pool):
            self.pool = pool
            self.ready = False

        def setup(self):
            self.ready = True

    monkeypatch.setattr(psycopg_pool, "ConnectionPool", FakePool)
    monkeypatch.setattr(lg_postgres, "PostgresSaver", FakeSaver)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://user:pw@db:5432/app")

    saver = checkpoint.make_checkpointer()

    assert saver.ready
    assert created["conninfo"] == "postgresql://user:pw@db:5432/app"
    assert created["check"] is FakePool.check_connection
    assert created["max_idle"] < 300  # under Neon's suspend timeout
