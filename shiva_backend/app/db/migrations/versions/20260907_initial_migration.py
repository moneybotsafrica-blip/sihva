"""Initial migration

Revision ID: 001
Revises: 
Create Date: 2026-09-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create tickets table
    op.create_table(
        'tickets',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('customer_id', sa.String(100), nullable=False, index=True),
        sa.Column('status', sa.Enum('OPEN', 'IN_PROGRESS', 'PENDING_STAFF', 'PENDING_CUSTOMER', 'RESOLVED_AUTO', 'CLOSED', name='ticketstatus'), nullable=False),
        sa.Column('path', sa.Enum('support', 'bug', name='ticketpath'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('assigned_staff_id', sa.String(100), nullable=True, index=True),
        sa.Column('ai_resolution_feedback', sa.Enum('helpful', 'not_helpful', 'partially_helpful', 'needs_human', name='airesolutionfeedback'), nullable=True),
        sa.Column('ai_resolution_feedback_at', sa.DateTime(), nullable=True),
        sa.Column('ai_resolution_feedback_comment', sa.Text(), nullable=True),
        sa.Column('ai_resolution_confidence', sa.Float(), nullable=True),
    )
    
    # Create partial unique index for one open ticket per customer
    op.create_index(
        'idx_one_open_ticket_per_customer',
        'tickets',
        ['customer_id'],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('CLOSED', 'RESOLVED_AUTO')")
    )
    
    # Create ticket_messages table
    op.create_table(
        'ticket_messages',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('ticket_id', sa.String(36), sa.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('sender', sa.Enum('customer', 'support_ai', 'code_ai', 'staff', 'system', name='messagesender'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('attachments', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    
    # Create fix_recommendations table
    op.create_table(
        'fix_recommendations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('ticket_id', sa.String(36), sa.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('diff', sa.Text(), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('status', sa.Enum('PENDING', 'APPROVED', 'REJECTED', 'NEEDS_INFO', name='fixrecommendationstatus'), nullable=False),
        sa.Column('reviewed_by', sa.String(100), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('fix_recommendations')
    op.drop_table('ticket_messages')
    op.drop_index('idx_one_open_ticket_per_customer', table_name='tickets')
    op.drop_table('tickets')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS ticketstatus')
    op.execute('DROP TYPE IF EXISTS ticketpath')
    op.execute('DROP TYPE IF EXISTS messagesender')
    op.execute('DROP TYPE IF EXISTS fixrecommendationstatus')
    op.execute('DROP TYPE IF EXISTS airesolutionfeedback')
