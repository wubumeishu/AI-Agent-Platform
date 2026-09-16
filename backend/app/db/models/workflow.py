"""Workflow execution logging models (Phase 4).

ExecutionLog is the audit/observability record for every task & workflow
execution in the queue + worker engine (t_wf_004). It captures:

- execution timing (start/finish/duration)
- input parameters and output result
- execution status and error information
- retry bookkeeping

Design note:
    The referenced workflow/queue/worker/task tables are introduced by
    t_wf_001 / t_wf_004. To keep ExecutionLog independently migratable and
    testable without blocking on those tables, the reference columns below
    are plain indexed UUIDs WITHOUT foreign-key constraints. They are logical
    references that can be promoted to real FKs once the sibling tables land.
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
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import relationship

from app.db.models.base import Base


# Observed execution states (mirrors the platform task-state model in ARCHITECTURE.md #15)
EXECUTION_STATES = ("pending", "running", "success", "failed", "cancelled", "timeout")
TRIGGER_TYPES = ("manual", "scheduled", "event", "cron")
EXECUTION_TYPES = ("task", "workflow", "scheduler", "action", "manual")

# Core workflow configuration vocabulary (this module)
WORKFLOW_TYPES = ("auto", "manual")
WORKFLOW_STATUSES = ("draft", "active", "paused", "archived")
ACTION_TYPES = ("conversation", "message", "tag", "status_change", "notification", "custom")
CONDITION_OPERATORS = ("eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in", "contains", "regex")


class ExecutionLog(Base):
    """Execution Log (执行日志) - detailed record of a single execution.

    One row per execution. Supports execution-history querying and
    troubleshooting (failure diagnosis) plus a retention cleanup policy.
    """

    __tablename__ = "execution_log"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Logical references to the workflow subsystem (no FK constraints yet).
    workflow_id = Column(PGUUID(as_uuid=True), nullable=True, index=True)
    queue_id = Column(PGUUID(as_uuid=True), nullable=True, index=True)
    worker_id = Column(PGUUID(as_uuid=True), nullable=True, index=True)
    task_id = Column(PGUUID(as_uuid=True), nullable=True, index=True)

    # Execution identity
    execution_type = Column(String(50), nullable=False, default="task", index=True)
    trigger_type = Column(String(20), nullable=False, default="manual")  # manual | scheduled | event | cron
    status = Column(String(20), nullable=False, default="pending", index=True)  # pending | running | success | failed | cancelled | timeout

    # Timing
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Float, nullable=True)

    # Input / output (the "日志包含输入输出信息" criterion)
    input_params = Column(JSONB, nullable=False, default=dict)
    output_result = Column(JSONB, nullable=True)

    # Error capture (the "错误日志记录完整" criterion)
    error_message = Column(Text, nullable=True)
    error_code = Column(String(100), nullable=True)

    # Retry bookkeeping
    retry_count = Column(Integer, nullable=False, default=0)

    # Free-form observability metadata (never store secrets here — see ARCHITECTURE.md #16)
    metadata_ = Column(JSONB, nullable=False, default=dict)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    is_deleted = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("idx_execution_log_status", "status"),
        Index("idx_execution_log_workflow", "workflow_id"),
        Index("idx_execution_log_queue", "queue_id"),
        Index("idx_execution_log_worker", "worker_id"),
        Index("idx_execution_log_task", "task_id"),
        Index("idx_execution_log_created", "created_at"),
    )

    def __repr__(self):
        return (
            f"<ExecutionLog(id={self.id}, type={self.execution_type}, "
            f"status={self.status}, retries={self.retry_count})>"
        )


# =====================================================================
# Core workflow configuration model (t_wf_002)
#
# Hierarchy:  Workflow 1--N Trigger 1--N Condition 1--N Action
#
# Each row supports soft-delete (is_deleted). Child rows are hard-deleted
# when a parent is deleted (cascade="all, delete-orphan"), and the service
# layer enforces the same rule on soft-delete. Logical FKs on
# ExecutionLog.workflow_id can be promoted to real FKs on this table.
# =====================================================================


class Workflow(Base):
    """Workflow (工作流) - top-level automation definition."""

    __tablename__ = "workflow"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    # auto = scheduled/event driven, manual = started on demand
    workflow_type = Column(String(20), nullable=False, default="auto", index=True)
    # draft | active | paused | archived
    status = Column(String(20), nullable=False, default="draft", index=True)
    # Free-form configuration (target entities, platforms, shared params, ...)
    config = Column(JSONB, nullable=False, default=dict)
    # Execution policy defaults (concurrency, timeout, retry)
    execution_policy = Column(JSONB, nullable=False, default=dict)
    version = Column(Integer, nullable=False, default=1)

    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), index=True,
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    is_deleted = Column(Boolean, nullable=False, default=False)

    # Relationships (child rows hard-delete with the parent)
    triggers = relationship(
        "WorkflowTrigger",
        back_populates="workflow",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("idx_workflow_status_name", "status", "name"),
        Index("idx_workflow_type", "workflow_type"),
    )

    def __repr__(self):
        return f"<Workflow(id={self.id}, name={self.name}, status={self.status})>"


class WorkflowTrigger(Base):
    """Workflow Trigger (触发器) - when a workflow runs.

    trigger_type:
      - manual:    invoked on demand (no spec required)
      - scheduled: fires on a fixed datetime
      - cron:      fires on a cron expression
      - event:     fires when a platform event occurs
    The type-specific payload lives in ``spec`` (JSONB):
      scheduled -> {"run_at": iso8601, "repeat_interval_hours": int?}
      cron      -> {"cron": "*/5 * * * *", "timezone": "Asia/Tokyo"?}
      event     -> {"event": "message.created", "topic": ...}
      manual    -> {}
    """

    __tablename__ = "workflow_trigger"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("workflow.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(200), nullable=True)
    trigger_type = Column(String(20), nullable=False, default="manual", index=True)
    spec = Column(JSONB, nullable=False, default=dict)
    enabled = Column(Boolean, nullable=False, default=True)

    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    is_deleted = Column(Boolean, nullable=False, default=False)

    workflow = relationship("Workflow", back_populates="triggers")
    conditions = relationship(
        "WorkflowCondition",
        back_populates="trigger",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("idx_trigger_workflow", "workflow_id"),
    )

    def __repr__(self):
        return (
            f"<WorkflowTrigger(id={self.id}, workflow_id={self.workflow_id}, "
            f"type={self.trigger_type})>"
        )


class WorkflowCondition(Base):
    """Workflow Condition (条件) - a guard evaluated before actions run.

    ``expression`` stores the condition expression as a JSON structure
    (no expression-parsing engine in this slice):

        {"field": "customer.total_orders", "operator": "gte", "value": 3}

    Operator vocabulary (see CONDITION_OPERATORS):
        eq, neq, gt, gte, lt, lte, in, not_in, contains, regex
    ``logic`` controls how this condition combines with siblings:
        "and" (default) | "or"
    """

    __tablename__ = "workflow_condition"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    trigger_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("workflow_trigger.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(200), nullable=True)
    expression = Column(JSONB, nullable=False, default=dict)
    logic = Column(String(5), nullable=False, default="and")  # and | or
    priority = Column(Integer, nullable=False, default=0)

    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    is_deleted = Column(Boolean, nullable=False, default=False)

    trigger = relationship("WorkflowTrigger", back_populates="conditions")
    actions = relationship(
        "WorkflowAction",
        back_populates="condition",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("idx_condition_trigger", "trigger_id"),
    )

    def __repr__(self):
        return f"<WorkflowCondition(id={self.id}, trigger_id={self.trigger_id})>"


class WorkflowAction(Base):
    """Workflow Action (动作) - what runs when conditions pass.

    action_type vocabulary (see ACTION_TYPES):
      - conversation:   open/continue a conversation with a persona
      - message:        send a message on a channel
      - tag:            apply/remove tags on an entity
      - status_change:  change an entity's lifecycle status
      - notification:   push a notification
      - custom:         free-form executor payload
    The executor payload (template ids, entity selectors, text, ...) lives
    in ``params`` (JSONB).
    """

    __tablename__ = "workflow_action"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    condition_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("workflow_condition.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(200), nullable=True)
    action_type = Column(String(30), nullable=False, default="message", index=True)
    params = Column(JSONB, nullable=False, default=dict)
    priority = Column(Integer, nullable=False, default=0)

    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    is_deleted = Column(Boolean, nullable=False, default=False)

    condition = relationship("WorkflowCondition", back_populates="actions")

    __table_args__ = (
        Index("idx_action_condition", "condition_id"),
    )

    def __repr__(self):
        return (
            f"<WorkflowAction(id={self.id}, condition_id={self.condition_id}, "
            f"type={self.action_type})>"
        )
