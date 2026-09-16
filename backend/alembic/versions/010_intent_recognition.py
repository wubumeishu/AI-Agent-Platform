"""Intent Recognition Tables

Revision ID: 010_intent_recognition
Revises: 009_conversation_message
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '010_intent_recognition'
down_revision = '009_conversation_message'
branch_labels = None
depends_on = None


def upgrade():
    # Intent table
    op.create_table(
        'intent',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('intent_type', sa.String(length=50), nullable=False),
        sa.Column('intent_name', sa.String(length=100), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('raw_input', sa.Text(), nullable=False),
        sa.Column('extracted_entities', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('matched_action', sa.String(length=100), nullable=True),
        sa.Column('metadata_', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversation.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Indexes
    op.create_index('idx_intent_conversation', 'intent', ['conversation_id'])
    op.create_index('idx_intent_type', 'intent', ['intent_type'])
    op.create_index('idx_intent_created', 'intent', ['created_at'])

    # Intent action log table
    op.create_table(
        'intent_action_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('intent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('action_type', sa.String(length=50), nullable=False),
        sa.Column('action_target', sa.String(length=200), nullable=True),
        sa.Column('action_params', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('executed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('execution_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['intent_id'], ['intent.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Indexes for action log
    op.create_index('idx_action_intent', 'intent_action_log', ['intent_id'])
    op.create_index('idx_action_type', 'intent_action_log', ['action_type'])


def downgrade():
    op.drop_index('idx_action_type', table_name='intent_action_log')
    op.drop_index('idx_action_intent', table_name='intent_action_log')
    op.drop_table('intent_action_log')

    op.drop_index('idx_intent_created', table_name='intent')
    op.drop_index('idx_intent_type', table_name='intent')
    op.drop_index('idx_intent_conversation', table_name='intent')
    op.drop_table('intent')
