"""Real execution dispatcher for the scheduler engine (architecture review P1-2).

Connects a fired schedule to the t_wf_004 Queue/Worker infrastructure: every
fire enqueues a ``WorkflowTask`` so that time-triggered (cron / interval)
workflows are actually executed by a worker instead of the default
``NoopDispatcher`` that only wrote an ``ExecutionLog`` row (a "record-only
empty shell").

Separation of concerns (mirrors the BrowserProvider / pluggable-executor rule):
the engine knows *when* to fire and records *whether* it did; this dispatcher
decides *what* a fire does. Platform-specific behaviour (which executor runs
the enqueued task) stays in the task/executor layer, not here.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Dict, Optional
from uuid import UUID

from sqlalchemy import select

from app.db.models.workflow_runtime import WorkflowQueue, WorkflowScheduler
from app.services.scheduler.engine import JobDispatcher

logger = logging.getLogger(__name__)

# P2-R5 trace status for a fire that could not be enqueued because no queue
# resolved. The engine records the ExecutionLog with this status so operators
# scanning *non-success* logs see the dropped fire — a missing queue must
# never be a silent success.
DROPPED_STATUS = "dropped"
NO_QUEUE_REASON = "no-queue"


class QueueDispatcher(JobDispatcher):
    """Enqueue a fired schedule as a ``WorkflowTask`` on the workflow's queue.

    Queue resolution (first match wins):
      1. The scheduler's ``workflow_id`` -> the first live ``WorkflowQueue``
         whose ``workflow_id`` matches.
      2. Fallback -> a named default queue (``default_queue_name``,
         config-driven, env-overridable) for schedulers with no workflow, or
         whose workflow has no dedicated queue yet.
      3. No queue found -> a *soft no-op* when ``require_queue=False``: log a
         warning and report ``{"enqueued": False, "reason": "no-queue"}``
         without raising, so a schedule whose workflow has no queue yet still
         records a clean fire. With ``require_queue=True`` (the default
         engine's behaviour, P1-R1) a missing queue is a hard failure: the
         fire is marked ``failed`` and the schedule stalls — observable,
         never a silent success.

    P1-R2 recovery baseline: unless explicitly disabled, each enqueued task
    is stamped with the process-config defaults for ``max_retries`` and
    ``timeout_seconds`` (see :meth:`_baseline_defaults`), so a crashed or
    stuck execution of a timed workflow is swept to ``timeout`` and
    re-queued automatically instead of becoming an unrecoverable orphan.

    Each dispatch opens its OWN DB session (never the engine's transaction),
    matching the "one session per event" convention used by the CRM /
    conversation bridges so a queued fire can never corrupt the engine's
    bookkeeping transaction.
    """

    name = "queue"

    def __init__(
        self,
        default_queue_name: Optional[str] = None,
        require_queue: bool = False,
        session_factory: Optional[Callable] = None,
        default_max_retries: Optional[int] = None,
        default_timeout_seconds: Optional[int] = None,
    ):
        # A None default resolves to the process config at construction time so
        # get_scheduler_engine() can install config-driven behaviour while unit
        # tests can pin exact values (and opt out of importing app.config).
        if default_queue_name is None:
            from app.config import scheduler_default_queue_name
            default_queue_name = scheduler_default_queue_name()
        self.default_queue_name = default_queue_name
        self.require_queue = require_queue
        self._session_factory = session_factory
        # P1-R2 recovery baseline: when None these resolve to the config
        # defaults (scheduler_default_max_retries / _timeout_seconds) so a
        # scheduler-fired task is *retryable* and *timed* by default instead
        # of being an unrecoverable running orphan on crash.
        self._default_max_retries = default_max_retries
        self._default_timeout_seconds = default_timeout_seconds

    def _baseline_defaults(self):
        """Resolve the P1-R2 (max_retries, timeout_seconds) baseline.

        Explicit constructor values win; otherwise the process config defaults
        apply. Both may be ``None`` (operator opted out of the baseline).
        """
        from app import config as _config

        max_retries = (
            self._default_max_retries
            if self._default_max_retries is not None
            else _config.scheduler_default_max_retries()
        )
        timeout_seconds = (
            self._default_timeout_seconds
            if self._default_timeout_seconds is not None
            else _config.scheduler_default_timeout_seconds()
        )
        return max_retries, timeout_seconds

    async def _new_session(self):
        if self._session_factory is not None:
            return self._session_factory()
        from app.db.session import AsyncSessionLocal  # deferred: keeps import-time
        return AsyncSessionLocal()  # safe in unit tests that never dispatch

    async def dispatch(
        self,
        scheduler: WorkflowScheduler,
        fired_at: datetime,
        params: Dict,
    ) -> Optional[Dict]:
        """Enqueue a ``WorkflowTask`` for the fired schedule.

        Returns a JSON-safe result dict (stored as the execution log's
        ``output_result``): ``{"enqueued": True, "task_id", "queue_id"}`` on
        success, or ``{"enqueued": False, "reason": "no-queue"}`` when no
        queue is resolvable and ``require_queue`` is off. Raises ``LookupError``
        (fire marked failed) when ``require_queue`` is on and no queue exists.
        """
        from app.schemas.workflow_task import TaskCreate
        from app.services.workflow_task import QueueWorkerEngine

        db = await self._new_session()
        async with db:
            queue_id = await self._resolve_queue_id(db, scheduler)
            if queue_id is None:
                if self.require_queue:
                    raise LookupError(
                        f"no execution queue for scheduler {scheduler.id} "
                        f"(workflow_id={scheduler.workflow_id}); "
                        f"default queue {self.default_queue_name!r} not found"
                    )
                logger.warning(
                    "Scheduler %s fired but no queue resolved; soft no-op "
                    "(workflow_id=%s, default=%r)",
                    scheduler.id, scheduler.workflow_id, self.default_queue_name,
                )
                # P2-R5: carry the trace status so the engine records the fire
                # as *dropped*, not success (operators scanning failed/dropped
                # logs see it; a missing queue is never a silent success).
                return {
                    "enqueued": False,
                    "reason": NO_QUEUE_REASON,
                    "status": DROPPED_STATUS,
                }

            engine = QueueWorkerEngine(db)
            max_retries, timeout_seconds = self._baseline_defaults()
            task = await engine.enqueue(
                TaskCreate(
                    queue_id=queue_id,
                    workflow_id=scheduler.workflow_id,
                    name=f"sched-fire:{scheduler.name}",
                    payload={
                        "scheduler_id": str(scheduler.id),
                        "fired_at": fired_at.isoformat(),
                        "params": params or {},
                    },
                    metadata={
                        "origin": "scheduler",
                        "scheduler": str(scheduler.id),
                    },
                    max_retries=max_retries,
                    timeout_seconds=timeout_seconds,
                )
            )
            logger.info(
                "Enqueued scheduler task %s on queue %s for scheduler %s",
                task.id, queue_id, scheduler.id,
            )
            return {
                "enqueued": True,
                "task_id": str(task.id),
                "queue_id": str(queue_id),
            }

    async def _resolve_queue_id(
        self, db, scheduler: WorkflowScheduler
    ) -> Optional[UUID]:
        """First-match queue resolution (workflow-scoped queue, else default)."""
        if scheduler.workflow_id is not None:
            row = (
                await db.execute(
                    select(WorkflowQueue.id).where(
                        WorkflowQueue.workflow_id == scheduler.workflow_id,
                        WorkflowQueue.is_deleted == False,  # noqa: E712
                    )
                )
            ).first()
            if row is not None:
                return row[0]
        row = (
            await db.execute(
                select(WorkflowQueue.id).where(
                    WorkflowQueue.name == self.default_queue_name,
                    WorkflowQueue.is_deleted == False,  # noqa: E712
                )
            )
        ).first()
        return row[0] if row is not None else None
