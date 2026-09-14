"""Memory and Context Window Tables

Revision ID: 011_memory_system
Revises: 010_intent_recognition
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '011_memory_system'
down_revision = '010_intent_recognition'
branch_labels = None
depends_on = None


def upgrade():
    # Memory table
    op.create_table(
        'memory',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('memory_type', sa.String(length=50), nullable=False, server_default='preference'),
        sa.Column('category', sa.String(length=50), nullable=False, server_default='general'),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False, server_default='conversation'),
        sa.Column('importance', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('metadata_', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Indexes for memory
    op.create_index('idx_memory_customer', 'memory', ['customer_id'])
    op.create_index('idx_memory_type', 'memory', ['memory_type'])
    op.create_index('idx_memory_category', 'memory', ['category'])
    op.create_index('idx_memory_created', 'memory', ['created_at'])
    op.create_index('idx_memory_tags', 'memory', ['tags'], postgresql_using='gin')

    # Memory Fragment table
    op.create_table(
        'memory_fragment',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('memory_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('fragment_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['memory_id'], ['memory.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Index for memory_fragment
    op.create_index('idx_fragment_memory', 'memory_fragment', ['memory_id'])

    # Conversation Summary table
    op.create_table(
        'conversation_summary',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('summary_type', sa.String(length=50), nullable=False, server_default='brief'),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('key_points', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('sentiment', sa.String(length=20), nullable=True),
        sa.Column('action_items', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversation.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Indexes for conversation_summary
    op.create_index('idx_summary_conversation', 'conversation_summary', ['conversation_id'])
    op.create_index('idx_summary_created', 'conversation_summary', ['created_at'])

    # Context Window table
    op.create_table(
        'context_window',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('current_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_tokens', sa.Integer(), nullable=False, server_default='4000'),
        sa.Column('compressed_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_compressed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('summary_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversation.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['summary_id'], ['conversation_summary.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('conversation_id'),
    )

    # Index for context_window
    op.create_index('idx_context_window_conversation', 'context_window', ['conversation_id'])


def downgrade():
    op.drop_index('idx_context_window_conversation', table_name='context_window')
    op.drop_table('context_window')
    op.drop_index('idx_summary_created', table_name='conversation_summary')
    op.drop_index('idx_summary_conversation', table_name='conversation_summary')
    op.drop_table('conversation_summary')
    op.drop_index('idx_fragment_memory', table_name='memory_fragment')
    op.drop_table('memory_fragment')
    op.drop_index('idx_memory_tags', table_name='memory')
    op.drop_index('idx_memory_created', table_name='memory')
    op.drop_index('idx_memory_category', table_name='memory')
    op.drop_index('idx_memory_type', table_name='memory')
    op.drop_index('idx_memory_customer', table_name='memory')
    op.drop_table('memory')
