"""Add staff_notes field to tickets table

Revision ID: 003
Revises: 002
Create Date: 2026-09-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tickets', sa.Column('staff_notes', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('tickets', 'staff_notes')
