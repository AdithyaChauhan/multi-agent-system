"""typed product catalog: product_types, brands and typed columns on products (ADR 0005)

Revision ID: a7d4e2c9b1f0
Revises: f3a9b2c7d1e5
Create Date: 2026-11-18 12:00:00.000000

Non-destructive: raw product columns (name, type, category, subcategory, brand, tags) stay as they
are. The data comes from `scripts/enrich_catalog.py apply`, not from this migration.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'a7d4e2c9b1f0'
down_revision: Union[str, Sequence[str], None] = 'f3a9b2c7d1e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_PRODUCT_COLUMNS = ("type_id", "brand_id", "title", "extracted_by", "confidence")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    # The app's startup create_all may already have created the two new tables.
    if "product_types" not in tables:
        op.create_table(
            "product_types",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String, nullable=False, unique=True),
            sa.Column("category", sa.String, nullable=False),
            sa.Column("served", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("synonyms", JSONB, nullable=False, server_default="[]"),
            sa.Column("suggestion", sa.String, nullable=True),
            sa.Column("attribute_schema", JSONB, nullable=False, server_default="{}"),
        )
    if "brands" not in tables:
        op.create_table(
            "brands",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String, nullable=False, unique=True),
            sa.Column("aliases", JSONB, nullable=False, server_default="[]"),
        )

    existing = {c["name"] for c in inspector.get_columns("products")}
    columns = {
        "type_id": sa.Column("type_id", sa.Integer, sa.ForeignKey("product_types.id"), nullable=True),
        "brand_id": sa.Column("brand_id", sa.Integer, sa.ForeignKey("brands.id"), nullable=True),
        "title": sa.Column("title", sa.String, nullable=True),
        "extracted_by": sa.Column("extracted_by", sa.String, nullable=True),
        "confidence": sa.Column("confidence", sa.Float, nullable=True),
    }
    for name in NEW_PRODUCT_COLUMNS:
        if name not in existing:
            op.add_column("products", columns[name])
    op.create_index("idx_products_type_id", "products", ["type_id"], if_not_exists=True)
    op.create_index("idx_products_brand_id", "products", ["brand_id"], if_not_exists=True)
    op.create_index(
        "idx_products_attributes", "products", ["attributes"], postgresql_using="gin", if_not_exists=True
    )


def downgrade() -> None:
    op.drop_index("idx_products_attributes", table_name="products", if_exists=True)
    op.drop_index("idx_products_brand_id", table_name="products", if_exists=True)
    op.drop_index("idx_products_type_id", table_name="products", if_exists=True)
    for name in reversed(NEW_PRODUCT_COLUMNS):
        op.drop_column("products", name)
    op.drop_table("brands")
    op.drop_table("product_types")
