"""In-process scheduler task consumer (reliability review P1-R1).

The scheduler engine only *enqueues* fired schedules as ``WorkflowTask`` rows
(P1-2). This module closes the loop: an opt-in background worker claims tasks
from the scheduler's queue and executes them, so a timed workflow actually
runs in the default deployment instead of sitting in the queue forever.

Design (mirrors the pluggable-executor rule the engine already follows):

- The consumer is a plain claim->execute poll loop over ``WorkflowQueue``
  rows; it opens its own DB session per poll (repo convention) so a slow
  executor can never hold a request transaction open.
- Executor selection is pluggable. The default :class:`SchedulerTaskExecutor`
  routes scheduler-origin tasks that carry a ``workflow_id`` to the
  :class:`WorkflowConversationBridge.run_scheduled` action graph (the same
  business logic the event path uses), and falls back to the side-effect-free
  :class:`EchoExecutor` for everything else. A deployment that wants a real
  platform integration (browser / AI provider) supplies its own
  :class:`~app.services.workflow_task.Executor` — the consumer never
  hard-codes one provider.
- Opt-in by ``SCHEDULER_WORKER=1`` (``config.scheduler_worker_enabled``):
  deployments that run a *dedicated external worker* on the same queue keep
  the consumer off so a task is not executed twice.

Startup crash-recovery and the periodic timeout sweep are owned by
``main.py`` / :mod:`app.services.workflow_task` (P1-R2), not here: the
consumer only *consumes*; recovery is orthogonal and must run even when the
consumer is off.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.db.models.workflow_runtime import WorkflowQueue, WorkflowWorker
from app.db.session import AsyncSessionLocal
from app.services.workflow_task import EchoExecutor, QueueWorkerEngine

logger = logging.getLogger(__name__)


class SchedulerTaskExecutor:
    """Default consumer executor: real action graph for scheduler tasks.

    A task whose ``metadata`` marks it scheduler-origin (the
    ``QueueDispatcher`` stamps ``{"origin": "scheduler"}``) and that carries
    a ``workflow_id`` is run through the conversation bridge's scheduled
    action graph (:meth:`WorkflowConversationBridge.run_scheduled`). The
    bridge summary is a JSON-safe dict, so it lands directly on the task's
    ``result`` column. Tasks without a workflow (or produced by anything else
    enqueued onto a shared queue) get the deterministic :class:`EchoExecutor`
    — the consumer never invents side effects.
    """

    name = "scheduler-task"

    async def run(self, payload: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        workflow_id = context.get("workflow_id")
        metadata = context.get("task_metadata") or {}
        if workflow_id and metadata.get("origin") == "scheduler":
            # Deferred import: keeps the consumer module importable without
            # the full app wiring (unit tests may exercise the routing first).
            from app.services.workflow_conversation_bridge import (
                WorkflowConversationBridge,
            )
            from app.db.session import AsyncSessionLocal as _ASL

            wf_uuid = UUID(str(workflow_id))
            async with _ASL() as db:
                bridge = WorkflowConversationBridge(db)
                params = dict(payload.get("params") or {})
                result = await bridge.run_scheduled(wf_uuid, params=params)
            return {
                "executor": self.name,
                "scheduler_run": result,
                "params": params,
            }
        echo = EchoExecutor()
        out = await echo.run(payload, context)
        out["executor"] = self.name
        return out


class SchedulerConsumer:
    """Polling claim->execute worker for one or more named workflow queues.

    The consumer resolves the *live* queue rows (by name) at start and after
    every failed poll, so a queue created later (or a renamed default) is
    picked up without a restart. It stops cleanly via :meth:`stop` and is
    safe to start/stop repeatedly (idempotent, single background task).
    """

    def __init__(
        self,
        queue_names: Optional[List[str]] = None,
        poll_seconds: float = 1.0,
        executor: Optional[Any] = None,
        session_factory: Optional[Any] = None,
        worker_name: str = "in-process-scheduler-worker",
    ):
        if queue_names is None:
            from app.config import scheduler_default_queue_name
            queue_names = [scheduler_default_queue_name()]
        self.queue_names = list(queue_names)
        self.poll_seconds = poll_seconds
        self.executor = executor or SchedulerTaskExecutor()
        self._session_factory = session_factory or (lambda: AsyncSessionLocal())
        self._worker_name = worker_name
        self._worker_id: Optional[UUID] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.processed = 0
        self.failed = 0

    # ---------- control ----------

    @property
    def running(self) -> bool:
        return self._running

    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "worker_id": str(self._worker_id) if self._worker_id else None,
            "queues": list(self.queue_names),
            "executor": getattr(self.executor, "name", repr(self.executor)),
            "processed": self.processed,
            "failed": self.failed,
            "poll_seconds": self.poll_seconds,
        }

    async def start(self) -> None:
        """Start the background poll loop (idempotent)."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="scheduler-consumer")
        logger.info(
            "Scheduler consumer started (queues=%s, poll=%.2fs, executor=%s)",
            self.queue_names, self.poll_seconds, self.status()["executor"],
        )

    async def stop(self) -> None:
        """Stop the poll loop and drain the task (idempotent)."""
        if not self._running:
            return
        self._running = False
        task, self._task = self._task, None
        if task is not None:
            await task
        logger.info("Scheduler consumer stopped (processed=%s, failed=%s)",
                    self.processed, self.failed)

    async def close(self) -> None:
        await self.stop()

    # ---------- internals ----------

    async def _register_worker(self, db) -> Optional[UUID]:
        """Create (idempotently) the WorkflowWorker row that owns claims.

        Recording a real worker row makes claims attributable in the DB —
        operators can see *who* consumed the scheduler queue, and a future
        crash-recovery pass can distinguish a dead worker's claims from a
        live one's. Best-effort: when the table/DB is unavailable the claim
        still works with a NULL worker_id.
        """
        from sqlalchemy import select

        res = await db.execute(
            select(WorkflowWorker).where(
                WorkflowWorker.name == self._worker_name,
                WorkflowWorker.is_deleted == False,  # noqa: E712
            )
        )
        row = res.scalar_one_or_none()
        if row is not None:
            if row.status != "stopped":
                row.status = "busy"
                await db.commit()
            return row.id
        row = WorkflowWorker(name=self._worker_name, status="busy")
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id

    async def _poll_once(self) -> int:
        """One claim->execute pass over all configured queues.

        Returns how many tasks were executed this pass. Never raises: a
        transient DB hiccup is logged and retried on the next poll.
        """
        from sqlalchemy import select

        db = self._session_factory()
        executed = 0
        try:
            async with db:
                if self._worker_id is None:
                    try:
                        self._worker_id = await self._register_worker(db)
                    except Exception:
                        logger.exception(
                            "Worker row registration failed; claims proceed "
                            "unattributed (worker_id stays NULL)"
                        )
                        self._worker_id = None

                qrows = (
                    await db.execute(
                        select(WorkflowQueue).where(
                            WorkflowQueue.name.in_(self.queue_names),
                            WorkflowQueue.is_deleted == False,  # noqa: E712
                        )
                    )
                ).scalars().all()
                for queue in qrows:
                    engine = QueueWorkerEngine(db)
                    while True:
                        claimed = await engine.claim_next(
                            queue.id, worker_id=self._worker_id
                        )
                        if claimed is None:
                            break
                        # execute_task runs the executor, records the terminal
                        # state (success/failed) on the row, and re-raises
                        # nothing — a failed executor is already a persisted
                        # failed task, picked up later by the P1-R2 sweep+retry.
                        result = await engine.execute_task(
                            claimed,
                            executor=self._executor_for(claimed),
                            context={
                                "task_metadata": claimed.metadata or {},
                            },
                        )
                        executed += 1
                        if result.status == "success":
                            self.processed += 1
                        else:
                            self.failed += 1
                            logger.warning(
                                "Consumer execution failed for task %s on queue %s "
                                "(will be retried by the P1-R2 sweep): %s",
                                result.task_id, queue.name, result.error_message,
                            )
        except Exception:
            # A down DB / transient error must not kill the worker loop.
            logger.exception("Scheduler consumer poll failed; retrying next tick")
            try:
                await db.rollback()
            except Exception:
                pass
        finally:
            if self._worker_id is not None:
                await self._mark_worker_idle()
        return executed

    def _executor_for(self, claimed) -> Any:
        """Route a claimed task to the right executor.

        The consumer's single executor handles the routing internally (see
        :class:`SchedulerTaskExecutor`), so a custom executor supplied by the
        deployment is used verbatim.
        """
        return self.executor

    async def _mark_worker_idle(self) -> None:
        """Best-effort idle stamp + heartbeat on the worker row.

        Runs inside the async worker loop, so it awaits a fresh session
        directly (a nested ``run_until_complete`` would deadlock the running
        loop). Observability-only: any failure is swallowed.
        """
        if self._worker_id is None:
            return
        try:
            from datetime import datetime, timezone
            from sqlalchemy import select

            db = self._session_factory()
            async with db:
                res = await db.execute(
                    select(WorkflowWorker).where(
                        WorkflowWorker.id == self._worker_id,
                        WorkflowWorker.is_deleted == False,  # noqa: E712
                    )
                )
                row = res.scalar_one_or_none()
                if row is not None and row.status != "stopped":
                    row.status = "idle"
                    row.last_heartbeat_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception:
            # Idle stamp is observability-only; never let it break the loop.
            logger.debug("Failed to stamp worker idle (non-fatal)", exc_info=True)

    async def _run(self) -> None:
        while self._running:
            try:
                await self._poll_once()
            except Exception:
                logger.exception("Scheduler consumer loop iteration raised")
            await asyncio.sleep(self.poll_seconds)
