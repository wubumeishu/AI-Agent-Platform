"""Migration to add message management features

Revision ID: 012_message_management
Revises: 011_memory_system
Create Date: 2026-09-14

Adds:
- parent_id column to message table (for threading)
- edit_count column to message table (max 3 edits)
- message_count and last_message_at columns to conversation table
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '012_message_management'
down_revision = '011_memory_system'
branch_labels = None
depends_on = None


def upgrade():
    # Add columns to conversation table
    op.add_column('conversation', sa.Column('message_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('conversation', sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True))
    
    # Create index for last_message_at
    op.create_index('idx_conversation_last_message', 'conversation', ['last_message_at'])
    
    # Add columns to message table
    op.add_column('message', sa.Column('parent_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('message', sa.Column('edit_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('message', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))
    
    # Create foreign key for parent_id
    op.create_foreign_key('fk_message_parent', 'message', 'message', ['parent_id'], ['id'], ondelete='SET NULL')
    
    # Create index for parent_id
    op.create_index('idx_message_parent', 'message', ['parent_id'])


def downgrade():
    # Drop indexes
    op.drop_index('idx_message_parent', table_name='message')
    op.drop_index('idx_conversation_last_message', table_name='conversation')
    
    # Drop foreign key
    op.drop_constraint('fk_message_parent', 'message', type_='foreignkey')
    
    # Drop columns
    op.drop_column('message', 'updated_at')
    op.drop_column('message', 'edit_count')
    op.drop_column('message', 'parent_id')
    op.drop_column('conversation', 'last_message_at')
    op.drop_column('conversation', 'message_count')
