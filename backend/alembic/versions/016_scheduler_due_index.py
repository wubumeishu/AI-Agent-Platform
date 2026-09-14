"""Scheduler performance index (Phase 4 / t_wf_003 - scheduling engine).

Revision ID: 016_scheduler_due_index
Revises: 015_workflow_framework
Create Date: 2026-09-14

The ``workflow_scheduler`` table was created by 015_workflow_framework
(t_wf_001 scaffold). This card (t_wf_003) adds **no new tables** - it
reuses the scaffold entity. It only adds a partial index that makes the
scheduling engine's due-detection scan fast:

    idx_scheduler_due (next_run_at) WHERE enabled AND NOT is_deleted

The engine's load_schedules / tick loop selects enabled, not-deleted
schedulers and orders by next fire; this index turns that into an index
scan instead of a full table filter.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "016_scheduler_due_index"
down_revision = "015_workflow_framework"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_scheduler_due",
        "workflow_scheduler",
        ["next_run_at"],
        unique=False,
        postgresql_where=sa.text(
            "enabled = true AND is_deleted = false"
        ),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("idx_scheduler_due", table_name="workflow_scheduler", if_exists=True)
