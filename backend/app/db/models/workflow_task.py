"""Workflow Task - the unit of execution work consumed by the queue + worker engine (t_wf_004).

A ``WorkflowTask`` is one concrete piece of work that has been enqueued onto a
``WorkflowQueue`` and will be claimed and executed by a ``WorkflowWorker``.
It is the observable, state-tracked record that makes the execution engine
testable and auditable end-to-end:

    pending -> running -> success | failed | timeout
                        -> cancelled
    failed / timeout -> pending   (retry, while retry_count < max_retries)

Design notes
------------
- This module is intentionally **loosely coupled** from the sibling
  framework tables (``workflow_queue`` / ``workflow_worker`` /
  ``workflow`` / ``execution_log``). The ``queue_id`` / ``worker_id`` /
  ``workflow_id`` columns are plain indexed UUIDs WITHOUT foreign-key
  constraints -- the same decoupling choice already made for
  ``ExecutionLog`` in ``app.db.models.workflow``. They are logical
  references that can be promoted to real FKs later without reworking
  this table.
- State values mirror the platform task-state model (ARCHITECTURE.md #15)
  and reuse ``EXECUTION_STATES`` from ``app.db.models.workflow`` so the
  vocabulary stays a single source of truth.
- The engine that drives this entity lives in
  ``app.services.workflow_task`` (``QueueWorkerEngine``); the CRUD /
  queue-management API lives in ``app.routers.workflow_task``.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    Float,
    Boolean,
    DateTime,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB

from app.db.models.base import Base
from app.db.models.workflow import EXECUTION_STATES


# Task lifecycle states: canonical subset + terminal states.
TASK_STATES = EXECUTION_STATES  # ("pending","running","success","failed","cancelled","timeout")

# Convenience partition
TERMINAL_STATES = ("success", "failed", "cancelled", "timeout")
NON_TERMINAL_STATES = ("pending", "running")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowTask(Base):
    """Workflow Task (任务) - a single unit of execution work in a queue.

    Owned by ``t_wf_004``. Claimed/executed by a ``WorkflowWorker``;
    produced by any workflow / scheduler / manual enqueue.
    """

    __tablename__ = "workflow_task"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Logical references (no FK constraints - keep this module independently
    # migratable; promotable to real FKs once schema is stable).
    queue_id = Column(PGUUID(as_uuid=True), nullable=False, index=True)
    worker_id = Column(PGUUID(as_uuid=True), nullable=True, index=True)
    workflow_id = Column(PGUUID(as_uuid=True), nullable=True, index=True)

    # Identity
    name = Column(String(200), nullable=True)

    # Work payload (input parameters for the executor)
    payload = Column(JSONB, nullable=False, default=dict)

    # State machine
    status = Column(String(20), nullable=False, default="pending", index=True)  # TASK_STATES

    # Ordering / scheduling
    priority = Column(Integer, nullable=False, default=0)  # lower = earlier (FIFO within queue)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)  # deferred execution; NULL/now = ready

    # Retry bookkeeping
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=0)

    # Execution timeout (per-task; NULL falls back to queue.timeout_seconds)
    timeout_seconds = Column(Integer, nullable=True)

    # Timing
    claimed_at = Column(DateTime(timezone=True), nullable=True)  # when a worker picked it up
    started_at = Column(DateTime(timezone=True), nullable=True)   # when execution actually began
    finished_at = Column(DateTime(timezone=True), nullable=True)  # when it reached a terminal state
    duration_ms = Column(Float, nullable=True)

    # Outcome
    result = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    error_code = Column(String(100), nullable=True)

    # Free-form observability metadata (never store secrets here)
    metadata_ = Column(JSONB, nullable=False, default=dict)

    created_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
    is_deleted = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        # Hot dequeue path: oldest ready task in a queue.
        Index(
            "idx_task_queue_status_scheduled",
            "queue_id",
            "status",
            "scheduled_at",
        ),
        # Timeout sweep: long-running tasks.
        Index("idx_task_status_started", "status", "claimed_at"),
        # Retry eligibility.
        Index("idx_task_status_retry", "status", "retry_count"),
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    @property
    def is_retryable(self) -> bool:
        """A failed/timeout task may be retried until it hits ``max_retries``."""
        return (
            self.status in ("failed", "timeout")
            and self.retry_count < self.max_retries
        )

    def __repr__(self) -> str:
        return (
            f"<WorkflowTask(id={self.id}, queue={self.queue_id}, "
            f"status={self.status}, retries={self.retry_count})>"
        )
