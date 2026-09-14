"""Workflow Configuration Router (t_wf_002).

Endpoints (all under /api/v1/workflows):

    POST   /                          create a workflow
    GET    /                          list workflows (filter + pagination)
    GET    /{workflow_id}             workflow detail (nested trigger/condition/action tree)
    PUT    /{workflow_id}             update a workflow
    DELETE /{workflow_id}             delete a workflow (cascades to children)

    POST   /{workflow_id}/triggers                     add trigger
    GET    /{workflow_id}/triggers                      list triggers
    PUT    /{workflow_id}/triggers/{trigger_id}          update trigger
    DELETE /{workflow_id}/triggers/{trigger_id}          delete trigger

    POST   /{workflow_id}/triggers/{trigger_id}/conditions     add condition
    GET    /{workflow_id}/triggers/{trigger_id}/conditions     list conditions
    PUT    /{workflow_id}/triggers/{trigger_id}/conditions/{condition_id}   update
    DELETE /{workflow_id}/triggers/{trigger_id}/conditions/{condition_id}   delete

    POST   /{workflow_id}/triggers/{trigger_id}/conditions/{condition_id}/actions       add action
    GET    /{workflow_id}/triggers/{trigger_id}/conditions/{condition_id}/actions      list actions
    PUT    .../actions/{action_id}     update action
    DELETE .../actions/{action_id}     delete action
"""
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowUpdate,
    WorkflowResponse,
    WorkflowListResponse,
    TriggerCreate,
    TriggerUpdate,
    TriggerResponse,
    TriggerListResponse,
    ConditionCreate,
    ConditionUpdate,
    ConditionResponse,
    ConditionListResponse,
    ActionCreate,
    ActionUpdate,
    ActionResponse,
    ActionListResponse,
)
from app.services.workflow import WorkflowService, WorkflowNotFoundError

router = APIRouter(prefix="/workflows", tags=["Workflow"])


def get_workflow_service(
    db: AsyncSession = Depends(get_db),
) -> WorkflowService:
    """Dependency for WorkflowService."""
    return WorkflowService(db)


# ========== Workflow CRUD ==========

@router.post("", response_model=WorkflowResponse, status_code=201)
async def create_workflow(
    data: WorkflowCreate,
    service: WorkflowService = Depends(get_workflow_service),
):
    """Create a new workflow."""
    return await service.create_workflow(data)


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    status: Optional[str] = Query(None, description="Filter by status (draft/active/paused/archived)"),
    workflow_type: Optional[str] = Query(None, description="Filter by type (auto/manual)"),
    search: Optional[str] = Query(None, description="Substring match on name"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    service: WorkflowService = Depends(get_workflow_service),
):
    """List workflows with filters and pagination."""
    items, total = await service.list_workflows(
        status=status, workflow_type=workflow_type, search=search,
        page=page, page_size=page_size,
    )
    return WorkflowListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: UUID,
    service: WorkflowService = Depends(get_workflow_service),
):
    """Get a workflow (flat record; use /detail for the nested tree)."""
    workflow = await service.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.get("/{workflow_id}/detail")
async def get_workflow_detail(
    workflow_id: UUID,
    service: WorkflowService = Depends(get_workflow_service),
):
    """Full nested view: workflow -> triggers -> conditions -> actions."""
    detail = await service.get_workflow_detail(workflow_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return detail


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: UUID,
    data: WorkflowUpdate,
    service: WorkflowService = Depends(get_workflow_service),
):
    """Update workflow fields (partial update; bumps the version)."""
    workflow = await service.update_workflow(workflow_id, data)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow(
    workflow_id: UUID,
    service: WorkflowService = Depends(get_workflow_service),
):
    """Soft-delete a workflow and its entire trigger/condition/action tree."""
    deleted = await service.delete_workflow(workflow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow not found")


# ========== Triggers ==========

@router.post("/{workflow_id}/triggers", response_model=TriggerResponse, status_code=201)
async def create_trigger(
    workflow_id: UUID,
    data: TriggerCreate,
    service: WorkflowService = Depends(get_workflow_service),
):
    """Add a trigger to a workflow (manual / scheduled / event / cron)."""
    try:
        return await service.create_trigger(workflow_id, data)
    except WorkflowNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.entity)


@router.get("/{workflow_id}/triggers", response_model=TriggerListResponse)
async def list_triggers(
    workflow_id: UUID,
    service: WorkflowService = Depends(get_workflow_service),
):
    """List all triggers of a workflow."""
    try:
        items = await service.list_triggers(workflow_id)
    except WorkflowNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.entity)
    return TriggerListResponse(items=items, total=len(items))


@router.put("/{workflow_id}/triggers/{trigger_id}", response_model=TriggerResponse)
async def update_trigger(
    workflow_id: UUID,
    trigger_id: UUID,
    data: TriggerUpdate,
    service: WorkflowService = Depends(get_workflow_service),
):
    """Update a trigger (partial update)."""
    trigger = await service.update_trigger(trigger_id, data)
    if trigger is None or trigger.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="Trigger not found")
    return trigger


@router.delete("/{workflow_id}/triggers/{trigger_id}", status_code=204)
async def delete_trigger(
    workflow_id: UUID,
    trigger_id: UUID,
    service: WorkflowService = Depends(get_workflow_service),
):
    """Soft-delete a trigger and its condition/action subtree."""
    deleted = await service.delete_trigger(trigger_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Trigger not found")


# ========== Conditions ==========

@router.post(
    "/{workflow_id}/triggers/{trigger_id}/conditions",
    response_model=ConditionResponse,
    status_code=201,
)
async def create_condition(
    workflow_id: UUID,
    trigger_id: UUID,
    data: ConditionCreate,
    service: WorkflowService = Depends(get_workflow_service),
):
    """Add a condition to a trigger."""
    try:
        return await service.create_condition(trigger_id, data)
    except WorkflowNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.entity)


@router.get(
    "/{workflow_id}/triggers/{trigger_id}/conditions",
    response_model=ConditionListResponse,
)
async def list_conditions(
    workflow_id: UUID,
    trigger_id: UUID,
    service: WorkflowService = Depends(get_workflow_service),
):
    """List all conditions of a trigger."""
    try:
        items = await service.list_conditions(trigger_id)
    except WorkflowNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.entity)
    return ConditionListResponse(items=items, total=len(items))


@router.put(
    "/{workflow_id}/triggers/{trigger_id}/conditions/{condition_id}",
    response_model=ConditionResponse,
)
async def update_condition(
    workflow_id: UUID,
    trigger_id: UUID,
    condition_id: UUID,
    data: ConditionUpdate,
    service: WorkflowService = Depends(get_workflow_service),
):
    """Update a condition (partial update)."""
    condition = await service.update_condition(condition_id, data)
    if condition is None or condition.trigger_id != trigger_id:
        raise HTTPException(status_code=404, detail="Condition not found")
    return condition


@router.delete(
    "/{workflow_id}/triggers/{trigger_id}/conditions/{condition_id}",
    status_code=204,
)
async def delete_condition(
    workflow_id: UUID,
    trigger_id: UUID,
    condition_id: UUID,
    service: WorkflowService = Depends(get_workflow_service),
):
    """Soft-delete a condition and its actions."""
    deleted = await service.delete_condition(condition_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Condition not found")


# ========== Actions ==========

@router.post(
    "/{workflow_id}/triggers/{trigger_id}/conditions/{condition_id}/actions",
    response_model=ActionResponse,
    status_code=201,
)
async def create_action(
    workflow_id: UUID,
    trigger_id: UUID,
    condition_id: UUID,
    data: ActionCreate,
    service: WorkflowService = Depends(get_workflow_service),
):
    """Add an action to a condition."""
    try:
        return await service.create_action(condition_id, data)
    except WorkflowNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.entity)


@router.get(
    "/{workflow_id}/triggers/{trigger_id}/conditions/{condition_id}/actions",
    response_model=ActionListResponse,
)
async def list_actions(
    workflow_id: UUID,
    trigger_id: UUID,
    condition_id: UUID,
    service: WorkflowService = Depends(get_workflow_service),
):
    """List all actions of a condition."""
    try:
        items = await service.list_actions(condition_id)
    except WorkflowNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.entity)
    return ActionListResponse(items=items, total=len(items))


@router.put(
    "/{workflow_id}/triggers/{trigger_id}/conditions/{condition_id}/actions/{action_id}",
    response_model=ActionResponse,
)
async def update_action(
    workflow_id: UUID,
    trigger_id: UUID,
    condition_id: UUID,
    action_id: UUID,
    data: ActionUpdate,
    service: WorkflowService = Depends(get_workflow_service),
):
    """Update an action (partial update)."""
    action = await service.update_action(action_id, data)
    if action is None or action.condition_id != condition_id:
        raise HTTPException(status_code=404, detail="Action not found")
    return action


@router.delete(
    "/{workflow_id}/triggers/{trigger_id}/conditions/{condition_id}/actions/{action_id}",
    status_code=204,
)
async def delete_action(
    workflow_id: UUID,
    trigger_id: UUID,
    condition_id: UUID,
    action_id: UUID,
    service: WorkflowService = Depends(get_workflow_service),
):
    """Soft-delete an action."""
    deleted = await service.delete_action(action_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Action not found")


# ========== Event trigger firing (conversation integration) ==========

class TriggerFireRequest(BaseModel):
    """Manually fire a workflow's event triggers with a synthetic event.

    Acceptance surface for "Workflow 可触发对话操作": the event + payload
    are pushed through the same bridge path that real conversation events
    use, so the trigger -> condition -> action chain is exercised
    end-to-end without waiting for a live message.
    """

    event: str = Field(..., description="Domain event type, e.g. 'message.created'")
    entity_type: str = Field("message", description="Event entity type (conversation | message | intent)")
    entity_id: Optional[UUID] = Field(None, description="Optional entity id for the synthetic event")
    payload: Dict[str, Any] = Field(default_factory=dict)


class TriggerFireResult(BaseModel):
    fired: bool
    workflow_id: UUID
    execution_log_id: Optional[str]
    error: Optional[str]


@router.post("/{workflow_id}/triggers/fire", response_model=TriggerFireResult)
async def fire_workflow_triggers(
    workflow_id: UUID,
    data: TriggerFireRequest,
    db: AsyncSession = Depends(get_db),
):
    """Fire the workflow's event triggers with a synthetic domain event."""
    from app.events.domain_events import DomainEvent
    from app.services.workflow_conversation_bridge import WorkflowConversationBridge

    service = WorkflowService(db)
    workflow = await service.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if workflow.status != "active":
        raise HTTPException(
            status_code=400,
            detail=f"Workflow status is '{workflow.status}'; only 'active' workflows can fire",
        )

    bridge = WorkflowConversationBridge(db)
    event = DomainEvent(
        event_type=data.event,
        entity_type=data.entity_type,
        entity_id=data.entity_id,
        payload={**data.payload, "manual_fire": True},
    )

    matches = [
        m for m in await bridge.find_trigger_matches(event)
        if m.workflow.id == workflow_id
    ]
    if not matches:
        return TriggerFireResult(
            fired=False, workflow_id=workflow_id, execution_log_id=None,
            error="no matching event trigger on this workflow",
        )

    log = await bridge._execute_workflow_for_event(matches[0], event)
    return TriggerFireResult(
        fired=True,
        workflow_id=workflow_id,
        execution_log_id=str(log.id) if log is not None else None,
        error=None,
    )
