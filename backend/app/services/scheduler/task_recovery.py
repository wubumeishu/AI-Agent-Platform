"""Periodic WorkflowTask recovery loop (reliability review P1-R2).

A living process still needs a running sweep to catch tasks that exceed their
timeout (a hung executor, an external worker that stopped heart-beating). The
crash-recovery pass in ``main.py`` only runs at boot, so this loop drives
``sweep_and_retry`` (sweep expired running tasks -> re-queue the retryable
ones) on a fixed interval, making the default deployment *recoverable while
running* instead of only after a restart.

Design notes
------------
- One session per tick (repo convention): the loop opens its own
  ``AsyncSessionLocal`` so a slow sweep can never hold an HTTP request's
  transaction open.
- The interval comes from ``config.task_sweep_interval_seconds`` (default
  30s). ``start`` is idempotent; a second call with the same loop is a no-op.
- ``stop`` cancels the background task cleanly so app shutdown never leaks a
  running loop.
- Errors are logged, never raised: a transient DB hiccup must not kill the
  recovery loop — it simply retries on the next tick.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TaskRecoveryLoop:
    """Background loop that periodically sweeps + re-queues workflow tasks."""

    def __init__(self, session_factory=None):
        if session_factory is None:
            from app.db.session import AsyncSessionLocal
            session_factory = (lambda: AsyncSessionLocal())
        self._session_factory = session_factory
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._interval = 30.0
        self._last_summary: dict = {}
        self.ticks = 0

    @property
    def running(self) -> bool:
        return self._running

    def status(self) -> dict:
        return {
            "running": self._running,
            "interval_seconds": self._interval,
            "ticks": self.ticks,
            "last_summary": dict(self._last_summary),
        }

    async def start(self, interval_seconds: float = 30.0) -> None:
        """Start the loop (idempotent)."""
        if self._running:
            return
        self._interval = interval_seconds
        self._running = True
        self._task = asyncio.create_task(self._run(), name="task-recovery-loop")
        logger.info("Task recovery loop started (every %.1fs)", interval_seconds)

    async def stop(self) -> None:
        """Stop the loop and drain its task (idempotent)."""
        if not self._running:
            return
        self._running = False
        task, self._task = self._task, None
        if task is not None:
            await task
        logger.info("Task recovery loop stopped (ticks=%s)", self.ticks)

    async def close(self) -> None:
        await self.stop()

    async def _run(self) -> None:
        while self._running:
            try:
                await self.sweep_once()
            except Exception:
                logger.exception("Task recovery tick raised; loop continues")
            await asyncio.sleep(self._interval)

    async def sweep_once(self) -> dict:
        """One sweep + retry pass. Returns the recovery summary."""
        from app.services.workflow_task import QueueWorkerEngine

        db = self._session_factory()
        try:
            async with db:
                engine = QueueWorkerEngine(db)
                summary = await engine.sweep_and_retry()
                self._last_summary = summary
                self.ticks += 1
        finally:
            # close() is implicit in the context manager exit.
            pass
        return summary


# ---------- process-wide singleton ----------

_LOOP: Optional[TaskRecoveryLoop] = None


def get_task_recovery_loop() -> TaskRecoveryLoop:
    """Return the process-wide recovery loop (lazily created, idempotent)."""
    global _LOOP
    if _LOOP is None:
        _LOOP = TaskRecoveryLoop()
    return _LOOP


def reset_task_recovery_loop() -> None:
    """Drop the singleton (test isolation / DI seam)."""
    global _LOOP
    _LOOP = None
