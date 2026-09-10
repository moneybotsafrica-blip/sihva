"""Add dynamic routing tables for intelligent query classification

Revision ID: 007
Revises: 006
Create Date: 2026-09-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create routing_destinations table
    op.create_table(
        'routing_destinations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False, unique=True),
        sa.Column('display_name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('destination_type', sa.String(50), nullable=False),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('priority', sa.Integer(), nullable=False, default=100),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_routing_destinations_name', 'routing_destinations', ['name'])
    op.create_index('ix_routing_destinations_is_active', 'routing_destinations', ['is_active'])

    # Create routing_rules table
    op.create_table(
        'routing_rules',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('conditions', sa.JSON(), nullable=False),
        sa.Column('actions', sa.JSON(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, default=100),
        sa.Column('weight', sa.Float(), nullable=False, default=1.0),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('total_matches', sa.Integer(), nullable=False, default=0),
        sa.Column('successful_matches', sa.Integer(), nullable=False, default=0),
        sa.Column('last_matched_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.String(100), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, default=1),
        sa.Column('is_experiment', sa.Boolean(), nullable=False, default=False),
        sa.Column('parent_rule_id', sa.String(36), nullable=True),
    )
    op.create_index('ix_routing_rules_is_active', 'routing_rules', ['is_active'])
    op.create_index('ix_routing_rules_priority', 'routing_rules', ['priority'])
    op.create_index('ix_routing_rules_parent_rule_id', 'routing_rules', ['parent_rule_id'])

    # Create routing_metrics table
    op.create_table(
        'routing_metrics',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('ticket_id', sa.String(36), nullable=True),
        sa.Column('chat_session_id', sa.String(36), nullable=True),
        sa.Column('rule_id', sa.String(36), nullable=True),
        sa.Column('destination', sa.String(100), nullable=False),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('customer_id', sa.String(100), nullable=True),
        sa.Column('customer_data', sa.JSON(), nullable=True),
        sa.Column('resolution_time_seconds', sa.Integer(), nullable=True),
        sa.Column('first_response_time_seconds', sa.Integer(), nullable=True),
        sa.Column('customer_satisfaction', sa.Integer(), nullable=True),
        sa.Column('was_escalated', sa.Boolean(), nullable=False, default=False),
        sa.Column('escalation_count', sa.Integer(), nullable=False, default=0),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_routing_metrics_ticket_id', 'routing_metrics', ['ticket_id'])
    op.create_index('ix_routing_metrics_chat_session_id', 'routing_metrics', ['chat_session_id'])
    op.create_index('ix_routing_metrics_rule_id', 'routing_metrics', ['rule_id'])
    op.create_index('ix_routing_metrics_destination', 'routing_metrics', ['destination'])
    op.create_index('ix_routing_metrics_created_at', 'routing_metrics', ['created_at'])

    # Create routing_feedback table
    op.create_table(
        'routing_feedback',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('metric_id', sa.String(36), nullable=False),
        sa.Column('feedback_source', sa.String(50), nullable=False),
        sa.Column('feedback_type', sa.String(50), nullable=False),
        sa.Column('correct_destination', sa.String(100), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('rating', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['metric_id'], ['routing_metrics.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_routing_feedback_metric_id', 'routing_feedback', ['metric_id'])
    op.create_index('ix_routing_feedback_feedback_type', 'routing_feedback', ['feedback_type'])


def downgrade() -> None:
    op.drop_index('ix_routing_feedback_feedback_type', 'routing_feedback')
    op.drop_index('ix_routing_feedback_metric_id', 'routing_feedback')
    op.drop_table('routing_feedback')
    
    op.drop_index('ix_routing_metrics_created_at', 'routing_metrics')
    op.drop_index('ix_routing_metrics_destination', 'routing_metrics')
    op.drop_index('ix_routing_metrics_rule_id', 'routing_metrics')
    op.drop_index('ix_routing_metrics_chat_session_id', 'routing_metrics')
    op.drop_index('ix_routing_metrics_ticket_id', 'routing_metrics')
    op.drop_table('routing_metrics')
    
    op.drop_index('ix_routing_rules_parent_rule_id', 'routing_rules')
    op.drop_index('ix_routing_rules_priority', 'routing_rules')
    op.drop_index('ix_routing_rules_is_active', 'routing_rules')
    op.drop_table('routing_rules')
    
    op.drop_index('ix_routing_destinations_is_active', 'routing_destinations')
    op.drop_index('ix_routing_destinations_name', 'routing_destinations')
    op.drop_table('routing_destinations')
