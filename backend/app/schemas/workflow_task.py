"""Queue + Worker execution engine schemas (t_wf_004).

Request / response models for:
- enqueuing a task onto a queue
- claiming (dequeue) + executing a task on a worker
- transitioning task state (success / failed / cancelled)
- retrying a failed/timeout task
- sweeping expired (timed-out) running tasks
- queue-management + execution-state tracking

The ``status`` field is validated against ``TASK_STATES`` so the API can never
silently write an illegal state.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models.workflow_task import TASK_STATES, TERMINAL_STATES

_STATE_PATTERN = "^(" + "|".join(TASK_STATES) + ")$"


# ========== Task create (enqueue) ==========

class TaskCreate(BaseModel):
    """Enqueue a new unit of work onto a queue."""
    queue_id: UUID
    workflow_id: Optional[UUID] = None
    worker_id: Optional[UUID] = None  # pin to a specific worker, else any
    name: Optional[str] = Field(None, max_length=200)
    payload: Dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=0, ge=0, description="Lower value is dequeued first.")
    scheduled_at: Optional[datetime] = None  # None -> ready immediately
    max_retries: int = Field(default=0, ge=0)
    timeout_seconds: Optional[int] = Field(None, ge=1, description="Per-task timeout; None -> queue timeout.")
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ========== Task update / state transition ==========

class TaskStateUpdate(BaseModel):
    """Drive a task to a terminal state (or cancel)."""
    status: str = Field(..., pattern=_STATE_PATTERN)
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = Field(None, max_length=5000)
    error_code: Optional[str] = Field(None, max_length=100)


class TaskGeneralUpdate(BaseModel):
    """Update mutable fields of a task that is not yet terminal."""
    name: Optional[str] = Field(None, max_length=200)
    payload: Optional[Dict[str, Any]] = None
    priority: Optional[int] = Field(None, ge=0)
    scheduled_at: Optional[datetime] = None
    max_retries: Optional[int] = Field(None, ge=0)
    timeout_seconds: Optional[int] = Field(None, ge=1)
    metadata: Optional[Dict[str, Any]] = None


# ========== Task response ==========

class TaskResponse(BaseModel):
    """A single queued task record."""
    id: UUID
    queue_id: UUID
    worker_id: Optional[UUID] = None
    workflow_id: Optional[UUID] = None
    name: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    status: str
    priority: int = 0
    scheduled_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 0
    timeout_seconds: Optional[int] = None
    claimed_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    # derived convenience flag
    is_retryable: bool = False

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, t) -> "TaskResponse":
        return cls(
            id=t.id,
            queue_id=t.queue_id,
            worker_id=t.worker_id,
            workflow_id=t.workflow_id,
            name=t.name,
            payload=t.payload or {},
            status=t.status,
            priority=t.priority or 0,
            scheduled_at=t.scheduled_at,
            retry_count=t.retry_count or 0,
            max_retries=t.max_retries or 0,
            timeout_seconds=t.timeout_seconds,
            claimed_at=t.claimed_at,
            started_at=t.started_at,
            finished_at=t.finished_at,
            duration_ms=t.duration_ms,
            result=t.result,
            error_message=t.error_message,
            error_code=t.error_code,
            metadata=t.metadata_ or {},
            created_at=t.created_at,
            updated_at=t.updated_at,
            is_retryable=bool(t.is_retryable),
        )


class TaskListResponse(BaseModel):
    """Paginated task listing (e.g. per-queue backlog + history)."""
    items: List[TaskResponse]
    total: int
    page: int
    page_size: int


class TaskFilter(BaseModel):
    """Rich task query (filter + pagination)."""
    queue_id: Optional[UUID] = None
    worker_id: Optional[UUID] = None
    workflow_id: Optional[UUID] = None
    status: Optional[str] = Field(None, pattern=_STATE_PATTERN)
    status_in: Optional[List[str]] = None  # e.g. ["failed", "timeout"]
    retryable: Optional[bool] = None
    scheduled_after: Optional[datetime] = None
    scheduled_before: Optional[datetime] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    order_by: str = Field(default="created_at", pattern="^(created_at|priority|status|scheduled_at)$")
    ascending: bool = True


# ========== Execution result (worker -> engine) ==========

class TaskExecuteResult(BaseModel):
    """Outcome of executing a claimed task."""
    task_id: UUID
    status: str  # success | failed | timeout
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    duration_ms: Optional[float] = None


# ========== Timeout sweep ==========

class TimeoutSweepRequest(BaseModel):
    """Sweep running tasks that have exceeded their timeout."""
    now: Optional[datetime] = None  # injectable for tests; defaults to utcnow
    limit: int = Field(default=1000, ge=1, le=100000)


class TimeoutSweepResponse(BaseModel):
    """Result of a timeout sweep."""
    swept: int
    task_ids: List[UUID]


# ========== Queue management / stats ==========

class QueueStats(BaseModel):
    """Aggregated per-state counts for one queue."""
    queue_id: UUID
    pending: int
    running: int
    success: int
    failed: int
    cancelled: int
    timeout: int
    total: int
    retryable: int  # failed/timeout tasks that still have retries left


class QueueStatsResponse(BaseModel):
    """Queue stats + derived readiness flags."""
    queue_id: UUID
    stats: QueueStats
    has_backlog: bool
    is_idle: bool


class ClearQueueRequest(BaseModel):
    """Cancel every non-terminal task currently sitting in a queue."""
    keep_running: bool = False  # when true, running tasks are left alone


class ClearQueueResponse(BaseModel):
    cancelled: int
    queue_id: UUID
