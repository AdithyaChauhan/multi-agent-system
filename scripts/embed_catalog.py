#!/usr/bin/env python3
"""Embed every product for hybrid search (ADR 0014). Safe to re-run: it recomputes all vectors.

Each product is embedded from its own words (title, kind, full name, attribute values), never from
type or category names. The model name is recorded in embedding_meta; the app uses hybrid search
only when that row matches its EMBEDDING_MODEL.

    python scripts/embed_catalog.py --database-url postgresql://USER:PASSWORD@localhost:5433/multi_agent_baseline

Needs the b5e1f0a3c2d4 migration (pgvector). About two minutes for 1,350 products on a laptop CPU.
"""

import argparse
import os
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    args = parser.parse_args()
    if not args.database_url.startswith("postgresql"):
        print("needs a Postgres --database-url (or DATABASE_URL)")
        return 1

    from app.core.config import EMBEDDING_MODEL
    from app.search.embeddings import embed_documents, product_document, to_pgvector

    engine = create_engine(args.database_url)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, title, name, attributes FROM products ORDER BY id")).all()
    start = time.perf_counter()
    vectors = embed_documents([product_document(title, name, attrs) for _, title, name, attrs in rows])
    with engine.begin() as conn:
        for (pid, *_), vec in zip(rows, vectors):
            conn.execute(
                text("UPDATE products SET embedding = CAST(:v AS vector) WHERE id = :id"),
                {"v": to_pgvector(vec), "id": pid},
            )
        conn.execute(text("DELETE FROM embedding_meta"))
        conn.execute(
            text("INSERT INTO embedding_meta (model, dim, products) VALUES (:m, :d, :n)"),
            {"m": EMBEDDING_MODEL, "d": len(vectors[0]) if vectors else 0, "n": len(rows)},
        )
    print(f"embedded {len(rows)} products with {EMBEDDING_MODEL} in {time.perf_counter() - start:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
