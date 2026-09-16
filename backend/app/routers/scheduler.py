"""Scheduler Router (t_wf_003) - CRUD + control for time-based scheduling.

Endpoints (all under /api/v1/schedulers):
    POST   /                       create a scheduler
    GET    /                       list (filter + pagination)
    GET    /{scheduler_id}        fetch one
    PUT    /{scheduler_id}        update (recomputes next_run_at)
    DELETE /{scheduler_id}        soft delete + disable
    POST   /{scheduler_id}/trigger      manual fire now
    POST   /engine/start         start the tick loop (load persisted schedules)
    POST   /engine/stop          stop the tick loop
    GET    /engine/status        engine self-report (running, queue size, counters)

Business rule isolation: the router never executes scheduled work itself -
firing goes through SchedulerEngine + a pluggable JobDispatcher, mirroring
the BrowserProvider abstraction (business services depend on the
abstraction, not on one concrete executor).
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.scheduler import (
    SchedulerCreate,
    SchedulerUpdate,
    SchedulerResponse,
    SchedulerListResponse,
    SchedulerTriggerRequest,
    SchedulerTriggerResponse,
)
from app.services.scheduler import SchedulerService, SchedulerConfigError
from app.services.scheduler.engine import get_scheduler_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schedulers", tags=["Scheduler"])


def get_scheduler_service(db: AsyncSession = Depends(get_db)) -> SchedulerService:
    return SchedulerService(db)


# ========== CRUD ==========

@router.post("", response_model=SchedulerResponse, status_code=201)
async def create_scheduler(
    data: SchedulerCreate,
    service: SchedulerService = Depends(get_scheduler_service),
):
    """Create a scheduler; cron expressions are validated before persistence."""
    try:
        return await service.create(data)
    except SchedulerConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("", response_model=SchedulerListResponse)
async def list_schedulers(
    schedule_type: Optional[str] = Query(None, description="cron | interval"),
    enabled: Optional[bool] = Query(None, description="Filter by enabled flag"),
    workflow_id: Optional[UUID] = Query(None, description="Filter by workflow"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: SchedulerService = Depends(get_scheduler_service),
):
    """List schedulers with filtering and pagination (newest first)."""
    items, total = await service.list(
        schedule_type=schedule_type,
        enabled=enabled,
        workflow_id=workflow_id,
        page=page,
        page_size=page_size,
    )
    return SchedulerListResponse(
        items=items, total=total, page=page, page_size=page_size
    )


@router.get("/{scheduler_id}", response_model=SchedulerResponse)
async def get_scheduler(
    scheduler_id: UUID,
    service: SchedulerService = Depends(get_scheduler_service),
):
    """Fetch one scheduler (404 when missing or soft-deleted)."""
    resp = await service.get(scheduler_id)
    if resp is None:
        raise HTTPException(status_code=404, detail="Scheduler not found")
    return resp


@router.put("/{scheduler_id}", response_model=SchedulerResponse)
async def update_scheduler(
    scheduler_id: UUID,
    data: SchedulerUpdate,
    service: SchedulerService = Depends(get_scheduler_service),
):
    """Partial update; schedule-defining changes recompute next_run_at."""
    try:
        resp = await service.update(scheduler_id, data)
    except SchedulerConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if resp is None:
        raise HTTPException(status_code=404, detail="Scheduler not found")
    return resp


@router.delete("/{scheduler_id}", status_code=204)
async def delete_scheduler(
    scheduler_id: UUID,
    service: SchedulerService = Depends(get_scheduler_service),
):
    """Soft-delete + disable. 404 when the id is unknown."""
    deleted = await service.delete(scheduler_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Scheduler not found")
    return None


# ========== Control ==========

@router.post("/{scheduler_id}/trigger", response_model=SchedulerTriggerResponse)
async def trigger_scheduler_now(
    scheduler_id: UUID,
    data: Optional[SchedulerTriggerRequest] = SchedulerTriggerRequest(),
    service: SchedulerService = Depends(get_scheduler_service),
):
    """Manually fire a scheduler now, regardless of its schedule.

    The fire is dispatched through the engine's JobDispatcher and recorded
    as an ExecutionLog (execution_type='scheduler'). The regular cadence is
    preserved by re-arming next_run_at.
    """
    existing = await service.get(scheduler_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Scheduler not found")
    engine = get_scheduler_engine()
    ok = await engine.trigger_now(scheduler_id, (data or SchedulerTriggerRequest()).params)
    return SchedulerTriggerResponse(
        scheduler_id=scheduler_id,
        accepted=ok,
        fired_at=None,
        message=("scheduled" if ok else "fire rejected (missing/disabled/failed)"),
    )


@router.post("/engine/start", status_code=202)
async def start_scheduler_engine():
    """Start the tick loop and arm persisted schedules (idempotent)."""
    engine = get_scheduler_engine()
    await engine.start()
    armed = await engine.load_schedules()
    return {"running": engine.running, "armed_schedules": armed, **engine.status()}


@router.post("/engine/stop", status_code=202)
async def stop_scheduler_engine():
    """Stop the tick loop; pending fires stay in memory for the next start."""
    engine = get_scheduler_engine()
    await engine.stop()
    return {"running": engine.running, **engine.status()}


@router.get("/engine/status")
async def scheduler_engine_status():
    """Engine self-report: running state, queue depth, fire counters."""
    engine = get_scheduler_engine()
    return {**engine.status()}
