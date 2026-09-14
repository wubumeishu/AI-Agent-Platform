"""Execution Log Router - record, query, and clean up workflow executions.

Endpoints (all under /api/v1/execution-logs):
    POST   /                     create a log record
    GET    /                     list logs (filter + pagination)
    POST   /history              execution-history query (body filters)
    GET    /failed               recent failed/timeout executions
    POST   /cleanup              run the retention cleanup policy
    GET    /{log_id}            fetch one log
    PUT    /{log_id}            update a log (progress / terminal state)
    GET    /health               service self-report
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.workflow import (
    ExecutionLogCreate,
    ExecutionLogUpdate,
    ExecutionLogResponse,
    ExecutionLogListResponse,
    ExecutionHistoryRequest,
    ExecutionLogCleanupRequest,
    ExecutionLogCleanupResponse,
)
from app.services.workflow import ExecutionLogService

router = APIRouter(prefix="/execution-logs", tags=["Execution Log"])


def get_execution_log_service(
    db: AsyncSession = Depends(get_db),
) -> ExecutionLogService:
    """Dependency for ExecutionLogService."""
    return ExecutionLogService(db)


# ========== Create / Read ==========

@router.post("", response_model=ExecutionLogResponse, status_code=201)
async def create_execution_log(
    data: ExecutionLogCreate,
    service: ExecutionLogService = Depends(get_execution_log_service),
):
    """Record a new execution log (typically at execution start)."""
    return await service.create_log(data)


@router.get("", response_model=ExecutionLogListResponse)
async def list_execution_logs(
    execution_type: Optional[str] = Query(None, description="Filter by execution type"),
    trigger_type: Optional[str] = Query(None, description="Filter by trigger type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    workflow_id: Optional[UUID] = Query(None, description="Filter by workflow"),
    queue_id: Optional[UUID] = Query(None, description="Filter by queue"),
    worker_id: Optional[UUID] = Query(None, description="Filter by worker"),
    task_id: Optional[UUID] = Query(None, description="Filter by task"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    service: ExecutionLogService = Depends(get_execution_log_service),
):
    """List execution logs with filtering and pagination."""
    items, total = await service.list_logs(
        execution_type=execution_type,
        trigger_type=trigger_type,
        status=status,
        workflow_id=workflow_id,
        queue_id=queue_id,
        worker_id=worker_id,
        task_id=task_id,
        page=page,
        page_size=page_size,
    )
    return ExecutionLogListResponse(
        items=items, total=total, page=page, page_size=page_size
    )


# ========== Execution history (body filters) ==========

@router.post("/history", response_model=ExecutionLogListResponse)
async def get_execution_history(
    request: ExecutionHistoryRequest,
    service: ExecutionLogService = Depends(get_execution_log_service),
):
    """Query execution history with rich filters (time window, ids, status)."""
    items, total = await service.get_history(request)
    return ExecutionLogListResponse(
        items=items, total=total, page=request.page, page_size=request.page_size
    )


@router.get("/failed", response_model=ExecutionLogListResponse)
async def get_failed_executions(
    limit: int = Query(100, ge=1, le=500, description="Max records to return"),
    service: ExecutionLogService = Depends(get_execution_log_service),
):
    """Recent failed / timeout executions for troubleshooting."""
    items = await service.get_failed_executions(limit=limit)
    return ExecutionLogListResponse(
        items=items, total=len(items), page=1, page_size=limit
    )


# ========== Cleanup policy ==========

@router.post("/cleanup", response_model=ExecutionLogCleanupResponse)
async def clean_execution_logs(
    data: ExecutionLogCleanupRequest,
    service: ExecutionLogService = Depends(get_execution_log_service),
):
    """Run the retention policy: keep only the most recent N logs."""
    return await service.clean_logs(data)


# ========== Single log ==========
# NOTE: the literal-path routes above (/failed, /health) are defined before
# this parameterised route so they are not swallowed by /{log_id}.

@router.get("/health")
async def health_check(
    service: ExecutionLogService = Depends(get_execution_log_service),
):
    """Service self-report."""
    return service.health()


@router.get("/{log_id}", response_model=ExecutionLogResponse)
async def get_execution_log(
    log_id: UUID,
    service: ExecutionLogService = Depends(get_execution_log_service),
):
    """Fetch a single execution log by ID."""
    log = await service.get_log(log_id)
    if log is None:
        raise HTTPException(status_code=404, detail="Execution log not found")
    return log


@router.put("/{log_id}", response_model=ExecutionLogResponse)
async def update_execution_log(
    log_id: UUID,
    data: ExecutionLogUpdate,
    service: ExecutionLogService = Depends(get_execution_log_service),
):
    """Update an execution log (progress, terminal state, error)."""
    log = await service.update_log(log_id, data)
    if log is None:
        raise HTTPException(status_code=404, detail="Execution log not found")
    return log
