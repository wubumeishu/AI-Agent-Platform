"""Conversation and Message Tables

Revision ID: 009_conversation_message
Revises: 008_channel_connection
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '009_conversation_message'
down_revision = '008_channel_connection'
branch_labels = None
depends_on = None


def upgrade():
    # Conversation table
    op.create_table(
        'conversation',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('channel', sa.String(length=50), nullable=False, server_default='web'),
        sa.Column('subject', sa.String(length=200), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('sentiment', sa.String(length=20), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('metadata_', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Indexes for conversation
    op.create_index('idx_conversation_customer', 'conversation', ['customer_id'])
    op.create_index('idx_conversation_status', 'conversation', ['status'])
    op.create_index('idx_conversation_created', 'conversation', ['created_at'])

    # Message table
    op.create_table(
        'message',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('metadata_', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversation.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Indexes for message
    op.create_index('idx_message_conversation', 'message', ['conversation_id'])
    op.create_index('idx_message_created', 'message', ['created_at'])
    op.create_index('idx_message_role', 'message', ['role'])


def downgrade():
    op.drop_index('idx_message_role', table_name='message')
    op.drop_index('idx_message_created', table_name='message')
    op.drop_index('idx_message_conversation', table_name='message')
    op.drop_table('message')
    op.drop_index('idx_conversation_created', table_name='conversation')
    op.drop_index('idx_conversation_status', table_name='conversation')
    op.drop_index('idx_conversation_customer', table_name='conversation')
    op.drop_table('conversation')
