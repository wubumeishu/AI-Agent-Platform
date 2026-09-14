"""add intents and intent_action_logs tables

Revision ID: 008_intent
Revises: 007_prompt_template
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '008_intent'
down_revision = '007_prompt_template'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create intents table
    op.create_table('intents',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('conversation_id', sa.Uuid(), nullable=False),        sa.Column('intent_type', sa.String(length=100), nullable=False),
        sa.Column('intent_name', sa.String(length=200), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('raw_input', sa.Text(), nullable=False),
        sa.Column('extracted_entities', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('matched_action', sa.String(length=200), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversation.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_intents_intent_type'), 'intents', ['intent_type'], unique=False)
    op.create_index(op.f('ix_intents_conversation_id'), 'intents', ['conversation_id'], unique=False)

    # Create intent_action_logs table
    op.create_table('intent_action_logs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('intent_id', sa.Uuid(), nullable=True),
        sa.Column('action_type', sa.String(length=100), nullable=False),
        sa.Column('action_target', sa.String(length=500), nullable=True),
        sa.Column('action_params', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('executed', sa.Boolean(), nullable=True),
        sa.Column('execution_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['intent_id'], ['intents.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_intent_action_logs_intent_id'), 'intent_action_logs', ['intent_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_intent_action_logs_intent_id'), table_name='intent_action_logs')
    op.drop_table('intent_action_logs')
    op.drop_index(op.f('ix_intents_conversation_id'), table_name='intents')
    op.drop_index(op.f('ix_intents_intent_type'), table_name='intents')
    op.drop_table('intents')
