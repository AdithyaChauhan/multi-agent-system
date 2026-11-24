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

# Close a pooled connection after this long unused: under Neon's 5-minute suspend, so the pool drops
# it before the server does.
IDLE_SECONDS = 240


def make_checkpointer():
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        return InMemorySaver()
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    conninfo = url.replace("postgresql+psycopg2://", "postgresql://", 1)
    # autocommit: setup() creates indexes concurrently; dict_row: the saver reads rows by column name.
    # check + max_idle: a serverless database (Neon's free plan) suspends after 5 idle minutes and
    # closes every connection. Without a check on checkout, the next turns got dead connections and
    # failed with a 500 until the pool had cycled them (reproduced 2026-11-24 by suspending Neon).
    pool = ConnectionPool(
        conninfo,
        min_size=1,
        max_size=10,
        open=True,
        check=ConnectionPool.check_connection,
        max_idle=IDLE_SECONDS,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    saver = PostgresSaver(pool)
    saver.setup()
    logger.info("Graph checkpointer: Postgres")
    return saver
