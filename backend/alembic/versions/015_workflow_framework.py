"""Add the full Workflow subsystem tables (Phase 4 / t_wf_001).

Revision ID: 015_workflow_framework
Revises: 014_execution_log
Create Date: 2026-09-14

Creates the Workflow configuration + runtime schema in one coherent
migration so the whole subsystem is Alembic-migratable:

Core configuration model (classes defined in app.db.models.workflow,
owned jointly with the execution-log work):
- workflow
- workflow_trigger
- workflow_condition
- workflow_action

Runtime entities (app.db.models.workflow_runtime, owned by t_wf_001):
- workflow_delay
- workflow_branch
- workflow_scheduler
- workflow_queue
- workflow_worker

``execution_log`` was already created by 014_execution_log and is NOT
touched here.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "015_workflow_framework"
down_revision = "014_execution_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- core: workflow ----
    op.create_table(
        "workflow",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("workflow_type", sa.String(length=20), nullable=False,
                  server_default="auto"),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="draft"),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        sa.Column("execution_policy", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_workflow_status_name", "workflow", ["status", "name"],
                    unique=False)
    op.create_index("idx_workflow_type", "workflow", ["workflow_type"],
                    unique=False)

    # ---- core: workflow_trigger ----
    op.create_table(
        "workflow_trigger",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("trigger_type", sa.String(length=20), nullable=False,
                  server_default="manual"),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"],
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_trigger_workflow", "workflow_trigger",
                    ["workflow_id"], unique=False)

    # ---- core: workflow_condition ----
    op.create_table(
        "workflow_condition",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trigger_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("expression", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        sa.Column("logic", sa.String(length=5), nullable=False,
                  server_default="and"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["trigger_id"], ["workflow_trigger.id"],
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_condition_trigger", "workflow_condition",
                    ["trigger_id"], unique=False)

    # ---- core: workflow_action ----
    op.create_table(
        "workflow_action",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("condition_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("action_type", sa.String(length=30), nullable=False,
                  server_default="message"),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default="{}"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["condition_id"], ["workflow_condition.id"],
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_action_condition", "workflow_action",
                    ["condition_id"], unique=False)
    op.create_index("idx_action_type", "workflow_action", ["action_type"],
                    unique=False)

    # ---- runtime: workflow_delay ----
    op.create_table(
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
                  server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["action_id"], ["workflow_action.id"],
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_delay_workflow", "workflow_delay", ["workflow_id"],
                    unique=False)

    # ---- runtime: workflow_branch ----
    op.create_table(
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
                  server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"],
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_branch_workflow", "workflow_branch", ["workflow_id"],
                    unique=False)

    # ---- runtime: workflow_scheduler ----
    op.create_table(
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
                  server_default=sa.text("true")),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trigger_id"], ["workflow_trigger.id"],
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_scheduler_workflow", "workflow_scheduler",
                    ["workflow_id"], unique=False)
    op.create_index(
        "idx_scheduler_enabled", "workflow_scheduler", ["enabled"],
        unique=False, postgresql_where=sa.text("is_deleted = false"),
    )

    # ---- runtime: workflow_queue ----
    op.create_table(
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
                  server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"],
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_queue_workflow", "workflow_queue", ["workflow_id"],
                    unique=False)
    op.create_index(
        "idx_queue_status", "workflow_queue", ["status"],
        unique=False, postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index("idx_queue_name", "workflow_queue", ["name"],
                    unique=True)

    # ---- runtime: workflow_worker ----
    op.create_table(
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
                  server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["queue_id"], ["workflow_queue.id"],
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_worker_queue", "workflow_worker", ["queue_id"],
                    unique=False)
    op.create_index(
        "idx_worker_status", "workflow_worker", ["status"],
        unique=False, postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index("idx_worker_status", table_name="workflow_worker")
    op.drop_index("idx_worker_queue", table_name="workflow_worker")
    op.drop_table("workflow_worker")

    op.drop_index("idx_queue_name", table_name="workflow_queue")
    op.drop_index("idx_queue_status", table_name="workflow_queue")
    op.drop_index("idx_queue_workflow", table_name="workflow_queue")
    op.drop_table("workflow_queue")

    op.drop_index("idx_scheduler_enabled", table_name="workflow_scheduler")
    op.drop_index("idx_scheduler_workflow", table_name="workflow_scheduler")
    op.drop_table("workflow_scheduler")

    op.drop_index("idx_branch_workflow", table_name="workflow_branch")
    op.drop_table("workflow_branch")

    op.drop_index("idx_delay_workflow", table_name="workflow_delay")
    op.drop_table("workflow_delay")

    op.drop_index("idx_action_type", table_name="workflow_action")
    op.drop_index("idx_action_condition", table_name="workflow_action")
    op.drop_table("workflow_action")

    op.drop_index("idx_condition_trigger", table_name="workflow_condition")
    op.drop_table("workflow_condition")

    op.drop_index("idx_trigger_workflow", table_name="workflow_trigger")
    op.drop_table("workflow_trigger")

    op.drop_index("idx_workflow_type", table_name="workflow")
    op.drop_index("idx_workflow_status_name", table_name="workflow")
    op.drop_table("workflow")
