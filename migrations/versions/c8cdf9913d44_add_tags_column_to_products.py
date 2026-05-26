"""add tags column to products

Revision ID: c8cdf9913d44
Revises: 
Create Date: 2026-05-27 01:31:14.055393

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'c8cdf9913d44'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products',
        sa.Column('tags', JSONB, nullable=True)
    )


def downgrade() -> None:
    op.drop_column('products', 'tags')