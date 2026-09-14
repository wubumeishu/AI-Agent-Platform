"""Queue + Worker execution engine router (t_wf_004).

Endpoints (all under /api/v1/workflow-tasks):

    POST   /                           enqueue a task (task 入队)
    GET    /                           list tasks (filter + pagination)
    GET    /{task_id}                  fetch one task
    PUT    /{task_id}                  update mutable fields of a non-terminal task
    POST   /{task_id}/cancel           cancel a pending/running task
    POST   /{task_id}/retry           re-queue a failed/timeout task (if retries left)

Dequeue / execute / timeout / queue-management (queue 出队、执行、超时、管理):

    POST   /queues/{queue_id}/claim    atomically claim the oldest ready task (出队)
    POST   /{task_id}/complete         mark running task success
    POST   /{task_id}/fail            mark running task failed
    POST   /queues/{queue_id}/stats   per-state backlog stats
    POST   /queues/{queue_id}/clear   drain (cancel) non-terminal tasks
    POST   /sweep-timeouts            mark expired running tasks as timed-out
    GET    /health                    service self-report
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.workflow_task import (
    TaskCreate,
    TaskExecuteResult,
    TaskFilter,
    TaskGeneralUpdate,
    TaskResponse,
    TaskListResponse,
    TaskStateUpdate,
    TimeoutSweepRequest,
    TimeoutSweepResponse,
    QueueStatsResponse,
    ClearQueueRequest,
    ClearQueueResponse,
)
from app.services.workflow_task import (
    EchoExecutor,
    QueueNotFoundError,
    QueueWorkerEngine,
    TaskNotFoundError,
    TaskStateError,
)

router = APIRouter(prefix="/workflow-tasks", tags=["Workflow Task Execution Engine"])


def get_engine(db: AsyncSession = Depends(get_db)) -> QueueWorkerEngine:
    """Dependency for the execution engine."""
    return QueueWorkerEngine(db)


def _raise_task_404(err: TaskNotFoundError) -> None:
    raise HTTPException(status_code=404, detail=f"Task {err.task_id} not found")


def _raise_state_409(err: TaskStateError) -> None:
    raise HTTPException(
        status_code=409,
        detail={
            "task_id": str(err.task_id),
            "from_state": err.from_state,
            "to_state": err.to_state,
            "message": str(err),
        },
    )


# ========== Enqueue / read ==========

@router.post("", response_model=TaskResponse, status_code=201)
async def enqueue_task(
    data: TaskCreate,
    engine: QueueWorkerEngine = Depends(get_engine),
):
    """Enqueue a new task onto a queue in the ``pending`` state."""
    try:
        return await engine.enqueue(data)
    except QueueNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    queue_id: Optional[UUID] = Query(None, description="Filter by queue"),
    worker_id: Optional[UUID] = Query(None, description="Filter by worker"),
    workflow_id: Optional[UUID] = Query(None, description="Filter by workflow"),
    status: Optional[str] = Query(None, description="Filter by status"),
    retryable: Optional[bool] = Query(None, description="Only tasks that can still be retried"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    engine: QueueWorkerEngine = Depends(get_engine),
):
    """List tasks with filtering + pagination (newest first by default)."""
    f = TaskFilter(
        queue_id=queue_id,
        worker_id=worker_id,
        workflow_id=workflow_id,
        status=status,
        retryable=retryable,
        page=page,
        page_size=page_size,
    )
    items, total = await engine.list_tasks(f)
    return TaskListResponse(items=items, total=total, page=page, page_size=page_size)


# NOTE: the literal `GET /health` is defined before the parameterised
# `GET /{task_id}` so it is not swallowed by the task_id route (FastAPI
# matches routes in registration order).
@router.get("/health")
async def health_check(
    engine: QueueWorkerEngine = Depends(get_engine),
):
    """Service self-report."""
    return engine.health()


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    engine: QueueWorkerEngine = Depends(get_engine),
):
    """Fetch a single task by ID."""
    task = await engine.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: UUID,
    data: TaskGeneralUpdate,
    engine: QueueWorkerEngine = Depends(get_engine),
):
    """Update mutable fields of a task that has not reached a terminal state."""
    # Fetch the ORM row so we can enforce the "not terminal" rule then patch.
    from app.services.workflow_task import _get_task_row
    try:
        task = await _get_task_row(engine, task_id)
    except TaskNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task.is_terminal:
        raise HTTPException(
            status_code=409,
            detail=f"Task {task_id} is in terminal state '{task.status}'; cannot update.",
        )
    if data.name is not None:
        task.name = data.name
    if data.payload is not None:
        task.payload = data.payload
    if data.priority is not None:
        task.priority = data.priority
    if data.scheduled_at is not None:
        task.scheduled_at = data.scheduled_at
    if data.max_retries is not None:
        task.max_retries = data.max_retries
    if data.timeout_seconds is not None:
        task.timeout_seconds = data.timeout_seconds
    if data.metadata is not None:
        task.metadata_ = data.metadata
    await engine.db.commit()
    await engine.db.refresh(task)
    return TaskResponse.from_model(task)


# ========== Dequeue / execute ==========

@router.post("/queues/{queue_id}/claim", response_model=Optional[TaskResponse])
async def claim_task(
    queue_id: UUID,
    worker_id: Optional[UUID] = Query(None, description="Pin the claim to this worker"),
    engine: QueueWorkerEngine = Depends(get_engine),
):
    """Atomically claim (dequeue) the oldest ready task on a queue.

    Returns 204-when-empty as ``null``: a ``204 No Content``-style empty body
    is not used because the response model is optional; an empty queue yields
    a JSON ``null`` body.
    """
    claimed = await engine.claim_next(queue_id, worker_id=worker_id)
    if claimed is None:
        # 204-style empty: return None (FastAPI serialises as JSON null).
        return None
    return claimed


@router.post("/{task_id}/complete", response_model=TaskResponse)
async def complete_task(
    task_id: UUID,
    data: Optional[TaskStateUpdate] = None,
    engine: QueueWorkerEngine = Depends(get_engine),
):
    """Mark a running task as successful."""
    try:
        return await engine.complete_task(task_id)
    except TaskNotFoundError as e:
        _raise_task_404(e)
    except TaskStateError as e:
        _raise_state_409(e)


@router.post("/{task_id}/fail", response_model=TaskResponse)
async def fail_task(
    task_id: UUID,
    data: TaskStateUpdate,
    engine: QueueWorkerEngine = Depends(get_engine),
):
    """Mark a running task as failed, capturing the error."""
    try:
        return await engine.fail_task(
            task_id, error_message=data.error_message, error_code=data.error_code
        )
    except TaskNotFoundError as e:
        _raise_task_404(e)
    except TaskStateError as e:
        _raise_state_409(e)


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(
    task_id: UUID,
    reason: Optional[str] = Query(None, description="Optional cancellation reason"),
    engine: QueueWorkerEngine = Depends(get_engine),
):
    """Cancel a pending or running task."""
    try:
        return await engine.cancel_task(task_id, reason=reason)
    except TaskNotFoundError as e:
        _raise_task_404(e)
    except TaskStateError as e:
        _raise_state_409(e)


@router.post("/{task_id}/retry", response_model=TaskResponse)
async def retry_task(
    task_id: UUID,
    engine: QueueWorkerEngine = Depends(get_engine),
):
    """Re-queue a failed/timeout task if it still has retries left."""
    try:
        return await engine.retry_task(task_id)
    except TaskNotFoundError as e:
        _raise_task_404(e)
    except TaskStateError as e:
        _raise_state_409(e)


# ========== Queue management ==========

@router.post("/queues/{queue_id}/stats", response_model=QueueStatsResponse)
async def queue_stats(
    queue_id: UUID,
    engine: QueueWorkerEngine = Depends(get_engine),
):
    """Per-state backlog + retryability stats for a queue."""
    return await engine.queue_stats(queue_id)


@router.post("/queues/{queue_id}/clear", response_model=ClearQueueResponse)
async def clear_queue(
    queue_id: UUID,
    data: Optional[ClearQueueRequest] = None,
    engine: QueueWorkerEngine = Depends(get_engine),
):
    """Drain a queue: cancel its pending (and optionally running) tasks."""
    try:
        return await engine.clear_queue(queue_id, data or ClearQueueRequest())
    except QueueNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/sweep-timeouts", response_model=TimeoutSweepResponse)
async def sweep_timeouts(
    data: Optional[TimeoutSweepRequest] = None,
    engine: QueueWorkerEngine = Depends(get_engine),
):
    """Mark every running task that exceeded its timeout as ``timeout``."""
    return await engine.sweep_timeouts(data or TimeoutSweepRequest())


# The execute-with-pluggable-executor helper is exposed on the service layer
# (``QueueWorkerEngine.execute_task``) rather than as an HTTP endpoint, because
# the executor is a code object (a strategy), not JSON. Callers in-process
# (scheduler tick, event handlers) use it directly with an :class:`EchoExecutor`
# or a real provider adapter.
