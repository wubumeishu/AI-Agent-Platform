"""Create the missing Workflow runtime tables (idempotent).

Revision ID: 020_workflow_runtime_tables
Revises: 019_linearize_heads
Create Date: 2026-09-14

The production database was built out-of-band with ``Base.metadata.create_all``
and has never been Alembic-managed (no ``alembic_version`` row). It already
contains the four Workflow CONFIG tables created by 015
(``workflow``, ``workflow_trigger``, ``workflow_condition``, ``workflow_action``)
but is MISSING the following seven runtime/observability tables that
``app.db.models`` requires:

    execution_log          (from 014_execution_log)
    workflow_delay         (from 015_workflow_framework)
    workflow_branch        (from 015_workflow_framework)
    workflow_scheduler     (from 015_workflow_framework)
    workflow_queue         (from 015_workflow_framework)
    workflow_worker        (from 015_workflow_framework)
    workflow_task          (from 016_workflow_task)

Any queue / worker / scheduler / task / execution-log operation on the default
database would therefore 500 with ``relation does not exist``.

This migration recreates exactly those seven tables (plus the
``idx_scheduler_due`` partial index from 016_scheduler_due_index) using
``IF NOT EXISTS`` so it is:

  * safe on the legacy production DB (the four config tables are NOT touched),
  * safe on a fresh database already advanced through 015/016 (no-op), and
  * re-runnable.

DDL is transcribed verbatim from 014/015/016 so the schema matches the ORM
models exactly. Column reference UUIDs that 014/016 deliberately left
UN-constrained (``workflow_task.queue_id/worker_id/workflow_id``,
``execution_log.*_id``) are kept that way here too, so this migration stays
independently applicable and does not impose new FK constraints that could
reject existing rows.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "020_workflow_runtime_tables"
down_revision = "019_linearize_heads"
branch_labels = None
depends_on = None


def _create_table(*args, **kwargs):
    """op.create_table with idempotency forced on."""
    kwargs["if_not_exists"] = True
    op.create_table(*args, **kwargs)


def _create_index(*args, **kwargs):
    kwargs["if_not_exists"] = True
    op.create_index(*args, **kwargs)


def upgrade() -> None:
    # ---- execution_log (from 014_execution_log) ----
    _create_table(
        "execution_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        # logical references (no FK constraints - keep 014 behaviour)
        sa.Column("workflow_id", sa.Uuid(), nullable=True),
        sa.Column("queue_id", sa.Uuid(), nullable=True),
        sa.Column("worker_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("execution_type", sa.String(length=50), nullable=False,
                  server_default="task"),
        sa.Column("trigger_type", sa.String(length=20), nullable=False,
                  server_default="manual"),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("input_params", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        sa.Column("output_result", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("metadata_", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("idx_execution_log_status", "execution_log", ["status"],
                  unique=False)
    _create_index("idx_execution_log_workflow", "execution_log", ["workflow_id"],
                  unique=False)
    _create_index("idx_execution_log_queue", "execution_log", ["queue_id"],
                  unique=False)
    _create_index("idx_execution_log_worker", "execution_log", ["worker_id"],
                  unique=False)
    _create_index("idx_execution_log_task", "execution_log", ["task_id"],
                  unique=False)
    _create_index("idx_execution_log_created", "execution_log", ["created_at"],
                  unique=False)

    # ---- workflow_delay (from 015_workflow_framework) ----
    _create_table(
        "workflow_delay",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.Uuid(), nullable=True),
        sa.Column("delay_amount", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("unit", sa.String(length=20), nullable=False,
                  server_default="seconds"),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["action_id"], ["workflow_action.id"],
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("idx_delay_workflow", "workflow_delay", ["workflow_id"],
                  unique=False)

    # ---- workflow_branch (from 015_workflow_framework) ----
    _create_table(
        "workflow_branch",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("rule", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"],
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("idx_branch_workflow", "workflow_branch", ["workflow_id"],
                  unique=False)

    # ---- workflow_scheduler (from 015_workflow_framework) ----
    _create_table(
        "workflow_scheduler",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=True),
        sa.Column("trigger_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("schedule_type", sa.String(length=20), nullable=False,
                  server_default="interval"),
        sa.Column("cron_expression", sa.String(length=100), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("timezone", sa.String(length=50), nullable=False,
                  server_default="UTC"),
        sa.Column("enabled", sa.Boolean(), nullable=False,
                  server_default="true"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trigger_id"], ["workflow_trigger.id"],
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("idx_scheduler_workflow", "workflow_scheduler", ["workflow_id"],
                  unique=False)
    _create_index("idx_scheduler_enabled", "workflow_scheduler", ["enabled"],
                  unique=False, postgresql_where=sa.text("is_deleted = false"))
    # partial index from 016_scheduler_due_index
    _create_index("idx_scheduler_due", "workflow_scheduler", ["next_run_at"],
                  unique=False,
                  postgresql_where=sa.text("enabled = true AND is_deleted = false"))

    # ---- workflow_queue (from 015_workflow_framework) ----
    _create_table(
        "workflow_queue",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False,
                  server_default="fifo"),
        sa.Column("max_concurrency", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.Column("retry_limit", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="idle"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"],
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("idx_queue_workflow", "workflow_queue", ["workflow_id"],
                  unique=False)
    _create_index("idx_queue_status", "workflow_queue", ["status"],
                  unique=False, postgresql_where=sa.text("is_deleted = false"))
    _create_index("idx_queue_name", "workflow_queue", ["name"], unique=True)

    # ---- workflow_worker (from 015_workflow_framework) ----
    # FK target workflow_queue must exist first -> created above.
    _create_table(
        "workflow_worker",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("queue_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="idle"),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.ForeignKeyConstraint(["queue_id"], ["workflow_queue.id"],
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index("idx_worker_queue", "workflow_worker", ["queue_id"],
                  unique=False)
    _create_index("idx_worker_status", "workflow_worker", ["status"],
                  unique=False, postgresql_where=sa.text("is_deleted = false"))

    # ---- workflow_task (from 016_workflow_task) ----
    _create_table(
        "workflow_task",
        sa.Column("id", sa.Uuid(), nullable=False),
        # logical references (no FK constraints - keep 016 behaviour)
        sa.Column("queue_id", sa.Uuid(), nullable=False),
        sa.Column("worker_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="pending"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("metadata_", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index(
        "idx_task_queue_status_scheduled",
        "workflow_task", ["queue_id", "status", "scheduled_at"],
        unique=False,
    )
    _create_index("idx_task_status_started", "workflow_task",
                  ["status", "claimed_at"], unique=False)
    _create_index("idx_task_status_retry", "workflow_task",
                  ["status", "retry_count"], unique=False)


def downgrade() -> None:
    # Reverse dependency order. Use if_exists=True so this is safe against
    # tables that were never created by this revision.
    for idx in ("idx_task_status_retry", "idx_task_status_started",
                "idx_task_queue_status_scheduled"):
        op.drop_index(idx, table_name="workflow_task", if_exists=True)
    op.drop_table("workflow_task", if_exists=True)

    for idx in ("idx_worker_status", "idx_worker_queue"):
        op.drop_index(idx, table_name="workflow_worker", if_exists=True)
    op.drop_table("workflow_worker", if_exists=True)

    for idx in ("idx_queue_name", "idx_queue_status", "idx_queue_workflow"):
        op.drop_index(idx, table_name="workflow_queue", if_exists=True)
    op.drop_table("workflow_queue", if_exists=True)

    for idx in ("idx_scheduler_due", "idx_scheduler_enabled",
                "idx_scheduler_workflow"):
        op.drop_index(idx, table_name="workflow_scheduler", if_exists=True)
    op.drop_table("workflow_scheduler", if_exists=True)

    op.drop_index("idx_branch_workflow", table_name="workflow_branch",
                  if_exists=True)
    op.drop_table("workflow_branch", if_exists=True)

    op.drop_index("idx_delay_workflow", table_name="workflow_delay",
                  if_exists=True)
    op.drop_table("workflow_delay", if_exists=True)

    for idx in ("idx_execution_log_created", "idx_execution_log_task",
                "idx_execution_log_worker", "idx_execution_log_queue",
                "idx_execution_log_workflow", "idx_execution_log_status"):
        op.drop_index(idx, table_name="execution_log", if_exists=True)
    op.drop_table("execution_log", if_exists=True)
