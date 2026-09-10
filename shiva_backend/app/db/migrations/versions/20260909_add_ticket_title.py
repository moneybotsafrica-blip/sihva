"""Add title field to tickets table for AI-generated ticket titles

Revision ID: 008
Revises: 007
Create Date: 2026-09-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '008'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add title column to tickets table
    op.add_column('tickets', sa.Column('title', sa.String(255), nullable=True))


def downgrade() -> None:
    # Remove title column from tickets table
    op.drop_column('tickets', 'title')
