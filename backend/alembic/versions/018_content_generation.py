"""merge Phase 5 heads + add content_generation table

Revision ID: 018_content_generation
Revises: 016_scheduler_due_index, 016_workflow_task, 017_nurture_plan_item_is_deleted
Create Date: 2026-09-14

This revision both merges the divergent Phase 5 heads into a single linear
chain (016_scheduler_due_index + 016_workflow_task + 017_nurture_plan_item_is
_deleted all descended from 015_workflow_framework) and introduces the
`content_generation` audit table for Phase 5 AI content generation + Nurture
automation. Merging is required so that subsequent migrations have exactly one
head to build on.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Multiple down_revisions = branch merge. This revision becomes the single
# newest head after it applies.
revision = '018_content_generation'
down_revision = ('016_scheduler_due_index', '016_workflow_task', '017_nurture_plan_item_is_deleted')
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Merge: ensure no lingering branch markers. The tuple down_revision above
    # tells Alembic this revision closes all three open heads.
    op.create_table('content_generation',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('account_id', sa.Uuid(), nullable=False),
        sa.Column('source', sa.String(length=40), nullable=False),
        sa.Column('content_type', sa.String(length=50), nullable=False),
        sa.Column('strategy', sa.String(length=20), nullable=False),
        sa.Column('fallback_used', sa.Boolean(), nullable=False),
        sa.Column('fallback_reason', sa.Text(), nullable=True),
        sa.Column('segment_id', sa.Uuid(), nullable=True),
        sa.Column('stage_code', sa.String(length=50), nullable=True),
        sa.Column('content_id', sa.Uuid(), nullable=True),
        sa.Column('nurture_plan_id', sa.Uuid(), nullable=True),
        sa.Column('plan_step_id', sa.Uuid(), nullable=True),
        sa.Column('quality_score', sa.Float(), nullable=True),
        sa.Column('quality_passed', sa.Boolean(), nullable=True),
        sa.Column('input_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('output_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('processing_time_ms', sa.Float(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['segment_id'], ['customer_segment.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['content_id'], ['content_item.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['nurture_plan_id'], ['nurture_plan.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['plan_step_id'], ['nurture_plan_item.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('idx_content_generation_account'), 'content_generation', ['account_id'], unique=False)
    op.create_index(op.f('idx_content_generation_source'), 'content_generation', ['source'], unique=False)
    op.create_index(op.f('idx_content_generation_strategy'), 'content_generation', ['strategy'], unique=False)
    op.create_index(op.f('idx_content_generation_content'), 'content_generation', ['content_id'], unique=False)
    op.create_index(op.f('idx_content_generation_plan'), 'content_generation', ['nurture_plan_id'], unique=False)
    op.create_index(op.f('idx_content_generation_created'), 'content_generation', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('idx_content_generation_created'), table_name='content_generation')
    op.drop_index(op.f('idx_content_generation_plan'), table_name='content_generation')
    op.drop_index(op.f('idx_content_generation_content'), table_name='content_generation')
    op.drop_index(op.f('idx_content_generation_strategy'), table_name='content_generation')
    op.drop_index(op.f('idx_content_generation_source'), table_name='content_generation')
    op.drop_index(op.f('idx_content_generation_account'), table_name='content_generation')
    op.drop_table('content_generation')
