"""Add AI resolution metadata fields for analytics

Revision ID: 20260909_add_ai_resolution_metadata
Revises: 008
Create Date: 2026-09-09 17:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260909_add_ai_resolution_metadata'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    # Add new columns to tickets table for AI resolution metadata
    op.add_column('tickets', sa.Column('ai_agent_type', sa.String(50), nullable=True))
    op.add_column('tickets', sa.Column('ai_kb_article_ids', sa.JSON(), nullable=True))
    op.add_column('tickets', sa.Column('ai_kb_similarity_score', sa.Float(), nullable=True))


def downgrade():
    # Remove the columns
    op.drop_column('tickets', 'ai_kb_similarity_score')
    op.drop_column('tickets', 'ai_kb_article_ids')
    op.drop_column('tickets', 'ai_agent_type')
