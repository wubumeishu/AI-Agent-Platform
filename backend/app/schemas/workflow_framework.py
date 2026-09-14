"""Workflow framework CRUD schemas (Phase 4 / t_wf_001 - scaffold layer).

Schemas for the *configuration + runtime* workflow subsystem:

    Workflow, Trigger, Condition, Action   (core config, t_wf_002)
    Delay, Branch, Scheduler, Queue, Worker (runtime, t_wf_001)

The execution-log schemas (ExecutionLogCreate/...) live in
``app.schemas.workflow`` and are intentionally not repeated here.

All list responses are paginated. Create/Update models validate against the
allowed value sets defined in the ORM modules.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.db.models.workflow import (
    ACTION_TYPES,
    CONDITION_OPERATORS,
    TRIGGER_TYPES,
    WORKFLOW_STATUSES,
    WORKFLOW_TYPES,
)
from app.db.models.workflow_runtime import (
    DELAY_UNITS,
    QUEUE_STATUSES,
    QUEUE_TYPES,
    SCHEDULE_TYPES,
    WORKER_STATUSES,
)


def _pattern(values) -> str:
    return "^(" + "|".join(values) + ")$"


_WF_STATUS_P = _pattern(WORKFLOW_STATUSES)
_WF_TYPE_P = _pattern(WORKFLOW_TYPES)
_TRIGGER_TYPE_P = _pattern(TRIGGER_TYPES)
_ACTION_TYPE_P = _pattern(ACTION_TYPES)
_OP_P = _pattern(CONDITION_OPERATORS)
_DELAY_UNIT_P = _pattern(DELAY_UNITS)
_SCHED_TYPE_P = _pattern(SCHEDULE_TYPES)
_QUEUE_TYPE_P = _pattern(QUEUE_TYPES)
_QUEUE_STATUS_P = _pattern(QUEUE_STATUSES)
_WORKER_STATUS_P = _pattern(WORKER_STATUSES)
_LOGIC_P = "^(and|or)$"


# ===== Generic pagination helper =====
class Page(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


# ================= WORKFLOW =================

class WorkflowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    workflow_type: str = Field(default="auto", pattern=_WF_TYPE_P)
    status: str = Field(default="draft", pattern=_WF_STATUS_P)
    config: Dict[str, Any] = Field(default_factory=dict)
    execution_policy: Dict[str, Any] = Field(default_factory=dict)


class WorkflowUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    workflow_type: Optional[str] = Field(None, pattern=_WF_TYPE_P)
    status: Optional[str] = Field(None, pattern=_WF_STATUS_P)
    config: Optional[Dict[str, Any]] = None
    execution_policy: Optional[Dict[str, Any]] = None


class WorkflowResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    workflow_type: str
    status: str
    config: Dict[str, Any]
    execution_policy: Dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowListResponse(BaseModel):
    items: List[WorkflowResponse]
    total: int
    page: int
    page_size: int


# ================= TRIGGER =================

class TriggerCreate(BaseModel):
    workflow_id: UUID
    name: Optional[str] = Field(None, max_length=200)
    trigger_type: str = Field(default="manual", pattern=_TRIGGER_TYPE_P)
    spec: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class TriggerUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    trigger_type: Optional[str] = Field(None, pattern=_TRIGGER_TYPE_P)
    spec: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class TriggerResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    name: Optional[str] = None
    trigger_type: str
    spec: Dict[str, Any]
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TriggerListResponse(BaseModel):
    items: List[TriggerResponse]
    total: int
    page: int
    page_size: int


# ================= CONDITION =================

class ConditionCreate(BaseModel):
    trigger_id: UUID
    name: Optional[str] = Field(None, max_length=200)
    expression: Dict[str, Any] = Field(default_factory=dict)
    logic: str = Field(default="and", pattern=_LOGIC_P)
    priority: int = Field(default=0, ge=0)


class ConditionUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    expression: Optional[Dict[str, Any]] = None
    logic: Optional[str] = Field(None, pattern=_LOGIC_P)
    priority: Optional[int] = Field(None, ge=0)


class ConditionResponse(BaseModel):
    id: UUID
    trigger_id: UUID
    name: Optional[str] = None
    expression: Dict[str, Any]
    logic: str
    priority: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConditionListResponse(BaseModel):
    items: List[ConditionResponse]
    total: int
    page: int
    page_size: int


# ================= ACTION =================

class ActionCreate(BaseModel):
    condition_id: UUID
    name: Optional[str] = Field(None, max_length=200)
    action_type: str = Field(default="message", pattern=_ACTION_TYPE_P)
    params: Dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=0, ge=0)


class ActionUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    action_type: Optional[str] = Field(None, pattern=_ACTION_TYPE_P)
    params: Optional[Dict[str, Any]] = None
    priority: Optional[int] = Field(None, ge=0)


class ActionResponse(BaseModel):
    id: UUID
    condition_id: UUID
    name: Optional[str] = None
    action_type: str
    params: Dict[str, Any]
    priority: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ActionListResponse(BaseModel):
    items: List[ActionResponse]
    total: int
    page: int
    page_size: int


# ================= DELAY =================

class DelayCreate(BaseModel):
    workflow_id: UUID
    action_id: Optional[UUID] = None
    delay_amount: int = Field(default=0, ge=0)
    unit: str = Field(default="seconds", pattern=_DELAY_UNIT_P)
    config: Dict[str, Any] = Field(default_factory=dict)


class DelayUpdate(BaseModel):
    action_id: Optional[UUID] = None
    delay_amount: Optional[int] = Field(None, ge=0)
    unit: Optional[str] = Field(None, pattern=_DELAY_UNIT_P)
    config: Optional[Dict[str, Any]] = None


class DelayResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    action_id: Optional[UUID] = None
    delay_amount: int
    unit: str
    config: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DelayListResponse(BaseModel):
    items: List[DelayResponse]
    total: int
    page: int
    page_size: int


# ================= BRANCH =================

class BranchCreate(BaseModel):
    workflow_id: UUID
    name: str = Field(..., min_length=1, max_length=200)
    rule: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)


class BranchUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    rule: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None


class BranchResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    name: str
    rule: Dict[str, Any]
    config: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BranchListResponse(BaseModel):
    items: List[BranchResponse]
    total: int
    page: int
    page_size: int


# ================= SCHEDULER =================

class SchedulerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    workflow_id: Optional[UUID] = None
    trigger_id: Optional[UUID] = None
    schedule_type: str = Field(default="interval", pattern=_SCHED_TYPE_P)
    cron_expression: Optional[str] = Field(None, max_length=100)
    interval_seconds: Optional[int] = Field(None, ge=1)
    timezone: str = Field(default="UTC", max_length=50)
    enabled: bool = True

    @model_validator(mode="after")
    def _check_cron_expression(self):
        # t_a986f957: a cron scheduler with no expression cannot ever be
        # armed — reject at create time (the dedicated /schedulers router
        # already returns 422 for the same condition; align both surfaces).
        if self.schedule_type == "cron" and not self.cron_expression:
            raise ValueError(
                "cron_expression is required when schedule_type='cron'"
            )
        return self


class SchedulerUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    workflow_id: Optional[UUID] = None
    trigger_id: Optional[UUID] = None
    schedule_type: Optional[str] = Field(None, pattern=_SCHED_TYPE_P)
    cron_expression: Optional[str] = Field(None, max_length=100)
    interval_seconds: Optional[int] = Field(None, ge=1)
    timezone: Optional[str] = Field(None, max_length=50)
    enabled: Optional[bool] = None


class SchedulerResponse(BaseModel):
    id: UUID
    name: str
    workflow_id: Optional[UUID] = None
    trigger_id: Optional[UUID] = None
    schedule_type: str
    cron_expression: Optional[str] = None
    interval_seconds: Optional[int] = None
    timezone: str
    enabled: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SchedulerListResponse(BaseModel):
    items: List[SchedulerResponse]
    total: int
    page: int
    page_size: int


# ================= QUEUE =================

class QueueCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    workflow_id: Optional[UUID] = None
    type: str = Field(default="fifo", pattern=_QUEUE_TYPE_P)
    max_concurrency: int = Field(default=1, ge=1)
    retry_limit: int = Field(default=0, ge=0)
    timeout_seconds: Optional[int] = Field(None, ge=1)
    status: str = Field(default="idle", pattern=_QUEUE_STATUS_P)


class QueueUpdate(BaseModel):
    workflow_id: Optional[UUID] = None
    type: Optional[str] = Field(None, pattern=_QUEUE_TYPE_P)
    max_concurrency: Optional[int] = Field(None, ge=1)
    retry_limit: Optional[int] = Field(None, ge=0)
    timeout_seconds: Optional[int] = Field(None, ge=1)
    status: Optional[str] = Field(None, pattern=_QUEUE_STATUS_P)


class QueueResponse(BaseModel):
    id: UUID
    name: str
    workflow_id: Optional[UUID] = None
    type: str
    max_concurrency: int
    retry_limit: int
    timeout_seconds: Optional[int] = None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QueueListResponse(BaseModel):
    items: List[QueueResponse]
    total: int
    page: int
    page_size: int


# ================= WORKER =================

class WorkerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    queue_id: Optional[UUID] = None
    status: str = Field(default="idle", pattern=_WORKER_STATUS_P)
    config: Dict[str, Any] = Field(default_factory=dict)


class WorkerUpdate(BaseModel):
    queue_id: Optional[UUID] = None
    status: Optional[str] = Field(None, pattern=_WORKER_STATUS_P)
    config: Optional[Dict[str, Any]] = None


class WorkerResponse(BaseModel):
    id: UUID
    name: str
    queue_id: Optional[UUID] = None
    status: str
    config: Dict[str, Any]
    last_heartbeat_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkerListResponse(BaseModel):
    items: List[WorkerResponse]
    total: int
    page: int
    page_size: int
