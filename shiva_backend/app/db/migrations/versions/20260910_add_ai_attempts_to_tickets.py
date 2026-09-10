"""Add ai_attempts column to tickets table for AI turn cap

Revision ID: 20260910_add_ai_attempts_to_tickets
Revises: 20260909_add_ai_resolution_metadata
Create Date: 2026-09-10

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260910_add_ai_attempts_to_tickets'
down_revision = '20260909_add_ai_resolution_metadata'
branch_labels = None
depends_on = None


def upgrade():
    # Add ai_attempts column to tickets table
    op.add_column('tickets', sa.Column('ai_attempts', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    # Remove ai_attempts column
    op.drop_column('tickets', 'ai_attempts')
