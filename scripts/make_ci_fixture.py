#!/usr/bin/env python3
"""Build the scrubbed database that CI replays the evals against (Phase 4, ADR 0015).

Copies multi_agent_baseline to <target> (default multi_agent_cifixture), then removes everything
that isn't needed or could be personal:
- users: only the demo shoppers and the synthetic users who own orders stay, and every email
  becomes <user_id>@example.com (names and Google ids are cleared);
- chat sessions, messages, support tickets, LangGraph checkpoints, reviews and specs: emptied;
- product embeddings: kept, with embedding_meta. CI used to recompute them, but another CPU's
  last digits reordered near-tied search results and broke the replay (2026-11-24); the query
  vectors are recorded for the same reason (eval/cassettes/query_vectors.json).

Then dump it (custom format) into the repo:

    python scripts/make_ci_fixture.py
    docker exec multiagent-db pg_dump -U postgres -Fc --no-owner multi_agent_cifixture > eval/fixtures/ci_baseline.dump

Copying needs no other open connections to the source database. Only a target whose name ends in
"_cifixture" is ever dropped and recreated.
"""

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from eval.run_baseline import DEFAULT_DB  # noqa: E402

EMPTIED = (
    "messages",
    "sessions",
    "support_tickets",
    "reviews",
    "specs",
    "checkpoint_writes",
    "checkpoint_blobs",
    "checkpoints",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-url", default=os.getenv("BASELINE_DATABASE_URL", DEFAULT_DB))
    parser.add_argument("--target", default="multi_agent_cifixture")
    args = parser.parse_args()
    if not args.target.endswith("_cifixture"):
        print("refusing: the target database name must end with _cifixture")
        return 1

    src = urlparse(args.source_url)
    admin = create_engine(urlunparse(src._replace(path="/postgres")), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{args.target}"'))
        conn.execute(text(f'CREATE DATABASE "{args.target}" TEMPLATE "{src.path.lstrip("/")}"'))
    admin.dispose()

    target = create_engine(urlunparse(src._replace(path=f"/{args.target}")))
    with target.begin() as conn:
        tables = {r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))}
        for table in EMPTIED:
            if table in tables:
                conn.execute(text(f'TRUNCATE TABLE "{table}" CASCADE'))
        conn.execute(
            text(
                "DELETE FROM users u WHERE u.user_id NOT LIKE 'demo-user-%' "
                "AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.user_id)"
            )
        )
        conn.execute(
            text(
                "UPDATE users SET email = user_id || '@example.com', name = NULL, google_id = NULL, auth_provider = 'demo'"
            )
        )
        counts = conn.execute(
            text(
                "SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM orders), (SELECT count(*) FROM products), "
                "(SELECT count(*) FROM users WHERE email NOT LIKE '%@example.com')"
            )
        ).one()
    print(
        f"{args.target}: {counts[0]} users, {counts[1]} orders, {counts[2]} products; non-example emails: {counts[3]}"
    )
    return 0 if counts[3] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
