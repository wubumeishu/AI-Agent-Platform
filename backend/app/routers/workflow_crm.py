"""Workflow-CRM integration API (t_4f31af5e).

Endpoints (all under /api/v1/workflow-crm):

    POST /trigger            manually run active workflows against a CRM event
    POST /dispatch-now       flush queued domain events through the executor
    GET  /health             subscriber + active-workflow self-report

Design:
- ``/trigger`` is the *manual* path: it does not depend on the in-process
  bus. It builds a DomainEvent from the request and runs the executor in the
  request's DB session, so a single HTTP call drives a full
  match -> condition -> action -> ExecutionLog cycle.
- ``/dispatch-now`` flushes any events queued by the CRM services since the
  last dispatch (useful when the app-level autoflush hook is disabled or for
  integration testing).
- The app-level autoflush (request-scoped) is wired in main.py so normal
  CRM mutations already fire workflows without a manual call.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models.workflow import Workflow
from app.events.domain_events import DomainEvent, get_event_bus
from app.schemas.workflow_crm import (
    WorkflowCrmTriggerRequest,
    WorkflowCrmTriggerResponse,
    WorkflowCrmHealthResponse,
)
from app.services.workflow_crm import (
    WorkflowCrmExecutor,
    register_workflow_crm_subscriber,
    _is_subscribed,
)

router = APIRouter(prefix="/api/v1/workflow-crm", tags=["Workflow-CRM Integration"])


def _make_executor(db: AsyncSession) -> WorkflowCrmExecutor:
    return WorkflowCrmExecutor(db)


# ---------------- manual trigger ----------------

@router.post("/trigger", response_model=WorkflowCrmTriggerResponse)
async def trigger_workflow_crm(
    req: WorkflowCrmTriggerRequest,
    db: AsyncSession = Depends(get_db),
):
    """Manually drive a CRM event through active workflows.

    Builds a synthetic DomainEvent from the request body, then runs every
    matching active workflow (or a single workflow when ``workflow_id`` is
    set). Returns per-workflow outcomes including condition evaluations and
    executed actions, plus the ExecutionLog ids written for each run.
    """
    if not req.entity_id:
        raise HTTPException(
            status_code=400,
            detail="entity_id is required to build a CRM event",
        )

    event_type = req.event_type or "manual"
    entity_type = req.entity_type or "lead"
    event = DomainEvent(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=req.entity_id,
        payload=req.payload or {},
    )

    executor = _make_executor(db)
    result = await executor.run_event(
        event, workflow_id=req.workflow_id, force=req.force
    )
    return WorkflowCrmTriggerResponse(**_normalize_trigger(result, event))


def _normalize_trigger(result: dict, event: DomainEvent) -> dict:
    """Map the executor's internal result onto the response schema."""
    return {
        "event_type": result.get("event_type", event.event_type),
        "entity_type": result.get("entity_type"),
        "entity_id": result.get("entity_id"),
        "status": result.get("status"),
        "matched": result.get("matched", 0),
        "executed": result.get("executed", 0),
        "failed": result.get("failed", 0),
        "skipped": result.get("skipped", 0),
        "workflows": result.get("workflows", []),
        "started_at": result.get("started_at"),
        "finished_at": result.get("finished_at"),
        "duration_ms": result.get("duration_ms"),
    }


# ---------------- flush queued events ----------------

@router.post("/dispatch-now")
async def dispatch_queued_events(db: AsyncSession = Depends(get_db)):
    """Flush any CRM domain events queued since the last dispatch.

    Returns the number of events dispatched. When the app-level autoflush
    is active this is normally a no-op; it is primarily a testing/ops
    escape hatch.
    """
    outcomes = await get_event_bus().dispatch_pending()
    return {"dispatched_events": len(outcomes)}


# ---------------- health / observability ----------------

@router.get("/health", response_model=WorkflowCrmHealthResponse)
async def workflow_crm_health(db: AsyncSession = Depends(get_db)):
    """Self-report: subscriber wiring + how many workflows are active."""
    active = (
        await db.execute(
            select(func.count()).select_from(Workflow).where(
                Workflow.is_deleted == False, Workflow.status == "active"  # noqa: E712
            )
        )
    ).scalar_one()

    from app.events.domain_events import EVENT_TYPES
    return WorkflowCrmHealthResponse(
        subscriber=_is_subscribed(),
        subscribed_events=list(EVENT_TYPES),
        active_workflows=active,
        detail="workflow-crm integration executor ready" if _is_subscribed()
        else "subscriber not registered (call /register or set AUTO_SUBSCRIBE_WORKFLOW_CRM)",
    )


@router.post("/register")
async def register_subscriber(db: AsyncSession = Depends(get_db)):
    """(Re)register the executor as a subscriber for all CRM event types.

    Idempotent. Returns the number of event types now subscribed.
    """
    count = register_workflow_crm_subscriber()
    return {"subscribed_events": count}
