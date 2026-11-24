"""Where the graph keeps a conversation's state between turns (ADR 0009).

One thread per chat session (thread_id = session id). On Postgres the state survives restarts and
is shared by every app instance; anywhere else (the SQLite unit tests) it lives in memory.
The saver creates and migrates its own tables (checkpoints, checkpoint_blobs, checkpoint_writes,
checkpoint_migrations) with `setup()`; they are not part of the Alembic history.
"""

import os

from langgraph.checkpoint.memory import InMemorySaver

from app.core.logger import get_logger

logger = get_logger("app.core.checkpoint")


def make_checkpointer():
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        return InMemorySaver()
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    conninfo = url.replace("postgresql+psycopg2://", "postgresql://", 1)
    # autocommit: setup() creates indexes concurrently; dict_row: the saver reads rows by column name.
    pool = ConnectionPool(
        conninfo,
        min_size=1,
        max_size=10,
        open=True,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    saver = PostgresSaver(pool)
    saver.setup()
    logger.info("Graph checkpointer: Postgres")
    return saver
