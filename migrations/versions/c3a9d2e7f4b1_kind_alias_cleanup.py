"""catalog data: bare "table" and "desk" are not laptop-table words (p03)

Revision ID: c3a9d2e7f4b1
Revises: b5e1f0a3c2d4
Create Date: 2026-11-23 20:30:00.000000

"table" on its own resolved to the laptop-stand kind "laptop table", so a shopper asking for a table
(furniture we don't sell) was shown laptop tables. The kind keeps its specific aliases ("lap desk",
"bed table"); data/catalog/product_types.yaml says the same.
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3a9d2e7f4b1"
down_revision: Union[str, Sequence[str], None] = "b5e1f0a3c2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = ["table", "desk", "lap desk", "bed table"]
NEW = ["lap desk", "bed table"]


def _set(aliases: list) -> None:
    bind = op.get_bind()
    row = bind.execute(sa.text("SELECT id, attribute_schema FROM product_types WHERE name = 'laptop stand'")).first()
    if row is None:
        return
    schema = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
    values = schema.get("kind", {}).get("values", {})
    if "laptop table" not in values:
        return
    values["laptop table"] = aliases
    bind.execute(
        sa.text("UPDATE product_types SET attribute_schema = :s WHERE id = :id"),
        {"s": json.dumps(schema), "id": row[0]},
    )


def upgrade() -> None:
    _set(NEW)


def downgrade() -> None:
    _set(OLD)
