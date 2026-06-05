"""add safety_alert to support_tickets

Revision ID: f3a9b2c7d1e5
Revises: c8cdf9913d44
Create Date: 2026-06-05 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f3a9b2c7d1e5'
down_revision: Union[str, Sequence[str], None] = 'c8cdf9913d44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('support_tickets',
        sa.Column('safety_alert', sa.Boolean(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('support_tickets', 'safety_alert')
