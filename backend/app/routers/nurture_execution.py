"""Nurture Execution Log Router (P1 - t_a2ce2cae / ADR-010 follow-up).

Read + control endpoints for the NurturePlan execution engine:

- GET  /nurture/executions/plan/{plan_id}    per-plan execution history
- GET  /nurture/executions/plan/{plan_id}/progress   per-plan progress summary
- GET  /nurture/executions/dead-letters     operator dead-letter queue
- POST /nurture/executions/trigger           run a scheduler pass now (manual trigger)
- POST /nurture/executions/segment-sync      drive automatic/dynamic segment sync

Engine lifecycle (opt-in background tick loop, V1 single-node controlled
start/stop - mirrors the Phase 4 scheduler engine):
- POST /nurture/executions/engine/start      start the recurring tick loop
- POST /nurture/executions/engine/stop       stop it
- GET  /nurture/executions/engine/status     self-report

All under /api/v1. The heavy lifting is in the pure core + DB adapter
(``nurture_schedule`` / ``nurture_step_executor`` /
``nurture_scheduler_service``); this router only wires a DB session + the
engine loop.
"""
import os
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.nurture_scheduler_service import (
    get_plan_execution_progress,
    list_dead_letters,
    list_plan_executions,
    sync_due_segments,
)

router = APIRouter(prefix="/api/v1/nurture/executions", tags=["Nurture Execution"])

# ---------- background tick loop (module-level, single instance) ----------
# Mirrors the Phase 4 scheduler engine: explicitly started/stopped; an opt-in
# autostart at app boot is honoured via NURTURE_SCHEDULER_AUTOSTART=1 so the
# "no manual trigger" requirement is satisfiable without forcing a background
# worker on every deployment.
_nurture_engine_loop: Optional[object] = None


def _get_engine_loop():
    """Lazy, process-wide instance of the background tick loop (V1 single node).

    Constructed with no injected content provider: each pass builds a
    DBContentProvider on its own session (single-session invariant). The tick
    interval honours NURTURE_SCHEDULER_TICK_SECONDS (default 30s).
    """
    global _nurture_engine_loop
    if _nurture_engine_loop is None:
        from app.db.session import AsyncSessionLocal
        from app.services.nurture_scheduler_service import (
            NurtureScheduler,
            NurtureSchedulerLoop,
        )

        tick_s = float(os.environ.get("NURTURE_SCHEDULER_TICK_SECONDS", "30"))
        scheduler = NurtureScheduler(AsyncSessionLocal)
        _nurture_engine_loop = NurtureSchedulerLoop(scheduler, tick_seconds=tick_s)
    return _nurture_engine_loop


@router.get(
    "/plan/{plan_id}",
    summary="Per-plan step execution history",
)
async def plan_execution_history(
    plan_id: UUID,
    status: Optional[str] = Query(None, description="Filter by execution status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Return a plan's step-execution history (newest first), optionally filtered
    by status (success / failed / dead_letter / running / pending / skipped)."""
    return await list_plan_executions(
        db, plan_id, status=status, limit=limit, offset=offset
    )


@router.get(
    "/plan/{plan_id}/progress",
    summary="Per-plan execution progress",
)
async def plan_execution_progress(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """What has run / is pending / is stuck for a plan - counts by status plus
    the last activity timestamp (architecture review §2.3 'current progress')."""
    return await get_plan_execution_progress(db, plan_id)


@router.get(
    "/dead-letters",
    summary="Dead-lettered step executions",
)
async def dead_letters(
    account_id: Optional[UUID] = Query(None, description="Filter by account"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """The operator queue: steps that exhausted retries or hit a non-recoverable
    error (terminal ``dead_letter`` status), newest first."""
    return await list_dead_letters(db, account_id=account_id, limit=limit)


@router.post(
    "/trigger",
    summary="Run a scheduler pass now (manual trigger)",
)
async def trigger_pass(
    db: AsyncSession = Depends(get_db),
):
    """Fire one due-detection + execution pass synchronously so plans that are
    due run without waiting for the background tick (manual trigger entry the
    review asked for).

    No content provider is injected: the scheduler builds a
    :class:`DBContentProvider` on the *same* session it runs the pass on, so
    content generation, execution-log rows and any segment sync all commit in
    one transaction (single-session invariant).
    """
    from app.db.session import AsyncSessionLocal
    from app.services.nurture_scheduler_service import (
        NurtureScheduler,
    )

    scheduler = NurtureScheduler(AsyncSessionLocal)
    try:
        return await scheduler.run_pass()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Nurture pass failed: {exc}")


@router.post(
    "/segment-sync",
    summary="Drive automatic/dynamic segment member sync",
)
async def segment_sync(
    interval_hours: float = Query(6.0, ge=0.1, description="Sync interval threshold"),
    db: AsyncSession = Depends(get_db),
):
    """(TD-9) Sync member_count + last_synced_at for every automatic/dynamic
    segment that is due; returns per-segment sync stats."""
    try:
        return await sync_due_segments(db, interval_hours=interval_hours)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Segment sync failed: {exc}")


# ---------- engine lifecycle (background tick loop) ----------

@router.post(
    "/engine/start",
    summary="Start the background scheduler tick loop",
)
async def engine_start():
    """Start the recurring due-detection + execution tick loop. Idempotent: a
    second call while running is a no-op. V1 single-node, controlled start."""
    await _get_engine_loop().start()
    return {"started": True, **_get_engine_loop().status()}


@router.post(
    "/engine/stop",
    summary="Stop the background scheduler tick loop",
)
async def engine_stop():
    """Stop the tick loop, awaiting the in-flight pass. Idempotent."""
    await _get_engine_loop().stop()
    return {"stopped": True, **_get_engine_loop().status()}


@router.get(
    "/engine/status",
    summary="Background tick loop self-report",
)
async def engine_status():
    """Whether the loop is running, tick interval, last pass + counters."""
    return _get_engine_loop().status()
