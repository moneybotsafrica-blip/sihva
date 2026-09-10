"""Add AI suggested resolution table for staff-only AI solutions

Revision ID: 20260910_add_ai_suggested_resolution
Revises: 20260910_add_ai_attempts_to_tickets
Create Date: 2026-09-10

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260910_add_ai_suggested_resolution'
down_revision = '20260910_add_ai_attempts_to_tickets'
branch_labels = None
depends_on = None


def upgrade():
    # Create ai_suggested_resolutions table
    op.create_table(
        'ai_suggested_resolutions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('ticket_id', sa.String(36), sa.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('suggested_solution', sa.Text(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('escalation_reason', sa.Text(), nullable=False),
        sa.Column('kb_article_ids', sa.JSON(), nullable=True),
        sa.Column('kb_similarity_score', sa.Float(), nullable=True),
        sa.Column('agent_type', sa.String(50), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),
        sa.Column('reviewed_by', sa.String(100), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_ai_suggested_resolutions_ticket_id', 'ai_suggested_resolutions', ['ticket_id'])
    op.create_index('ix_ai_suggested_resolutions_status', 'ai_suggested_resolutions', ['status'])


def downgrade():
    op.drop_index('ix_ai_suggested_resolutions_status', 'ai_suggested_resolutions')
    op.drop_index('ix_ai_suggested_resolutions_ticket_id', 'ai_suggested_resolutions')
    op.drop_table('ai_suggested_resolutions')
