"""Scheduler Engine (t_wf_003) - in-process firing loop + job queue.

Single-node V1 design (distributed scheduling is explicitly out of scope):

- An in-memory min-heap queue of pending fires: ``(next_run_at, scheduler_id)``.
- A tick loop (default 200ms) pops due jobs and hands them to a
  **dispatcher** - the executor abstraction. The engine itself knows nothing
  about WHAT a scheduled job does; it only enforces *when* and records
  *whether* (ExecutionLog). Business services plug real executors in via
  ``JobDispatcher`` - mirroring the BrowserProvider abstraction rule.
- After each fire the scheduler row's ``last_run_at`` / ``next_run_at`` are
  recomputed and re-armed, so state stays observable in the DB.
- Start/stop control is exposed to the API layer through ``start()`` /
  ``stop()``; while stopped the queue keeps accepting arms (fires are
  simply dropped at pop-time if the scheduler was disabled in the meantime).

Accuracy: a fire is due when ``now >= next_run_at``; with a 200ms tick the
worst-case *late* error is ~200ms - well within the <1s acceptance bar.

Performance note (P2-R6, reliability review): within a single tick, due
fires are dispatched *serially* (``for pending in due: await _fire_one``),
and ``disarm`` rebuilds the heap in O(n). Both are accepted low-frequency
limits for V1: each fire is now exactly 2 commits (running + terminal,
batched — the old 3rd round-trip SELECT was removed in this change), so
a dense seconds-cron with many co-due jobs is the only scenario that
bound throughput. The documented remediation (parallel fire batches,
a per-tick batched terminal commit, O(log n) disarm via a lazy-remove
set) is tracked for a future wave; at the current single-node, low-rate
operating point the serial design is correct and simpler to reason about.
"""
import asyncio
import heapq
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Dict, List, Optional
from uuid import UUID

from app.db.session import AsyncSessionLocal
from app.db.models.workflow import ExecutionLog
from app.db.models.workflow_runtime import WorkflowScheduler
from sqlalchemy import select

from app.services.scheduler.schedule_calc import compute_next_fire, ScheduleConfigError

logger = logging.getLogger(__name__)


def _json_safe(value):
    """Coerce a dict to JSON-serializable form for JSONB storage (UUID/datetime -> str)."""
    from datetime import datetime as _dt
    from uuid import UUID as _UUID
    if not isinstance(value, dict):
        return value
    out = {}
    for k, v in value.items():
        if isinstance(v, _UUID):
            out[str(k)] = str(v)
        elif isinstance(v, _dt):
            out[str(k)] = v.isoformat()
        else:
            out[str(k)] = v
    return out


class JobDispatcher:
    """Execution abstraction: a fired schedule is handed here.

    Subclass to integrate real executors (workflow runner, queue enqueue,
    ...). The engine only cares about the return contract:
    ``dict`` output (stored as the execution log's output_result) or None.
    Raising an exception marks the fire as failed.
    """

    name: str = "noop"

    async def dispatch(
        self,
        scheduler: WorkflowScheduler,
        fired_at: datetime,
        params: Dict,
    ) -> Optional[Dict]:
        return None


class NoopDispatcher(JobDispatcher):
    """Records nothing - the scheduler fires and the engine logs success."""

    name = "noop"


@dataclass
class _PendingFire:
    next_run_at: datetime
    seq: int  # tie-breaker for equal times (heap determinism)
    scheduler_id: UUID

    def __lt__(self, other: "_PendingFire") -> bool:
        return (self.next_run_at, self.seq) < (other.next_run_at, other.seq)


class SchedulerEngine:
    """In-process scheduler: heap queue + tick loop + dispatcher."""

    def __init__(
        self,
        dispatcher: Optional[JobDispatcher] = None,
        tick_seconds: float = 0.2,
        session_factory: Optional[Callable] = None,
    ):
        self.dispatcher = dispatcher or NoopDispatcher()
        self.tick_seconds = tick_seconds
        self._session_factory = session_factory or (lambda: AsyncSessionLocal())
        self._heap: List[_PendingFire] = []
        self._seq = 0
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.started_at: Optional[datetime] = None
        self.stopped_at: Optional[datetime] = None
        self.fires_total = 0
        self.fires_failed = 0

    # ---------- state ----------

    @property
    def running(self) -> bool:
        return self._running

    def status(self) -> Dict:
        return {
            "running": self._running,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "pending_fires": len(self._heap),
            "fires_total": self.fires_total,
            "fires_failed": self.fires_failed,
            "dispatcher": self.dispatcher.name,
        }

    # ---------- control ----------

    async def start(self) -> None:
        """Start the tick loop (idempotent)."""
        async with self._lock:
            if self._running:
                return
            self._running = True
            self.started_at = datetime.now(timezone.utc)
            self.stopped_at = None
            self._task = asyncio.create_task(self._run(), name="scheduler-engine")
            logger.info("Scheduler engine started (tick=%.3fs)", self.tick_seconds)

    async def stop(self) -> None:
        """Stop the tick loop and drain the task (idempotent)."""
        async with self._lock:
            if not self._running:
                return
            self._running = False
            task, self._task = self._task, None
        if task is not None:
            await task
        self.stopped_at = datetime.now(timezone.utc)
        logger.info("Scheduler engine stopped")

    async def close(self) -> None:
        """Stop + guarantee no task leaks (call on app shutdown)."""
        await self.stop()

    # ---------- queue management ----------

    def arm(self, scheduler_id: UUID, next_run_at: datetime) -> None:
        """Enqueue a pending fire (callable from the tick loop or tests)."""
        self._seq += 1
        heapq.heappush(
            self._heap, _PendingFire(next_run_at, self._seq, scheduler_id)
        )

    def disarm(self, scheduler_id: UUID) -> int:
        """Remove every pending fire for ``scheduler_id`` from the heap.

        Called by the service layer after a schedule change / soft-delete so
        the in-memory heap and the DB row (next_run_at) cannot diverge
        (architecture review P1-3: two sources of truth). Returns how many
        pending fires were removed. Pure in-memory; safe when the loop is
        stopped (armed entries simply never pop).
        """
        kept = [p for p in self._heap if p.scheduler_id != scheduler_id]
        removed = len(self._heap) - len(kept)
        if removed:
            self._heap = kept
            heapq.heapify(self._heap)
        return removed

    async def load_schedules(self) -> int:
        """Arm every enabled scheduler whose next fire can be computed.

        Called on engine start so restarts pick up persisted schedules.
        Returns how many jobs were armed.
        """
        armed = 0
        db = self._session_factory()
        async with db:
            result = await db.execute(
                select(WorkflowScheduler).where(
                    WorkflowScheduler.enabled == True,  # noqa: E712
                    WorkflowScheduler.is_deleted == False,  # noqa: E712
                )
            )
            now = datetime.now(timezone.utc)
            for sched in result.scalars().all():
                try:
                    nxt = self._next_for(sched, now)
                except (ScheduleConfigError, ValueError):
                    logger.warning(
                        "Scheduler %s has an invalid schedule config; skipped",
                        sched.id,
                    )
                    continue
                if nxt is not None:
                    self.arm(sched.id, nxt)
                    armed += 1
        return armed

    async def repair_stalled_schedules(self) -> int:
        """Recompute + re-arm enabled schedulers that lost their ``next_run_at``
        (P2-R4: a stalled schedule must not stay stalled across a restart).

        ``_fire_one`` leaves a failed/dropped fire's row *un-armed* in the heap,
        and an invalid-config fire can null out ``next_run_at``. ``load_schedules``
        only arms rows whose ``next_run_at`` is already set, so a schedule that
        stalled (e.g. a temporarily broken cron expression later fixed, or a
        hard-failed fire) would remain silent after a restart. This method finds
        every enabled, not-deleted scheduler with ``next_run_at IS NULL``,
        recomputes its next fire, and — when the config is valid again — persists
        + arms it, logging an explicit warning so the recovery is observable.
        Schedulers whose config is still broken are left stalled and warned
        about (they need operator action, not a silent re-arm).

        Called at startup after :meth:`load_schedules` so restarts self-heal.
        Returns the number of schedules repaired (re-armed).
        """
        repaired = 0
        db = self._session_factory()
        async with db:
            result = await db.execute(
                select(WorkflowScheduler).where(
                    WorkflowScheduler.enabled == True,  # noqa: E712
                    WorkflowScheduler.is_deleted == False,  # noqa: E712
                    WorkflowScheduler.next_run_at.is_(None),
                )
            )
            now = datetime.now(timezone.utc)
            rows = list(result.scalars().all())
            for sched in rows:
                try:
                    nxt = self._next_for(sched, now)
                except (ScheduleConfigError, ValueError) as exc:
                    logger.warning(
                        "Stalled scheduler %s still has an invalid config (%s); "
                        "left un-armed until the config is fixed",
                        sched.id, exc,
                    )
                    continue
                if nxt is None:
                    logger.warning(
                        "Stalled scheduler %s has no computable next fire; "
                        "left un-armed",
                        sched.id,
                    )
                    continue
                sched.next_run_at = nxt
                sched.updated_at = datetime.now(timezone.utc)
                self.arm(sched.id, nxt)
                repaired += 1
                logger.warning(
                    "Repaired stalled scheduler %s: recomputed next_run_at=%s and "
                    "re-armed it (was enabled but had no next fire)",
                    sched.id, nxt.isoformat(),
                )
            if repaired:
                await db.commit()
        return repaired

    async def finalize_stale_execution_logs(self, staleness_seconds: float = 0.0) -> int:
        """Close out ``running`` scheduler ExecutionLogs lost to a crash (P2-R7).

        A fire persists two commits: (1) a ``running`` ExecutionLog, then (2)
        the terminal update. If the process dies between them, a stale
        ``running`` log survives. On restart the schedule refires from
        ``last_run`` (at-least-once is *intended*), so the stale row must be
        closed — not silently left — or operators scanning non-terminal logs
        see a run that never reached a terminal state. This method marks every
        scheduler ``running`` log older than ``staleness_seconds`` as ``timeout``
        with ``error_code="STALE_RUNNING"`` so the trace is complete and the
        refire is observable rather than a duplicate-with-no-explanation.

        ``staleness_seconds`` of ``0`` (the default at boot) closes every
        running scheduler log — correct for a single-node restart where the
        previous process is provably dead. Called at startup, best-effort.
        """
        from app.db.models.workflow import ExecutionLog

        finalized = 0
        db = self._session_factory()
        async with db:
            now = datetime.now(timezone.utc)
            result = await db.execute(
                select(ExecutionLog).where(
                    ExecutionLog.execution_type == "scheduler",
                    ExecutionLog.status == "running",
                    ExecutionLog.is_deleted == False,  # noqa: E712
                )
            )
            rows = list(result.scalars().all())
            for log in rows:
                base = log.started_at or log.created_at
                if base is not None and staleness_seconds > 0:
                    if (now - base).total_seconds() < staleness_seconds:
                        continue  # recent: a live sibling process may still own it
                log.status = "timeout"
                log.error_code = "STALE_RUNNING"
                log.error_message = (
                    "running scheduler execution log found at boot with no "
                    "terminal commit (process crash); closed out so the trace "
                    "stays complete"
                )
                log.finished_at = log.finished_at or now
                if log.duration_ms is None and base is not None:
                    log.duration_ms = (now - base).total_seconds() * 1000.0
                log.updated_at = now
                finalized += 1
                logger.warning(
                    "Finalized stale running scheduler ExecutionLog %s "
                    "(scheduler=%s) -> timeout",
                    log.id, log.metadata_.get("scheduler") if log.metadata_ else None,
                )
            if finalized:
                await db.commit()
        return finalized



    # ---------- firing ----------

    async def _run(self) -> None:
        while self._running:
            try:
                await self.tick()
            except Exception:
                logger.exception("Scheduler tick raised; loop continues")
            await asyncio.sleep(self.tick_seconds)

    async def tick(self) -> int:
        """One pop-and-fire pass. Returns how many jobs were fired.

        Jobs due by now are popped; after each fire the scheduler row is
        refreshed and re-armed (skipped when disabled or config-broken).
        """
        now = datetime.now(timezone.utc)
        due: List[_PendingFire] = []
        while self._heap and self._heap[0].next_run_at <= now:
            due.append(heapq.heappop(self._heap))
        fired = 0
        for pending in due:
            ok = await self._fire_one(pending.scheduler_id, now)
            fired += 1 if ok else 0
        return fired

    async def _fire_one(self, scheduler_id: UUID, now: datetime) -> bool:
        """Fire one job end-to-end. Returns True on success.

        Safe to call when the engine loop is not running (manual trigger).
        """
        factory = self._session_factory
        db = factory()
        try:
            async with db:
                result = await db.execute(
                    select(WorkflowScheduler).where(
                        WorkflowScheduler.id == scheduler_id,
                        WorkflowScheduler.is_deleted == False,  # noqa: E712
                    )
                )
                sched = result.scalar_one_or_none()
                if sched is None or not sched.enabled:
                    logger.debug("Fire dropped: scheduler %s missing/disabled", scheduler_id)
                    return False

                fired_at = datetime.now(timezone.utc)
                log = self._new_execution_log(sched, fired_at, status="running")
                db.add(log)
                await db.commit()

                try:
                    output = await self.dispatcher.dispatch(sched, fired_at, {})
                    status = "success"
                    err_msg = err_code = None
                except Exception as exc:  # dispatcher errors must not kill the loop
                    output = None
                    status = "failed"
                    err_msg = f"{type(exc).__name__}: {exc}"[:5000]
                    err_code = "E_DISPATCH"
                    self.fires_failed += 1
                    logger.exception("Scheduler %s dispatch failed", scheduler_id)

                # P2-R5: a dispatcher soft-drop (no queue resolvable) must
                # surface as a *non-success* ExecutionLog status ("dropped"),
                # never as success. The dispatcher carries the trace status in
                # the output result dict; only that field is honoured, so real
                # execution output is never misclassified.
                if status == "success" and isinstance(output, dict) and output.get("status") == "dropped":
                    status = "dropped"
                    err_code = "E_NO_QUEUE"
                    err_msg = (
                        f"no execution queue resolved for scheduler {scheduler_id}; "
                        f"fire dropped ({output.get('reason', 'no-queue')})"
                    )
                    self.fires_failed += 1
                    logger.warning("Scheduler %s fire dropped: no queue", scheduler_id)

                # P2-R6: persist terminal state + advance the schedule
                # bookkeeping in ONE commit. expire_on_commit=False (repo
                # session factory) keeps ``log`` usable after the first
                # commit, so the old post-commit re-fetch SELECT is gone and
                # a fire is exactly 2 commits instead of 3 round-trips.
                log.status = status
                log.output_result = _json_safe(output)
                log.error_message = err_msg
                log.error_code = err_code
                log.finished_at = datetime.now(timezone.utc)
                log.duration_ms = (log.finished_at - log.started_at).total_seconds() * 1000.0

                sched.last_run_at = fired_at
                try:
                    sched.next_run_at = self._next_for(sched, fired_at)
                except (ScheduleConfigError, ValueError) as exc:
                    logger.warning(
                        "Scheduler %s next-run computation failed: %s", sched.id, exc
                    )
                    sched.next_run_at = None
                sched.updated_at = datetime.now(timezone.utc)
                await db.commit()

                self.fires_total += 1
                logger.info(
                    "Fired scheduler %s (%s) at %s -> %s",
                    sched.id, sched.name, fired_at.isoformat(), status,
                )
                # Re-arm only on success; a failure/drop leaves the row with
                # the recomputed next_run_at but *un-armed* in the heap, so
                # operators see the stalled schedule in the DB and can
                # trigger_now / re-start it (P2-R4 repair re-arms on boot).
                if status == "success" and sched.next_run_at is not None:
                    self.arm(sched.id, sched.next_run_at)
                return status == "success"
        except Exception:
            logger.exception("Fire of scheduler %s raised unexpectedly", scheduler_id)
            try:
                await db.rollback()
            except Exception:
                logger.exception("Rollback after fire failure also raised")
            return False

    # ---------- manual trigger (start/stop API support) ----------

    async def trigger_now(self, scheduler_id: UUID, params: Optional[Dict] = None) -> bool:
        """Fire a scheduler immediately, outside the tick loop.

        Used by POST /schedulers/{id}/trigger. The schedule bookkeeping in
        _fire_one re-arms the next fire so the manual trigger does not
        break the cadence.
        """
        return await self._fire_one(scheduler_id, datetime.now(timezone.utc))

    # ---------- helpers ----------

    def _next_for(self, sched: WorkflowScheduler, now: datetime) -> Optional[datetime]:
        """Next fire strictly after ``now`` (strict; avoids instant refire)."""
        from datetime import timedelta
        if sched.schedule_type == "interval":
            return compute_next_fire(sched, now + timedelta(microseconds=1), now=now)
        return compute_next_fire(sched, now + timedelta(microseconds=1))

    @staticmethod
    def _new_execution_log(
        sched: WorkflowScheduler, fired_at: datetime, status: str = "running"
    ) -> ExecutionLog:
        trigger_type = "cron" if sched.schedule_type == "cron" else "scheduled"
        return ExecutionLog(
            execution_type="scheduler",
            trigger_type=trigger_type,
            status=status,
            workflow_id=sched.workflow_id,
            input_params={"scheduler_id": str(sched.id), "name": sched.name},
            started_at=fired_at,
            metadata_={"scheduler": str(sched.id)},
        )


# ---------- process-wide singleton ----------

_ENGINE: Optional[SchedulerEngine] = None


def get_scheduler_engine() -> SchedulerEngine:
    """Return the process-wide engine (lazily created).

    P1-2 (architecture review): the default dispatcher is now the real
    :class:`QueueDispatcher` — every fired schedule enqueues a ``WorkflowTask``
    onto the workflow's queue (t_wf_004), so time-triggered workflows are
    actually executed instead of the old record-only ``NoopDispatcher``. The
    default queue name and autostart behaviour come from config so a
    deployment can point the engine at a different queue or switch execution
    off.

    P1-R1 (reliability review): the dispatcher runs with
    ``require_queue=True`` so a missing default queue is a *hard, observable*
    failure (the fire is recorded ``failed`` and the schedule stalls) instead
    of a silent drop recorded as ``success``. Combined with the 027 seed
    migration (default queue ``workflow-scheduler`` always exists on a
    migrated DB) and the optional in-process consumer
    (``SCHEDULER_WORKER=1``, ``app.services.scheduler.consumer``), timed
    workflows are end-to-end executable in the default deployment.
    """
    global _ENGINE
    if _ENGINE is None:
        from app.config import scheduler_default_queue_name
        from app.services.scheduler.dispatcher import QueueDispatcher

        _ENGINE = SchedulerEngine(
            dispatcher=QueueDispatcher(
                default_queue_name=scheduler_default_queue_name(),
                require_queue=True,
            )
        )
    return _ENGINE


def reset_scheduler_engine() -> None:
    """Drop the process-wide singleton (test isolation / DI seams).

    ``SchedulerService`` reaches into :func:`get_scheduler_engine` to keep the
    in-memory heap in sync after a schedule change (architecture review P1-3),
    which pins it to the singleton. This helper lets unit tests install their
    own engine or start clean without leaking heap state across tests.
    """
    global _ENGINE
    _ENGINE = None
