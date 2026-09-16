"""NurturePlanItem soft-delete flag (P1 dual-track unification, t_4b55abe8).

Revision ID: 017_nurture_plan_item_is_deleted
Revises: 015_workflow_framework
Create Date: 2026-09-14

Architecture ruling (t_1814d03d Phase 5 review, Contract B):
``nurture_plan_item`` is the single source of truth for nurture plan steps;
the legacy ``nurture_plan.sequence_steps`` JSON column is retired. Reconciling
steps on ``update_nurture_plan`` soft-deletes surplus rows (by step_order
upsert, extras marked is_deleted), so this column is required.

Chained off 015_workflow_framework (same precedent as 014_execution_log):
016_scheduler_due_index and 016_workflow_task are parallel heads; this
revision adds no new tables and is logically independent of both.

Existing databases: the column is added with server_default 'false' so all
existing step rows remain valid (none are deleted).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "017_nurture_plan_item_is_deleted"
down_revision = "015_workflow_framework"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nurture_plan_item",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("nurture_plan_item", "is_deleted")
