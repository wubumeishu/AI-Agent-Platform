"""Workflow framework CRUD router (Phase 4 / t_wf_001 - scaffold layer).

REST CRUD surface for the full workflow subsystem. No execution engine, cron
evaluation, or cross-module integration here — those are later waves
(t_wf_003/t_wf_004/t_wf_006/t_wf_007). This card delivers the *skeleton*:
create / read / list (filtered + sorted + paginated) / update / soft-delete
for every entity, with auto-generated OpenAPI docs.

Endpoints (all under /api/v1):

    /workflows               CRUD for Workflow
    /workflow-triggers       CRUD for Trigger
    /workflow-conditions     CRUD for Condition
    /workflow-actions        CRUD for Action
    /workflow-delays         CRUD for Delay
    /workflow-branches       CRUD for Branch
    /workflow-schedulers     CRUD for Scheduler
    /workflow-queues         CRUD for Queue
    /workflow-workers        CRUD for Worker
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas import workflow_framework as wf
from app.services.workflow_framework import (
    ConflictError,
    WorkflowBranchService,
    WorkflowDelayService,
    WorkflowQueueService,
    WorkflowSchedulerService,
    WorkflowWorkerService,
)


async def _guard_conflict(coro):
    """t_a986f957: map a uniqueness ConflictError to HTTP 409 instead of 500.

    FastAPI 0.141 APIRouter does not support ``exception_handlers``, so the
    domain exception is mapped at each create/update call site.
    """
    try:
        return await coro
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))


# NOTE: no "/api/v1" prefix here — main.py mounts this router under
# prefix="/api/v1" (matching the platform/accounts convention). The
# decorator paths below are the resource-level paths.
router = APIRouter(tags=["Workflow Framework"])


# ---------- service factories (DI) ----------
def _svc_workflows(db: AsyncSession = Depends(get_db)):
    return WorkflowService(db)


def _svc_triggers(db: AsyncSession = Depends(get_db)):
    return WorkflowTriggerService(db)


def _svc_conditions(db: AsyncSession = Depends(get_db)):
    return WorkflowConditionService(db)


def _svc_actions(db: AsyncSession = Depends(get_db)):
    return WorkflowActionService(db)


def _svc_delays(db: AsyncSession = Depends(get_db)):
    return WorkflowDelayService(db)


def _svc_branches(db: AsyncSession = Depends(get_db)):
    return WorkflowBranchService(db)


def _svc_schedulers(db: AsyncSession = Depends(get_db)):
    return WorkflowSchedulerService(db)


def _svc_queues(db: AsyncSession = Depends(get_db)):
    return WorkflowQueueService(db)


def _svc_workers(db: AsyncSession = Depends(get_db)):
    return WorkflowWorkerService(db)


# =====================================================================
# WORKFLOW
# =====================================================================
# NOTE (architecture review P1-1, t_c94bba06): the flat CRUD for the 4
# configuration entities (Workflow / Trigger / Condition / Action) LIVES in
# the nested ``workflow_config`` router — it is the single canonical
# /workflows API surface. This router previously re-declared them and,
# because ``workflow_config`` is registered first in main.py, its copies were
# silently shadowed (duplicate OpenAPI operation ids). Those blocks are
# removed; only the runtime entities below remain.

# =====================================================================
# DELAY
# =====================================================================

@router.get("/workflow-delays", response_model=wf.DelayListResponse)
async def list_delays(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    workflow_id: Optional[UUID] = Query(None),
    unit: Optional[str] = Query(None),
    order_by: Optional[str] = Query(None),
    ascending: bool = Query(False),
    service: WorkflowDelayService = Depends(_svc_delays),
):
    items, total = await service.list(
        page, page_size, order_by, ascending, workflow_id=workflow_id, unit=unit
    )
    return wf.DelayListResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("/workflow-delays", response_model=wf.DelayResponse, status_code=201)
async def create_delay(
    data: wf.DelayCreate,
    service: WorkflowDelayService = Depends(_svc_delays),
):
    return await _guard_conflict(service.create(data))


@router.get("/workflow-delays/{instance_id}", response_model=wf.DelayResponse)
async def get_delay(
    instance_id: UUID,
    service: WorkflowDelayService = Depends(_svc_delays),
):
    obj = await service.get(instance_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Delay not found")
    return obj


@router.put("/workflow-delays/{instance_id}", response_model=wf.DelayResponse)
async def update_delay(
    instance_id: UUID,
    data: wf.DelayUpdate,
    service: WorkflowDelayService = Depends(_svc_delays),
):
    obj = await _guard_conflict(service.update(instance_id, data))
    if obj is None:
        raise HTTPException(status_code=404, detail="Delay not found")
    return obj


@router.delete("/workflow-delays/{instance_id}", status_code=204)
async def delete_delay(
    instance_id: UUID,
    service: WorkflowDelayService = Depends(_svc_delays),
):
    if not await service.delete(instance_id):
        raise HTTPException(status_code=404, detail="Delay not found")
    return None


# =====================================================================
# BRANCH
# =====================================================================

@router.get("/workflow-branches", response_model=wf.BranchListResponse)
async def list_branches(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    workflow_id: Optional[UUID] = Query(None),
    order_by: Optional[str] = Query(None),
    ascending: bool = Query(False),
    service: WorkflowBranchService = Depends(_svc_branches),
):
    items, total = await service.list(
        page, page_size, order_by, ascending, workflow_id=workflow_id
    )
    return wf.BranchListResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("/workflow-branches", response_model=wf.BranchResponse, status_code=201)
async def create_branch(
    data: wf.BranchCreate,
    service: WorkflowBranchService = Depends(_svc_branches),
):
    return await _guard_conflict(service.create(data))


@router.get("/workflow-branches/{instance_id}", response_model=wf.BranchResponse)
async def get_branch(
    instance_id: UUID,
    service: WorkflowBranchService = Depends(_svc_branches),
):
    obj = await service.get(instance_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    return obj


@router.put("/workflow-branches/{instance_id}", response_model=wf.BranchResponse)
async def update_branch(
    instance_id: UUID,
    data: wf.BranchUpdate,
    service: WorkflowBranchService = Depends(_svc_branches),
):
    obj = await _guard_conflict(service.update(instance_id, data))
    if obj is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    return obj


@router.delete("/workflow-branches/{instance_id}", status_code=204)
async def delete_branch(
    instance_id: UUID,
    service: WorkflowBranchService = Depends(_svc_branches),
):
    if not await service.delete(instance_id):
        raise HTTPException(status_code=404, detail="Branch not found")
    return None


# =====================================================================
# SCHEDULER
# =====================================================================

@router.get("/workflow-schedulers", response_model=wf.SchedulerListResponse)
async def list_schedulers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    workflow_id: Optional[UUID] = Query(None),
    schedule_type: Optional[str] = Query(None, alias="type"),
    enabled: Optional[bool] = Query(None),
    order_by: Optional[str] = Query(None),
    ascending: bool = Query(False),
    service: WorkflowSchedulerService = Depends(_svc_schedulers),
):
    items, total = await service.list(
        page, page_size, order_by, ascending,
        workflow_id=workflow_id, schedule_type=schedule_type, enabled=enabled,
    )
    return wf.SchedulerListResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("/workflow-schedulers", response_model=wf.SchedulerResponse, status_code=201)
async def create_scheduler(
    data: wf.SchedulerCreate,
    service: WorkflowSchedulerService = Depends(_svc_schedulers),
):
    return await _guard_conflict(service.create(data))


@router.get("/workflow-schedulers/{instance_id}", response_model=wf.SchedulerResponse)
async def get_scheduler(
    instance_id: UUID,
    service: WorkflowSchedulerService = Depends(_svc_schedulers),
):
    obj = await service.get(instance_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Scheduler not found")
    return obj


@router.put("/workflow-schedulers/{instance_id}", response_model=wf.SchedulerResponse)
async def update_scheduler(
    instance_id: UUID,
    data: wf.SchedulerUpdate,
    service: WorkflowSchedulerService = Depends(_svc_schedulers),
):
    obj = await _guard_conflict(service.update(instance_id, data))
    if obj is None:
        raise HTTPException(status_code=404, detail="Scheduler not found")
    return obj


@router.delete("/workflow-schedulers/{instance_id}", status_code=204)
async def delete_scheduler(
    instance_id: UUID,
    service: WorkflowSchedulerService = Depends(_svc_schedulers),
):
    if not await service.delete(instance_id):
        raise HTTPException(status_code=404, detail="Scheduler not found")
    return None


# =====================================================================
# QUEUE
# =====================================================================

@router.get("/workflow-queues", response_model=wf.QueueListResponse)
async def list_queues(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    workflow_id: Optional[UUID] = Query(None),
    type_: Optional[str] = Query(None, alias="type"),
    status: Optional[str] = Query(None),
    order_by: Optional[str] = Query(None),
    ascending: bool = Query(False),
    service: WorkflowQueueService = Depends(_svc_queues),
):
    items, total = await service.list(
        page, page_size, order_by, ascending,
        workflow_id=workflow_id, type_=type_, status=status,
    )
    return wf.QueueListResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("/workflow-queues", response_model=wf.QueueResponse, status_code=201)
async def create_queue(
    data: wf.QueueCreate,
    service: WorkflowQueueService = Depends(_svc_queues),
):
    return await _guard_conflict(service.create(data))


@router.get("/workflow-queues/{instance_id}", response_model=wf.QueueResponse)
async def get_queue(
    instance_id: UUID,
    service: WorkflowQueueService = Depends(_svc_queues),
):
    obj = await service.get(instance_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Queue not found")
    return obj


@router.put("/workflow-queues/{instance_id}", response_model=wf.QueueResponse)
async def update_queue(
    instance_id: UUID,
    data: wf.QueueUpdate,
    service: WorkflowQueueService = Depends(_svc_queues),
):
    obj = await _guard_conflict(service.update(instance_id, data))
    if obj is None:
        raise HTTPException(status_code=404, detail="Queue not found")
    return obj


@router.delete("/workflow-queues/{instance_id}", status_code=204)
async def delete_queue(
    instance_id: UUID,
    service: WorkflowQueueService = Depends(_svc_queues),
):
    if not await service.delete(instance_id):
        raise HTTPException(status_code=404, detail="Queue not found")
    return None


# =====================================================================
# WORKER
# =====================================================================

@router.get("/workflow-workers", response_model=wf.WorkerListResponse)
async def list_workers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    queue_id: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None),
    order_by: Optional[str] = Query(None),
    ascending: bool = Query(False),
    service: WorkflowWorkerService = Depends(_svc_workers),
):
    items, total = await service.list(
        page, page_size, order_by, ascending, queue_id=queue_id, status=status
    )
    return wf.WorkerListResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("/workflow-workers", response_model=wf.WorkerResponse, status_code=201)
async def create_worker(
    data: wf.WorkerCreate,
    service: WorkflowWorkerService = Depends(_svc_workers),
):
    return await _guard_conflict(service.create(data))


@router.get("/workflow-workers/{instance_id}", response_model=wf.WorkerResponse)
async def get_worker(
    instance_id: UUID,
    service: WorkflowWorkerService = Depends(_svc_workers),
):
    obj = await service.get(instance_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    return obj


@router.put("/workflow-workers/{instance_id}", response_model=wf.WorkerResponse)
async def update_worker(
    instance_id: UUID,
    data: wf.WorkerUpdate,
    service: WorkflowWorkerService = Depends(_svc_workers),
):
    obj = await _guard_conflict(service.update(instance_id, data))
    if obj is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    return obj


@router.delete("/workflow-workers/{instance_id}", status_code=204)
async def delete_worker(
    instance_id: UUID,
    service: WorkflowWorkerService = Depends(_svc_workers),
):
    if not await service.delete(instance_id):
        raise HTTPException(status_code=404, detail="Worker not found")
    return None
