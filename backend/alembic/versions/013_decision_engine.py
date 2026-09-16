"""add decision_log table

Revision ID: 013_decision_engine
Revises: 012_message_management
Create Date: 2026-09-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '013_decision_engine'
down_revision = '012_message_management'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('decision_log',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('conversation_id', sa.Uuid(), nullable=True),
        sa.Column('customer_id', sa.Uuid(), nullable=True),
        sa.Column('persona_id', sa.Uuid(), nullable=True),
        sa.Column('intent_type', sa.String(length=100), nullable=False),
        sa.Column('intent_confidence', sa.Float(), nullable=True),
        sa.Column('strategy', sa.String(length=20), nullable=False),
        sa.Column('action_type', sa.String(length=100), nullable=False),
        sa.Column('response_text', sa.Text(), nullable=False),
        sa.Column('fallback_used', sa.Boolean(), nullable=False),
        sa.Column('fallback_reason', sa.Text(), nullable=True),
        sa.Column('quality_score', sa.Float(), nullable=True),
        sa.Column('quality_passed', sa.Boolean(), nullable=True),
        sa.Column('explanation', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('input_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('processing_time_ms', sa.Float(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversation.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['persona_id'], ['persona.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('idx_decision_log_conversation'), 'decision_log', ['conversation_id'], unique=False)
    op.create_index(op.f('idx_decision_log_strategy'), 'decision_log', ['strategy'], unique=False)
    op.create_index(op.f('idx_decision_log_created'), 'decision_log', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('idx_decision_log_created'), table_name='decision_log')
    op.drop_index(op.f('idx_decision_log_strategy'), table_name='decision_log')
    op.drop_index(op.f('idx_decision_log_conversation'), table_name='decision_log')
    op.drop_table('decision_log')
