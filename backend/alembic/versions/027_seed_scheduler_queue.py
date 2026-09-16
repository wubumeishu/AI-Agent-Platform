"""Seed the default scheduler queue + scheduler task baselines (reliability P1-R1).

Revision ID: 027_seed_scheduler_queue
Revises: 026_missing_orm_tables
Create Date: 2026-09-15

The scheduler engine's default dispatcher (QueueDispatcher) resolves its
target queue as: the scheduler's workflow-scoped queue, else the *named*
default queue ``workflow-scheduler`` (``scheduler_default_queue_name`` in
``app.config``). That default queue was never created anywhere:

  * no migration seeded it (verified: no ``workflow_queue`` INSERT in
    ``alembic/versions``), and
  * the dispatcher deliberately does NOT auto-create it (queue creation is a
    resource-layer operation, not a fire-path side effect).

So in a default install every timed fire resolved to ``no-queue`` and was
soft-dropped (the P1-R1 data-loss finding in REVIEW-WORKFLOW-RELIABILITY.md).
This revision seeds the default queue idempotently, following the
020/026 ``IF NOT EXISTS`` + ``ON CONFLICT DO NOTHING`` precedent:

  * a fresh DB and the legacy production DB both gain exactly one
    ``workflow_queue`` row named ``workflow-scheduler``;
  * re-running the migration is a no-op (the unique ``idx_queue_name``
    index backs the conflict target);
  * existing deployments that already created a queue under a different name
    are untouched (they can point ``SCHEDULER_DEFAULT_QUEUE`` at it).

The seeded queue also carries the P1-R2 recovery baseline:

  * ``timeout_seconds`` = 600 (10 minutes) — the sweep fallback for any task
    that does not set its own per-task timeout, so a stuck execution is
    observable instead of rotting in ``running`` forever;
  * ``max_retries`` is not a queue column (it is per-task); the dispatcher
    stamps ``max_retries=2`` onto scheduler-fired tasks by default (see
    ``scheduler_default_max_retries``), so a crashed execution is re-queued
    automatically by the retry path instead of becoming an unrecoverable
    orphan.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "027_seed_scheduler_queue"
down_revision = "026_missing_orm_tables"
branch_labels = None
depends_on = None


# Baseline values, mirrored in app.config (scheduler_default_timeout_seconds);
# keep the two in sync if either moves.
DEFAULT_QUEUE_NAME = "workflow-scheduler"
DEFAULT_QUEUE_TIMEOUT_SECONDS = 600


def upgrade() -> None:
    # The queue table itself is 020's concern; make it on a fresh DB that
    # somehow skipped 020 (defensive parity with the IF NOT EXISTS precedent)
    # and no-op everywhere else.
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
                  server_default="false"),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "idx_queue_name", "workflow_queue", ["name"],
        unique=True, if_not_exists=True,
    )

    # Idempotent seed: one default scheduler queue with the P1-R2 timeout
    # baseline. ON CONFLICT (name) keeps re-runs and already-seeded DBs a
    # no-op; the conflict target is the unique idx_queue_name from above.
    op.execute(
        f"""
        INSERT INTO workflow_queue
            (id, workflow_id, name, type, max_concurrency, retry_limit,
             timeout_seconds, status, created_at, updated_at, is_deleted)
        VALUES
            (gen_random_uuid(), NULL, '{DEFAULT_QUEUE_NAME}', 'fifo', 1, 0,
             {DEFAULT_QUEUE_TIMEOUT_SECONDS}, 'idle', NOW(), NOW(), false)
        ON CONFLICT (name) DO UPDATE
            SET timeout_seconds = COALESCE(workflow_queue.timeout_seconds,
                {DEFAULT_QUEUE_TIMEOUT_SECONDS})
            WHERE workflow_queue.timeout_seconds IS NULL
        """
    )


def downgrade() -> None:
    # Remove only the seed row (and its baseline timeout). The table itself
    # belongs to 020_workflow_runtime_tables and is never dropped here.
    op.execute(
        "DELETE FROM workflow_queue WHERE name = "
        f"'{DEFAULT_QUEUE_NAME}' AND workflow_id IS NULL"
    )
