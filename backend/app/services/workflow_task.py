"""Queue + Worker execution engine service (t_wf_004).

Drives the ``WorkflowTask`` entity through its lifecycle:

    enqueue -> claim (dequeue) -> execute -> finish (success/failed/timeout)
                          \\-> cancel
    failed / timeout -> retry (while retries remain) -> pending

Design notes
------------
- The engine is **loosely coupled** from AI / CRM / browser platform logic.
  It depends on a pluggable :class:`Executor` (adapter, per the
  BrowserProvider / AI-provider separation principle). The default
  :class:`EchoExecutor` is a safe no-side-effect double; real integrations
  (t_wf_006 conversation, t_wf_007 CRM) supply their own executor.
- Dequeue is **atomic**: :meth:`QueueWorkerEngine.claim_next` uses Postgres
  ``FOR UPDATE SKIP LOCKED`` so two workers never grab the same task on the
  single-machine multi-worker setup (distributed workers are out of scope,
  but this is the correct primitive to stay correct when we get there).
- Timeout handling is a **sweep**, not a timer: :meth:`QueueWorkerEngine.sweep_timeouts`
  marks every running task whose effective timeout (task.timeout_seconds,
  falling back to the queue's) has elapsed as ``timeout``.
- Execution observability (``ExecutionLog``) is intentionally *not* written
  inside the engine's DB transactions: the engine is the source of truth for
  task state, and a separate integration (or the execution-log endpoints)
  records the log row. Keeping the engine self-contained means it is
  unit-testable against a mocked session, matching the repo convention.

Only depends on ``AsyncSession`` — mirroring ``ExecutionLogService`` /
``WorkflowService`` so it is independently testable.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, Tuple

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.db.models.workflow_task import WorkflowTask
from app.schemas.workflow_task import (
    TaskCreate,
    TaskExecuteResult,
    TaskFilter,
    TaskGeneralUpdate,
    TaskResponse,
    TaskStateUpdate,
    TimeoutSweepRequest,
    TimeoutSweepResponse,
    QueueStats,
    QueueStatsResponse,
    ClearQueueRequest,
    ClearQueueResponse,
)

logger = logging.getLogger(__name__)


# ----- Legal state transitions (source -> set of allowed targets) -----
LEGAL_TRANSITIONS: Dict[str, frozenset] = {
    "pending": frozenset({"running", "cancelled"}),
    "running": frozenset({"success", "failed", "timeout", "cancelled"}),
    # failed/timeout can be re-queued for retry -> pending (guarded by retry count)
    "failed": frozenset({"pending"}),
    "timeout": frozenset({"pending"}),
    "cancelled": frozenset(),
    "success": frozenset(),
}


class Executor(Protocol):
    """A pluggable unit of work that actually *does* something.

    Implementations supply the real AI / CRM / browser action (t_wf_006,
    t_wf_007). The engine only knows this interface, never the concrete
    provider — keeping platform logic isolated.
    """

    async def run(self, payload: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the payload. Return a JSON-serialisable result dict.

        Raises ``Exception`` on failure; the engine records the task as
        ``failed``.
        """
        ...


class EchoExecutor:
    """Default, side-effect-free executor.

    Returns a deterministic echo of the payload. Ideal for tests, the API
    docs examples, and any queue that is only being exercised for state
    tracking (no real business action wired yet).
    """

    async def run(self, payload: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        return {"echo": payload, "ok": True, "executor": "echo"}


class TaskStateError(Exception):
    """Raised when a task is moved to a state that is not legal from its current state."""

    def __init__(self, task_id: UUID, from_state: str, to_state: str):
        self.task_id = task_id
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Illegal task transition {from_state!r} -> {to_state!r} for task {task_id}"
        )


class TaskNotFoundError(Exception):
    """Raised when an engine operation targets a task that does not exist."""

    def __init__(self, task_id: UUID):
        self.task_id = task_id
        super().__init__(f"Task {task_id} not found")


class QueueNotFoundError(Exception):
    """Raised when a task is enqueued onto a queue that does not exist.

    Guards against orphaned tasks: a task enqueued onto an unknown
    ``queue_id`` can never be claimed (``claim_next`` matches on
    ``WorkflowTask.queue_id``) and would silently rot the backlog. t_a986f957.
    """

    def __init__(self, queue_id: UUID):
        self.queue_id = queue_id
        super().__init__(f"Queue {queue_id} not found")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _get_task_row(engine: "QueueWorkerEngine", task_id: UUID) -> WorkflowTask:
    """Fetch the live ORM row for ``task_id`` (used by the router's update path).

    Raises :class:`TaskNotFoundError` when the task does not exist.
    """
    row = await engine._get_task(task_id)
    if row is None:
        raise TaskNotFoundError(task_id)
    return row


class QueueWorkerEngine:
    """Execution engine: enqueue / dequeue / execute / state / timeout.

    Depends only on an ``AsyncSession``. An :class:`Executor` is supplied per
    call, so the engine never hard-codes a provider.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- internal helpers ----------

    async def _get_task(self, task_id: UUID) -> Optional[WorkflowTask]:
        res = await self.db.execute(
            select(WorkflowTask).where(
                WorkflowTask.id == task_id,
                WorkflowTask.is_deleted == False,  # noqa: E712
            )
        )
        return res.scalar_one_or_none()

    @staticmethod
    def _assert_transition(task: WorkflowTask, target: str) -> None:
        """Raise :class:`TaskStateError` if ``task.status -> target`` is illegal."""
        if target not in LEGAL_TRANSITIONS.get(task.status, frozenset()):
            raise TaskStateError(task.id, task.status, target)

    # ---------- enqueue ----------

    async def enqueue(self, data: TaskCreate) -> TaskResponse:
        """Enqueue a new task onto ``data.queue_id`` in the ``pending`` state.

        A future ``scheduled_at`` keeps the task out of the ready set until
        that time (``claim_next`` only picks up tasks with scheduled_at <= now).

        Raises :class:`QueueNotFoundError` when ``data.queue_id`` does not
        correspond to a live ``WorkflowQueue`` — enqueuing onto an unknown
        queue would produce an orphaned task that can never be claimed.
        (t_a986f957)
        """
        from app.db.models.workflow_runtime import (  # deferred; may be absent in tests
            WorkflowQueue,
        )
        queue = (
            await self.db.execute(
                select(WorkflowQueue).where(
                    WorkflowQueue.id == data.queue_id,
                    WorkflowQueue.is_deleted == False,  # noqa: E712
                )
            )
        ).scalar_one_or_none()
        if queue is None:
            raise QueueNotFoundError(data.queue_id)

        task = WorkflowTask(
            queue_id=data.queue_id,
            worker_id=data.worker_id,
            workflow_id=data.workflow_id,
            name=data.name,
            payload=data.payload or {},
            status="pending",
            priority=data.priority,
            scheduled_at=data.scheduled_at,
            retry_count=0,
            max_retries=data.max_retries,
            timeout_seconds=data.timeout_seconds,
            metadata_=data.metadata or {},
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        logger.info(
            "Enqueued task %s on queue %s (priority=%s, scheduled_at=%s)",
            task.id, task.queue_id, task.priority, task.scheduled_at,
        )
        return TaskResponse.from_model(task)

    # ---------- read ----------

    async def get_task(self, task_id: UUID) -> Optional[TaskResponse]:
        task = await self._get_task(task_id)
        return None if task is None else TaskResponse.from_model(task)

    async def list_tasks(self, f: TaskFilter) -> Tuple[List[TaskResponse], int]:
        q = select(WorkflowTask).where(WorkflowTask.is_deleted == False)  # noqa: E712
        if f.queue_id:
            q = q.where(WorkflowTask.queue_id == f.queue_id)
        if f.worker_id:
            q = q.where(WorkflowTask.worker_id == f.worker_id)
        if f.workflow_id:
            q = q.where(WorkflowTask.workflow_id == f.workflow_id)
        if f.status:
            q = q.where(WorkflowTask.status == f.status)
        if f.status_in:
            q = q.where(WorkflowTask.status.in_(f.status_in))
        if f.scheduled_after:
            q = q.where(WorkflowTask.scheduled_at >= f.scheduled_after)
        if f.scheduled_before:
            q = q.where(WorkflowTask.scheduled_at <= f.scheduled_before)

        # retryable filter: (failed|timeout) AND retry_count < max_retries
        if f.retryable:
            q = q.where(
                WorkflowTask.status.in_(["failed", "timeout"]),
                WorkflowTask.retry_count < WorkflowTask.max_retries,
            )
        elif f.retryable is False:
            q = q.where(
                or_(
                    WorkflowTask.status.notin_(["failed", "timeout"]),
                    WorkflowTask.retry_count >= WorkflowTask.max_retries,
                )
            )

        total = (
            await self.db.execute(select(func.count()).select_from(q.subquery()))
        ).scalar_one()

        order_col = getattr(WorkflowTask, f.order_by)
        order = order_col.asc() if f.ascending else order_col.desc()
        q = q.order_by(order).offset((f.page - 1) * f.page_size).limit(f.page_size)
        rows = (await self.db.execute(q)).scalars().all()
        return [TaskResponse.from_model(t) for t in rows], total

    # ---------- dequeue / claim (atomic) ----------

    async def claim_next(
        self,
        queue_id: UUID,
        worker_id: Optional[UUID] = None,
        now: Optional[datetime] = None,
    ) -> Optional[TaskResponse]:
        """Atomically claim the oldest ready task on ``queue_id``.

        "Ready" = status pending, not soft-deleted, scheduled_at in the past
        (or NULL). ``priority`` breaks ties (lower first), then created_at.
        Uses Postgres ``FOR UPDATE SKIP LOCKED`` so concurrent workers do not
        double-claim. Returns None when the queue has no ready work.

        A pinned ``worker_id`` restricts the claim to tasks assigned to that
        worker (or unassigned tasks).
        """
        now = now or _utcnow()
        stmt = (
            select(WorkflowTask)
            .where(
                WorkflowTask.queue_id == queue_id,
                WorkflowTask.status == "pending",
                WorkflowTask.is_deleted == False,  # noqa: E712
                or_(
                    WorkflowTask.scheduled_at.is_(None),
                    WorkflowTask.scheduled_at <= now,
                ),
            )
            .order_by(WorkflowTask.priority.asc(), WorkflowTask.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if worker_id is not None:
            stmt = stmt.where(
                or_(
                    WorkflowTask.worker_id.is_(None),
                    WorkflowTask.worker_id == worker_id,
                )
            )

        res = await self.db.execute(stmt)
        task = res.scalars().first()
        if task is None:
            return None

        # pending -> running, stamp timing.
        task.status = "running"
        task.claimed_at = now
        task.started_at = now
        task.finished_at = None
        task.duration_ms = None
        task.error_message = None
        task.error_code = None
        if task.worker_id is None and worker_id is not None:
            task.worker_id = worker_id
        await self.db.commit()
        await self.db.refresh(task)
        logger.info(
            "Claimed task %s on queue %s by worker %s", task.id, queue_id, task.worker_id
        )
        return TaskResponse.from_model(task)

    # ---------- execute (pluggable) ----------

    async def execute_task(
        self,
        task: TaskResponse,
        executor: Executor,
        context: Optional[Dict[str, Any]] = None,
    ) -> TaskExecuteResult:
        """Run ``executor`` for a claimed (running) task and record the outcome.

        - success: executor returns -> status success, result captured
        - failure: executor raises  -> status failed, error captured

        The task must be in the ``running`` state (as returned by
        :meth:`claim_next`). Duration is stamped from ``started_at``.
        """
        task_row = await self._get_task(task.id)
        if task_row is None:
            raise TaskNotFoundError(task.id)
        if task_row.status != "running":
            raise TaskStateError(task_row.id, task_row.status, "success/failed (expected running)")

        ctx = dict(context or {})
        ctx.setdefault("task_id", str(task_row.id))
        ctx.setdefault("queue_id", str(task_row.queue_id))
        ctx.setdefault(
            "workflow_id", str(task_row.workflow_id) if task_row.workflow_id else None
        )
        ctx.setdefault("retry_count", task_row.retry_count or 0)

        try:
            result = await executor.run(task_row.payload or {}, ctx)
            task_row.status = "success"
            task_row.result = result if isinstance(result, dict) else {"value": result}
            task_row.error_message = None
            task_row.error_code = None
            status = "success"
        except Exception as exc:  # noqa: BLE001 - record any executor failure
            logger.warning("Task %s execution failed: %s", task_row.id, exc)
            task_row.status = "failed"
            task_row.error_message = str(exc)[:5000]
            task_row.error_code = "EXECUTION_FAILED"
            result = None
            status = "failed"

        now = _utcnow()
        task_row.finished_at = now
        if task_row.started_at is not None:
            task_row.duration_ms = (now - task_row.started_at).total_seconds() * 1000.0
        await self.db.commit()
        await self.db.refresh(task_row)

        return TaskExecuteResult(
            task_id=task_row.id,
            status=status,
            result=task_row.result,
            error_message=task_row.error_message,
            error_code=task_row.error_code,
            duration_ms=task_row.duration_ms,
        )

    # ---------- explicit state transitions ----------

    async def complete_task(
        self,
        task_id: UUID,
        result: Optional[Dict[str, Any]] = None,
    ) -> TaskResponse:
        """Mark a running task as successful."""
        return await self._finish(task_id, "success", result=result)

    async def fail_task(
        self,
        task_id: UUID,
        error_message: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> TaskResponse:
        """Mark a running task as failed."""
        return await self._finish(
            task_id, "failed", error_message=error_message, error_code=error_code
        )

    async def cancel_task(self, task_id: UUID, reason: Optional[str] = None) -> TaskResponse:
        """Cancel a pending or running task."""
        task = await self._get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        self._assert_transition(task, "cancelled")
        task.status = "cancelled"
        now = _utcnow()
        task.finished_at = now
        if reason:
            task.error_message = reason
            task.error_code = "CANCELLED"
        if task.started_at is not None:
            task.duration_ms = (now - task.started_at).total_seconds() * 1000.0
        await self.db.commit()
        await self.db.refresh(task)
        logger.info("Cancelled task %s (%s)", task.id, reason)
        return TaskResponse.from_model(task)

    async def _finish(
        self,
        task_id: UUID,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> TaskResponse:
        task = await self._get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        self._assert_transition(task, status)
        task.status = status
        now = _utcnow()
        task.finished_at = now
        if result is not None:
            task.result = result
        if error_message is not None:
            task.error_message = error_message
        if error_code is not None:
            task.error_code = error_code
        if task.started_at is not None:
            task.duration_ms = (now - task.started_at).total_seconds() * 1000.0
        await self.db.commit()
        await self.db.refresh(task)
        logger.info("Task %s -> %s", task.id, status)
        return TaskResponse.from_model(task)

    # ---------- retry ----------

    async def retry_task(self, task_id: UUID) -> TaskResponse:
        """Re-queue a failed/timeout task, if it still has retries left.

        Increments ``retry_count`` and returns the task to ``pending`` so the
        next :meth:`claim_next` picks it up. Once ``retry_count`` reaches
        ``max_retries`` the task stays in its terminal state.
        """
        task = await self._get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        if task.status not in ("failed", "timeout"):
            raise TaskStateError(task.id, task.status, "pending (retry only from failed/timeout)")
        if (task.retry_count or 0) >= (task.max_retries or 0):
            raise TaskStateError(task.id, task.status, "pending (retry exhausted)")

        task.retry_count = (task.retry_count or 0) + 1
        task.status = "pending"
        task.claimed_at = None
        task.started_at = None
        task.finished_at = None
        task.duration_ms = None
        task.error_message = None
        task.error_code = None
        task.result = None
        await self.db.commit()
        await self.db.refresh(task)
        logger.info(
            "Retried task %s -> pending (retry %s/%s)",
            task.id, task.retry_count, task.max_retries,
        )
        return TaskResponse.from_model(task)

    # ---------- timeout sweep ----------

    async def sweep_timeouts(
        self,
        req: Optional[TimeoutSweepRequest] = None,
    ) -> TimeoutSweepResponse:
        """Mark every running task that has exceeded its effective timeout.

        Effective timeout = ``task.timeout_seconds`` if set, else the owning
        queue's ``timeout_seconds``. A running task is expired when
        ``started_at`` (or ``claimed_at`` fallback) + timeout <= now. Expired
        tasks transition to the ``timeout`` terminal state (retryable if
        retries remain).

        The sweep is safe to run on a schedule (e.g. a cron every N seconds).
        """
        req = req or TimeoutSweepRequest()
        now = req.now or _utcnow()

        running = (
            await self.db.execute(
                select(WorkflowTask).where(
                    WorkflowTask.status == "running",
                    WorkflowTask.is_deleted == False,  # noqa: E712
                )
            )
        ).scalars().all()

        # Resolve per-queue timeout fallbacks in one batched query (P2-2,
        # t_c94bba06): the old code issued one select(WorkflowQueue) per
        # distinct queue_id (an N+1). A single in_() fetch keeps it to one
        # round-trip regardless of how many queues the running tasks span.
        from app.db.models.workflow_runtime import WorkflowQueue  # deferred; may be absent in tests

        queue_ids = {t.queue_id for t in running if t.queue_id is not None}
        queue_timeouts: Dict[UUID, Optional[int]] = {}
        if queue_ids:
            qrows = (
                await self.db.execute(
                    select(WorkflowQueue).where(WorkflowQueue.id.in_(queue_ids))
                )
            ).scalars().all()
            queue_timeouts = {q.id: q.timeout_seconds for q in qrows}

        swept_ids: List[UUID] = []
        for t in running:
            base = t.started_at or t.claimed_at
            if base is None:
                continue
            timeout = (
                t.timeout_seconds
                if t.timeout_seconds is not None
                else queue_timeouts.get(t.queue_id)
            )
            if timeout is None:
                continue
            if (now - base).total_seconds() >= timeout:
                t.status = "timeout"
                t.finished_at = now
                t.error_message = "Task execution timed out"
                t.error_code = "TIMEOUT"
                t.duration_ms = (now - base).total_seconds() * 1000.0
                swept_ids.append(t.id)
                logger.warning("Task %s timed out (exceeded %ss)", t.id, timeout)

        if swept_ids:
            await self.db.commit()
        return TimeoutSweepResponse(swept=len(swept_ids), task_ids=swept_ids)

    # ---------- crash recovery (P1-R2) ----------

    async def recover_stale_running(
        self,
        now: Optional[datetime] = None,
        staleness_seconds: Optional[float] = None,
    ) -> int:
        """Reset stuck ``running`` tasks back to ``pending`` (startup recovery).

        After a process crash / restart, any task that was ``running`` when the
        old process died is an orphan: nothing will ever commit its terminal
        state. In the single-node V1 deployment the in-process worker is the only
        executor, so *every* ``running`` row at boot belongs to the dead process
        and must be re-queued. This method resets those rows to ``pending``
        (clearing the stale claim/started timestamps so a fresh claim re-stamps
        them) and returns how many were recovered.

        ``staleness_seconds`` narrows the reset to tasks whose ``claimed_at`` is
        at least that old (the multi-worker "another live worker may still own
        this" safety window). When ``None`` (the default for a fresh process
        boot) *all* running tasks are reset, which is correct for a single-node
        restart where the previous worker is provably dead. Operators who run a
        longer-lived worker can pass the config threshold to avoid racing a
        sibling worker that is still legitimately mid-execution.
        """
        now = now or _utcnow()
        res = await self.db.execute(
            select(WorkflowTask).where(
                WorkflowTask.status == "running",
                WorkflowTask.is_deleted == False,  # noqa: E712
            )
        )
        rows = res.scalars().all()

        recovered: List[UUID] = []
        for t in rows:
            if staleness_seconds is not None:
                base = t.claimed_at or t.started_at
                if base is not None:
                    # A task claimed very recently may still be finishing on a
                    # live sibling worker; only reset the clearly-stale ones.
                    if (now - base).total_seconds() < staleness_seconds:
                        continue
            t.status = "pending"
            t.claimed_at = None
            t.started_at = None
            t.finished_at = None
            t.duration_ms = None
            t.error_message = None
            t.error_code = None
            t.result = None
            t.worker_id = None
            recovered.append(t.id)
            logger.warning(
                "Recovered stale running task %s -> pending (crash recovery)",
                t.id,
            )
        if recovered:
            await self.db.commit()
        return len(recovered)

    async def sweep_and_retry(
        self,
        req: Optional[TimeoutSweepRequest] = None,
    ) -> Dict[str, int]:
        """Periodic recovery tick: sweep expired running tasks, then re-queue
        the retryable ones (P1-R2: a stuck/crashed execution is *recoverable*
        by default, not an unrecoverable orphan).

        Steps:
          1. ``sweep_timeouts`` marks every running task past its effective
             timeout as ``timeout`` (and commits it).
          2. Re-queue every task that is now terminal-``failed``/``timeout``
             and still has retries left (``retry_count < max_retries``) back
             to ``pending`` so the next ``claim_next`` re-executes it.

        The step-2 query reads the *committed* terminal backlog, which includes
        exactly the tasks swept in step 1 (plus any pre-existing failed/timeout
        rows awaiting a retry), so a single periodic tick heals the whole
        backlog with no double-requeue.

        Returns a small summary ``{"swept": n, "requeued": m}`` so a periodic
        driver (or operator) can observe how much was recovered this tick.
        """
        sweep = await self.sweep_timeouts(req)

        # Re-queue the committed terminal backlog (swept-to-timeout rows plus
        # any pre-existing failed/timeout rows still awaiting a retry).
        from sqlalchemy import select as _select

        backlog = (
            await self.db.execute(
                _select(WorkflowTask.id).where(
                    WorkflowTask.status.in_(["failed", "timeout"]),
                    WorkflowTask.is_deleted == False,  # noqa: E712
                    WorkflowTask.retry_count < WorkflowTask.max_retries,
                )
            )
        ).scalars().all()
        requeued = 0
        for tid in backlog:
            try:
                await self.retry_task(tid)
                requeued += 1
            except TaskStateError:
                # Retry exhausted (max_retries reached) or the task is no
                # longer in a retryable state — leave it terminal and move on.
                logger.info(
                    "Task %s in terminal state but not re-queued "
                    "(retry exhausted or state changed)",
                    tid,
                )
        if requeued:
            logger.info(
                "Recovery tick: swept %s timed-out task(s), re-queued %s "
                "retryable task(s)",
                sweep.swept, requeued,
            )
        return {"swept": sweep.swept, "requeued": requeued}

    # ---------- queue stats ----------

    async def queue_stats(self, queue_id: UUID) -> QueueStatsResponse:
        rows = (
            await self.db.execute(
                select(WorkflowTask.status, func.count())
                .where(
                    WorkflowTask.queue_id == queue_id,
                    WorkflowTask.is_deleted == False,  # noqa: E712
                )
                .group_by(WorkflowTask.status)
            )
        ).all()
        counts = {s: 0 for s in ("pending", "running", "success", "failed", "cancelled", "timeout")}
        for status, cnt in rows:
            if status in counts:
                counts[status] = int(cnt)

        retryable = (
            await self.db.execute(
                select(func.count()).where(
                    WorkflowTask.queue_id == queue_id,
                    WorkflowTask.is_deleted == False,  # noqa: E712
                    WorkflowTask.status.in_(["failed", "timeout"]),
                    WorkflowTask.retry_count < WorkflowTask.max_retries,
                )
            )
        ).scalar_one()

        total = sum(counts.values())
        stats = QueueStats(
            queue_id=queue_id,
            pending=counts["pending"],
            running=counts["running"],
            success=counts["success"],
            failed=counts["failed"],
            cancelled=counts["cancelled"],
            timeout=counts["timeout"],
            total=total,
            retryable=int(retryable or 0),
        )
        return QueueStatsResponse(
            queue_id=queue_id,
            stats=stats,
            has_backlog=stats.pending > 0,
            is_idle=(stats.running == 0 and stats.pending == 0),
        )

    # ---------- clear / drain ----------

    async def clear_queue(
        self,
        queue_id: UUID,
        req: Optional[ClearQueueRequest] = None,
    ) -> ClearQueueResponse:
        """Cancel every non-terminal task in the queue (drain it).

        When ``keep_running`` is true, running tasks are left in place so an
        in-flight worker can finish them; only pending tasks are cancelled.
        """
        req = req or ClearQueueRequest()
        # t_a986f957: draining a non-existent queue used to report a clean
        # 200/cancelled=0, silently confirming a typo'd queue id. Fail with a
        # QueueNotFoundError (mapped to 404 by the router) instead.
        from app.db.models.workflow_runtime import (  # deferred; may be absent in tests
            WorkflowQueue,
        )
        queue_exists = (
            await self.db.execute(
                select(WorkflowQueue).where(
                    WorkflowQueue.id == queue_id,
                    WorkflowQueue.is_deleted == False,  # noqa: E712
                )
            )
        ).scalar_one_or_none()
        if queue_exists is None:
            raise QueueNotFoundError(queue_id)

        targets = ["pending"] if req.keep_running else ["pending", "running"]
        res = await self.db.execute(
            update(WorkflowTask)
            .where(
                WorkflowTask.queue_id == queue_id,
                WorkflowTask.status.in_(targets),
                WorkflowTask.is_deleted == False,  # noqa: E712
            )
            .values(status="cancelled", finished_at=_utcnow(), error_code="CANCELLED")
        )
        cancelled = res.rowcount or 0
        await self.db.commit()
        logger.info("Cleared queue %s: cancelled %s tasks", queue_id, cancelled)
        return ClearQueueResponse(cancelled=cancelled, queue_id=queue_id)

    # ---------- health ----------

    def health(self) -> dict:
        return {"service": "queue-worker-engine", "db_enabled": self.db is not None}
