"""Workflow-CRM integration API schemas (t_4f31af5e).

These are independent of the sibling t_wf_002 workflow-config schemas: the
integration executor talks to the *model* layer directly, so it has its own
small request/response contracts here.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class WorkflowCrmTriggerRequest(BaseModel):
    """Manually run a workflow against a CRM entity (or inject a raw event).

    Two modes:
    - entity-driven: provide ``entity_type`` + ``entity_id`` and an optional
      ``event_type``. The executor builds the event, re-reads live state and
      runs matching active workflows.
    - workflow-driven: provide ``workflow_id`` to target a single workflow
      (used with ``force`` to skip event-type matching on its triggers).
    """

    event_type: Optional[str] = Field(
        None,
        description="Domain event type (lead.status_changed, customer.tag_changed, ...). "
        "Defaults to a synthetic 'manual' event when omitted.",
    )
    entity_type: Optional[str] = Field(
        None, description="CRM entity kind: 'lead' | 'customer'."
    )
    entity_id: Optional[UUID] = Field(None, description="The CRM entity the event is about.")
    workflow_id: Optional[UUID] = Field(None, description="Only consider this workflow.")
    force: bool = Field(
        False,
        description="Skip event-type matching on triggers (run regardless of the "
        "trigger's configured event).",
    )
    payload: Dict[str, Any] = Field(default_factory=dict)


class ActionOutcome(BaseModel):
    action_id: Optional[str]
    name: Optional[str]
    action_type: str
    status: str
    detail: Optional[str] = None
    entity_refs: Dict[str, Any] = Field(default_factory=dict)
    duration_ms: Optional[float] = None


class WorkflowRunOutcome(BaseModel):
    workflow_id: Optional[str]
    workflow_name: Optional[str]
    trigger_id: Optional[str]
    status: str
    conditions: List[Dict[str, Any]] = Field(default_factory=list)
    actions: List[ActionOutcome] = Field(default_factory=list)
    execution_log_id: Optional[str] = None


class WorkflowCrmTriggerResponse(BaseModel):
    event_type: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    status: str
    matched: int
    executed: int
    failed: int
    skipped: int
    workflows: List[WorkflowRunOutcome] = Field(default_factory=list)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_ms: Optional[float] = None


class WorkflowCrmHealthResponse(BaseModel):
    subscriber: bool
    subscribed_events: List[str] = Field(default_factory=list)
    active_workflows: int
    detail: Optional[str] = None
