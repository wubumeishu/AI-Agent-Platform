"""Add the nurture_step_execution table (P1 - t_a2ce2cae, ADR-010 follow-up).

Revision ID: 025_nurture_step_execution
Revises: 024_channel_config
Create Date: 2026-09-14

Introduces the execution log for the NurturePlan Step Execution Engine:
one row per step-attempt (status, timing, error, content provenance, retry
bookkeeping). ``plan_id`` / ``step_id`` / ``run_id`` are plain indexed UUIDs
without foreign-key constraints - mirroring the workflow ExecutionLog
convention - so the table is independently migratable and tolerates a step
row being soft-deleted mid-run.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "025_nurture_step_execution"
down_revision: str = "024_channel_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nurture_step_execution",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("step_id", sa.Uuid(), nullable=True),
        sa.Column("step_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("content_item_id", sa.Uuid(), nullable=True),
        sa.Column("content_type", sa.String(length=50), nullable=True),
        sa.Column("content_strategy", sa.String(length=20), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_nse_plan", "nurture_step_execution", ["plan_id"], unique=False)
    op.create_index("idx_nse_account", "nurture_step_execution", ["account_id"], unique=False)
    op.create_index("idx_nse_step", "nurture_step_execution", ["step_id"], unique=False)
    op.create_index("idx_nse_run", "nurture_step_execution", ["run_id"], unique=False)
    op.create_index("idx_nse_plan_status", "nurture_step_execution", ["plan_id", "status"], unique=False)
    op.create_index("idx_nse_status", "nurture_step_execution", ["status"], unique=False)
    op.create_index("idx_nse_created", "nurture_step_execution", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_nse_created", table_name="nurture_step_execution")
    op.drop_index("idx_nse_status", table_name="nurture_step_execution")
    op.drop_index("idx_nse_plan_status", table_name="nurture_step_execution")
    op.drop_index("idx_nse_run", table_name="nurture_step_execution")
    op.drop_index("idx_nse_step", table_name="nurture_step_execution")
    op.drop_index("idx_nse_account", table_name="nurture_step_execution")
    op.drop_index("idx_nse_plan", table_name="nurture_step_execution")
    op.drop_table("nurture_step_execution")
