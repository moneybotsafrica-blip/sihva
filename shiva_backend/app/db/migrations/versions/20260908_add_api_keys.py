"""Add API keys table

Revision ID: 20260908_add_api_keys
Revises: 20260908_add_staff_notes
Create Date: 2026-09-08 11:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = '20260908_add_api_keys'
down_revision: Union[str, None] = '20260908_add_staff_notes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create api_keys table
    op.create_table(
        'api_keys',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('key_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('scope', sa.String(20), nullable=False),  # Using string for SQLite compatibility
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.String(100), nullable=True),
    )
    
    # Create index on key_hash for fast lookups
    op.create_index('ix_api_keys_key_hash', 'api_keys', ['key_hash'])


def downgrade() -> None:
    op.drop_index('ix_api_keys_key_hash', table_name='api_keys')
    op.drop_table('api_keys')