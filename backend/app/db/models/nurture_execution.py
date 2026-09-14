"""NurturePlan execution engine models (P1 - t_a2ce2cae / ADR-010 follow-up).

Phase 5 delivered the NurturePlan *data model* + API + segment rule engine
only (ADR-010: Data/Execution Split). This module adds the missing
*execution layer*:

- ``NurtureStepExecution`` - one row per step-attempt. Captures the
  execution log (status, timing, error, content link, retry bookkeeping)
  for the Step Execution Engine. Independent of the workflow ``ExecutionLog``
  table: it records *per-step* outcomes (the granularity the nurture
  sequence needs) rather than whole-schedule fires.

Design notes:
- ``plan_id`` / ``step_id`` are plain indexed UUIDs WITHOUT foreign-key
  constraints, mirroring the workflow ``ExecutionLog`` convention - this keeps
  the table independently migratable and testable, and lets the engine tolerate
  a step row being soft-deleted mid-run.
- The engine's source of truth for "what to run next" is this table plus the
  ordered ``nurture_plan_item`` rows; the legacy ``nurture_plan.sequence_steps``
  JSON column is never read (Contract B, t_1814d03d / t_4b55abe8).
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


# Observed step-execution states.
#   pending     - scheduled, not yet started
#   running     - started, in flight
#   success     - executed cleanly
#   failed      - attempt failed, eligible for retry (attempts < max)
#   dead_letter - terminal failure (retries exhausted); operator inspectable
#   skipped     - not executed this pass (e.g. step deleted, content missing)
NURTURE_EXEC_STATES = ("pending", "running", "success", "failed", "dead_letter", "skipped")

# Content provenance recorded when a step delivers AI-generated content.
NURTURE_CONTENT_STRATEGIES = ("llm", "template", "reuse")


class NurtureStepExecution(Base):
    """One execution attempt of a single NurturePlan step."""

    __tablename__ = "nurture_step_execution"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Logical references (no FK constraints yet - promotable once stable).
    plan_id = Column(PGUUID(as_uuid=True), nullable=False, index=True)
    account_id = Column(PGUUID(as_uuid=True), nullable=True, index=True)
    step_id = Column(PGUUID(as_uuid=True), nullable=True, index=True)
    step_order = Column(Integer, nullable=False, default=0)

    # Which run-of-the-plan this attempt belongs to (anchor-based dedup).
    run_id = Column(PGUUID(as_uuid=True), nullable=True, index=True)

    # Execution identity.
    attempt = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="pending", index=True)

    # Content provenance (when this step delivered generated/reused content).
    content_item_id = Column(PGUUID(as_uuid=True), nullable=True)
    content_type = Column(String(50), nullable=True)
    content_strategy = Column(String(20), nullable=True)  # llm | template | reuse

    # Timing.
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    executed_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Float, nullable=True)

    # Retry bookkeeping + error capture.
    retry_count = Column(Integer, nullable=False, default=0)
    error_code = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)

    # Free-form observability (never store secrets - see ARCHITECTURE.md #16).
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
        Index("idx_nse_plan_status", "plan_id", "status"),
        Index("idx_nse_status", "status"),
        Index("idx_nse_run", "run_id"),
        Index("idx_nse_created", "created_at"),
    )

    def __repr__(self):
        return (
            f"<NurtureStepExecution(plan={self.plan_id}, step={self.step_order}, "
            f"attempt={self.attempt}, status={self.status})>"
        )
