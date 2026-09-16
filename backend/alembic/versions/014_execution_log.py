"""add execution_log table

Revision ID: 014_execution_log
Revises: 013_decision_engine
Create Date: 2026-09-14

Adds:
- execution_log table (workflow execution audit/observability record)

Reference columns (workflow_id/queue_id/worker_id/task_id) are plain indexed
UUIDs WITHOUT foreign-key constraints: the referenced tables belong to t_wf_001
/ t_wf_004 which are not yet in the schema. They are logical references that can
be promoted to real FKs once those tables land.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '014_execution_log'
down_revision = '013_decision_engine'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'execution_log',
        sa.Column('id', sa.Uuid(), nullable=False),
        # logical references (no FK constraints - sibling tables not yet in schema)
        sa.Column('workflow_id', sa.Uuid(), nullable=True),
        sa.Column('queue_id', sa.Uuid(), nullable=True),
        sa.Column('worker_id', sa.Uuid(), nullable=True),
        sa.Column('task_id', sa.Uuid(), nullable=True),
        # execution identity
        sa.Column('execution_type', sa.String(length=50), nullable=False,
                  server_default='task'),
        sa.Column('trigger_type', sa.String(length=20), nullable=False,
                  server_default='manual'),
        sa.Column('status', sa.String(length=20), nullable=False,
                  server_default='pending'),
        # timing
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Float(), nullable=True),
        # input / output
        sa.Column('input_params', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default='{}'),
        sa.Column('output_result', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True),
        # error capture
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_code', sa.String(length=100), nullable=True),
        # retry bookkeeping
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        # observability metadata (never store secrets)
        sa.Column('metadata_', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default='{}'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False,
                  server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    # indexes
    op.create_index('idx_execution_log_status', 'execution_log', ['status'], unique=False)
    op.create_index('idx_execution_log_workflow', 'execution_log', ['workflow_id'], unique=False)
    op.create_index('idx_execution_log_queue', 'execution_log', ['queue_id'], unique=False)
    op.create_index('idx_execution_log_worker', 'execution_log', ['worker_id'], unique=False)
    op.create_index('idx_execution_log_task', 'execution_log', ['task_id'], unique=False)
    op.create_index('idx_execution_log_created', 'execution_log', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_execution_log_created', table_name='execution_log')
    op.drop_index('idx_execution_log_task', table_name='execution_log')
    op.drop_index('idx_execution_log_worker', table_name='execution_log')
    op.drop_index('idx_execution_log_queue', table_name='execution_log')
    op.drop_index('idx_execution_log_workflow', table_name='execution_log')
    op.drop_index('idx_execution_log_status', table_name='execution_log')
    op.drop_table('execution_log')
