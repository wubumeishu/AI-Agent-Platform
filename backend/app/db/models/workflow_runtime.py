"""Workflow runtime entities (Phase 4 / t_wf_001 - schema & scaffold layer).

The *core* configuration model (Workflow / WorkflowTrigger / WorkflowCondition
/ WorkflowAction) and the observability record (ExecutionLog) live in
``app.db.models.workflow``. This module owns the complementary **runtime**
entities that power execution, scheduling and worker management:

    WorkflowDelay     -- wait/pause step (delay N units before continuing)
    WorkflowBranch    -- a routing point that selects an execution path
    WorkflowScheduler -- time-based schedule (cron expression or fixed interval)
    WorkflowQueue     -- task queue holding units of execution work
    WorkflowWorker    -- an executor that consumes from a queue

Design notes
------------
- All entities are soft-deletable (``is_deleted``) and carry
  ``created_at`` / ``updated_at`` timestamps, matching the resource-layer
  conventions (Platform, Account, ...).
- ``config`` / ``spec`` / ``params`` use JSONB so the framework can evolve
  without schema churn. This card is a *scaffold*: it ships the tables, the
  migration, and CRUD. The execution engine, cron parsing and queue
  dispatch are later waves (t_wf_003 / t_wf_004).
- Relationships to the core model classes are **unidirectional** so this
  module stays additive and does not edit the sibling ``workflow`` module.
- ``WorkflowQueue`` / ``WorkflowWorker`` are the real tables that
  ``ExecutionLog``'s ``queue_id`` / ``worker_id`` logical refs point at
  (t_wf_005 intentionally left those as plain indexed UUIDs).
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import relationship

from app.db.models.base import Base


# ===== Allowed value sets (validation + docs) =====
DELAY_UNITS = ("seconds", "minutes", "hours", "days")
SCHEDULE_TYPES = ("cron", "interval")
QUEUE_TYPES = ("fifo", "priority")
QUEUE_STATUSES = ("idle", "running", "paused")
WORKER_STATUSES = ("idle", "busy", "stopped")


def _now():
    # P2-1 (t_c94bba06): aware-UTC default. The sibling scheduler / workflow
    # services store aware-UTC datetimes (DateTime(timezone=True)); a naive
    # utcnow() default here would create a mixed naive/aware column and break
    # comparison logic. Aware-UTC keeps the whole module consistent.
    return datetime.now(timezone.utc)


class WorkflowDelay(Base):
    """Workflow Delay (延迟) - wait N units before continuing a step."""

    __tablename__ = "workflow_delay"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("workflow.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("workflow_action.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    delay_amount = Column(Integer, nullable=False, default=0)
    unit = Column(String(20), nullable=False, default="seconds")  # seconds|minutes|hours|days
    config = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        onupdate=_now,
    )
    is_deleted = Column(Boolean, nullable=False, default=False)

    workflow = relationship("Workflow")  # unidirectional, no backref

    __table_args__ = (Index("idx_delay_workflow", "workflow_id"),)

    def __repr__(self):
        return f"<WorkflowDelay(id={self.id}, {self.delay_amount}{self.unit})>"


class WorkflowBranch(Base):
    """Workflow Branch (分支) - routing point that selects an execution path."""

    __tablename__ = "workflow_branch"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("workflow.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(200), nullable=False)
    rule = Column(JSONB, nullable=False, default=dict)  # routing rule (no eval in scaffold)
    config = Column(JSONB, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        onupdate=_now,
    )
    is_deleted = Column(Boolean, nullable=False, default=False)

    workflow = relationship("Workflow")  # unidirectional, no backref

    __table_args__ = (Index("idx_branch_workflow", "workflow_id"),)

    def __repr__(self):
        return f"<WorkflowBranch(id={self.id}, name={self.name})>"


class WorkflowScheduler(Base):
    """Workflow Scheduler (调度器) - cron expression or fixed-interval schedule.

    ``schedule_type`` selects the mode:
      - cron:     ``cron_expression`` is the 5/6-field expression; ``timezone`` applies
      - interval: ``interval_seconds`` is the fixed gap between runs
    """

    __tablename__ = "workflow_scheduler"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("workflow.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    trigger_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("workflow_trigger.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name = Column(String(200), nullable=False)
    schedule_type = Column(String(20), nullable=False, default="interval")  # cron|interval
    cron_expression = Column(String(100), nullable=True)
    interval_seconds = Column(Integer, nullable=True)
    timezone = Column(String(50), nullable=False, default="UTC")
    enabled = Column(Boolean, nullable=False, default=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        onupdate=_now,
    )
    is_deleted = Column(Boolean, nullable=False, default=False)

    workflow = relationship("Workflow")  # unidirectional, no backref

    __table_args__ = (
        Index("idx_scheduler_workflow", "workflow_id"),
        Index(
            "idx_scheduler_enabled",
            "enabled",
            postgresql_where=is_deleted == False,  # noqa: E712
        ),
    )

    def __repr__(self):
        return (
            f"<WorkflowScheduler(id={self.id}, type={self.schedule_type}, "
            f"enabled={self.enabled})>"
        )


class WorkflowQueue(Base):
    """Workflow Queue (任务队列) - holds units of execution work."""

    __tablename__ = "workflow_queue"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("workflow.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name = Column(String(100), nullable=False, unique=True, index=True)
    type = Column(String(30), nullable=False, default="fifo")  # fifo|priority
    max_concurrency = Column(Integer, nullable=False, default=1)
    retry_limit = Column(Integer, nullable=False, default=0)
    timeout_seconds = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="idle")

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        onupdate=_now,
    )
    is_deleted = Column(Boolean, nullable=False, default=False)

    workflow = relationship("Workflow")  # unidirectional, no backref

    __table_args__ = (
        Index("idx_queue_workflow", "workflow_id"),
        Index(
            "idx_queue_status",
            "status",
            postgresql_where=is_deleted == False,  # noqa: E712
        ),
    )

    def __repr__(self):
        return f"<WorkflowQueue(id={self.id}, name={self.name}, status={self.status})>"


class WorkflowWorker(Base):
    """Workflow Worker (执行器) - consumes tasks from a queue."""

    __tablename__ = "workflow_worker"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    queue_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("workflow_queue.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name = Column(String(200), nullable=False)
    status = Column(String(20), nullable=False, default="idle")  # idle|busy|stopped
    config = Column(JSONB, nullable=False, default=dict)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        onupdate=_now,
    )
    is_deleted = Column(Boolean, nullable=False, default=False)

    queue = relationship("WorkflowQueue")  # unidirectional, no backref

    __table_args__ = (
        Index("idx_worker_queue", "queue_id"),
        Index(
            "idx_worker_status",
            "status",
            postgresql_where=is_deleted == False,  # noqa: E712
        ),
    )

    def __repr__(self):
        return f"<WorkflowWorker(id={self.id}, name={self.name}, status={self.status})>"
