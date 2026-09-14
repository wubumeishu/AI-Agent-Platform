"""add workflow_task table - queue + worker execution engine unit of work (t_wf_004).

Revision ID: 016_workflow_task
Revises: 015_workflow_framework
Create Date: 2026-09-14

Adds:
- workflow_task table (a single unit of execution work in a WorkflowQueue,
  claimed and executed by a WorkflowWorker). This is the observable,
  state-tracked record of the execution engine:

      pending -> running -> success | failed | timeout
                            -> cancelled
      failed / timeout -> pending   (retry, while retry_count < max_retries)

Reference columns (queue_id / worker_id / workflow_id) are plain indexed
UUIDs WITHOUT foreign-key constraints: they are logical references to the
``workflow_queue`` / ``workflow_worker`` / ``workflow`` tables introduced by
t_wf_001. Keeping them un-constrained (exactly as ExecutionLog did) makes
this migration independently applicable and testable without blocking on the
sibling tables landing. They can be promoted to real FKs in a later wave.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "016_workflow_task"
down_revision = "015_workflow_framework"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_task",
        sa.Column("id", sa.Uuid(), nullable=False),
        # logical references (no FK constraints - sibling tables land separately)
        sa.Column("queue_id", sa.Uuid(), nullable=False),
        sa.Column("worker_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_id", sa.Uuid(), nullable=True),
        # identity + payload
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        # state machine
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="pending"),
        # ordering / scheduling
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        # retry bookkeeping
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="0"),
        # execution timeout (NULL -> fall back to queue.timeout_seconds)
        sa.Column("timeout_seconds", sa.Integer(), nullable=True),
        # timing
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        # outcome
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        # observability metadata (never store secrets here)
        sa.Column("metadata_", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.PrimaryKeyConstraint("id"),
    )
    # indexes
    # hot dequeue path: oldest ready task in a queue
    op.create_index(
        "idx_task_queue_status_scheduled",
        "workflow_task", ["queue_id", "status", "scheduled_at"],
        unique=False,
    )
    # timeout sweep
    op.create_index("idx_task_status_started", "workflow_task",
                    ["status", "claimed_at"], unique=False)
    # retry eligibility
    op.create_index("idx_task_status_retry", "workflow_task",
                    ["status", "retry_count"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_task_status_retry", table_name="workflow_task")
    op.drop_index("idx_task_status_started", table_name="workflow_task")
    op.drop_index("idx_task_queue_status_scheduled", table_name="workflow_task")
    op.drop_table("workflow_task")
