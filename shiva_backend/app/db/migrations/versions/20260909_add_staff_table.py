"""Add staff table for staff management

Revision ID: 006
Revises: 005
Create Date: 2026-09-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'staff',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('role', sa.String(50), nullable=False, default='staff'),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('custom_data', sa.JSON(), nullable=True),
        sa.Column('external_id', sa.String(100), nullable=True),
        sa.Column('external_system', sa.String(50), nullable=True),
    )
    op.create_index('ix_staff_email', 'staff', ['email'])
    op.create_index('ix_staff_external_id', 'staff', ['external_id'])


def downgrade() -> None:
    op.drop_index('ix_staff_external_id', 'staff')
    op.drop_index('ix_staff_email', 'staff')
    op.drop_table('staff')
