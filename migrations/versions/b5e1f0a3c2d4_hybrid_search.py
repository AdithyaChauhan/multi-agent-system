"""hybrid search: pgvector embeddings and a full-text column on products (ADR 0006, 0014)

Revision ID: b5e1f0a3c2d4
Revises: a7d4e2c9b1f0
Create Date: 2026-11-23 18:30:00.000000

Postgres only; on any other database this is a no-op (unit tests run on SQLite and never use
these columns). The vectors come from `scripts/embed_catalog.py`, not from this migration.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b5e1f0a3c2d4"
down_revision: Union[str, Sequence[str], None] = "a7d4e2c9b1f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DIM = 384  # BAAI/bge-small-en-v1.5


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(f"ALTER TABLE products ADD COLUMN IF NOT EXISTS embedding vector({DIM})")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_products_embedding ON products USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS search_tsv tsvector GENERATED ALWAYS AS "
        "(to_tsvector('english', coalesce(title, '') || ' ' || coalesce(name, '') || ' ' || coalesce(brand, ''))) "
        "STORED"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_products_search_tsv ON products USING gin (search_tsv)")
    op.execute(
        "CREATE TABLE IF NOT EXISTS embedding_meta ("
        "model text PRIMARY KEY, dim integer NOT NULL, products integer NOT NULL, "
        "updated_at timestamptz NOT NULL DEFAULT now())"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TABLE IF EXISTS embedding_meta")
    op.execute("DROP INDEX IF EXISTS idx_products_search_tsv")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS search_tsv")
    op.execute("DROP INDEX IF EXISTS idx_products_embedding")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS embedding")
