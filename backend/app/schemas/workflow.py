"""Workflow + Execution Log Schemas (Phase 4).

Unified module: both the execution-log observability record (t_wf_005) and
the core workflow configuration model (t_wf_001/t_wf_002) cohere here,
since both share the same module namespace.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator, field_validator

from app.db.models.workflow import (
    EXECUTION_STATES,
    TRIGGER_TYPES,
    EXECUTION_TYPES,
    WORKFLOW_TYPES,
    WORKFLOW_STATUSES,
    ACTION_TYPES,
    CONDITION_OPERATORS,
)

# ------------------------------------------------------------------
# pattern helpers
# ------------------------------------------------------------------
_STATE_PATTERN = "^(" + "|".join(EXECUTION_STATES) + ")$"
_TRIGGER_TYPE_PATTERN = "^(" + "|".join(TRIGGER_TYPES) + ")$"
_EXEC_TYPE_PATTERN = "^(" + "|".join(EXECUTION_TYPES) + ")$"
_WORKFLOW_TYPE_PATTERN = "^(" + "|".join(WORKFLOW_TYPES) + ")$"
_WORKFLOW_STATUS_PATTERN = "^(" + "|".join(WORKFLOW_STATUSES) + ")$"
_ACTION_TYPE_PATTERN = "^(" + "|".join(ACTION_TYPES) + ")$"
_OPERATOR_SET = set(CONDITION_OPERATORS)

# ------------------------------------------------------------------
# required spec keys per trigger_type
# ------------------------------------------------------------------
_TRIGGER_REQUIRED_SPEC_KEYS: Dict[str, str] = {
    "scheduled": "run_at",
    "cron": "cron",
    "event": "event",
}


def _validate_trigger_spec(trigger_type: Optional[str], spec: Optional[Dict[str, Any]]) -> None:
    """Raise ValueError if spec is missing a required key for trigger_type."""
    if trigger_type is None:
        return
    if trigger_type not in _TRIGGER_REQUIRED_SPEC_KEYS:
        return
    required_key = _TRIGGER_REQUIRED_SPEC_KEYS[trigger_type]
    effective_spec = spec or {}
    if required_key not in effective_spec:
        raise ValueError(
            f"spec must include '{required_key}' for trigger_type='{trigger_type}'"
        )


# =====================================================================
# Execution Log schemas (t_wf_005)
# =====================================================================

class ExecutionLogCreate(BaseModel):
    """Schema for creating an execution log record (called at execution start)."""
    execution_type: str = Field(default="task", pattern=_EXEC_TYPE_PATTERN)
    trigger_type: str = Field(default="manual", pattern=_TRIGGER_TYPE_PATTERN)
    status: str = Field(default="pending", pattern=_STATE_PATTERN)
    workflow_id: Optional[UUID] = None
    queue_id: Optional[UUID] = None
    worker_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    input_params: Dict[str, Any] = Field(default_factory=dict)
    output_result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = Field(None, max_length=5000)
    error_code: Optional[str] = Field(None, max_length=100)
    retry_count: int = Field(default=0, ge=0)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[float] = Field(None, ge=0.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExecutionLogUpdate(BaseModel):
    """Schema for updating an existing execution log (progress / terminal state)."""
    status: Optional[str] = Field(None, pattern=_STATE_PATTERN)
    output_result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = Field(None, max_length=5000)
    error_code: Optional[str] = Field(None, max_length=100)
    retry_count: Optional[int] = Field(None, ge=0)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[float] = Field(None, ge=0.0)
    metadata: Optional[Dict[str, Any]] = None


class ExecutionLogResponse(BaseModel):
    """Schema for a single execution log record."""
    id: UUID
    execution_type: str
    trigger_type: str
    status: str
    workflow_id: Optional[UUID] = None
    queue_id: Optional[UUID] = None
    worker_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    input_params: Dict[str, Any] = Field(default_factory=dict)
    output_result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    retry_count: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, log) -> "ExecutionLogResponse":
        """Build from an ORM model (renames the ``metadata_`` attribute)."""
        return cls(
            id=log.id,
            execution_type=log.execution_type,
            trigger_type=log.trigger_type,
            status=log.status,
            workflow_id=log.workflow_id,
            queue_id=log.queue_id,
            worker_id=log.worker_id,
            task_id=log.task_id,
            input_params=log.input_params or {},
            output_result=log.output_result,
            error_message=log.error_message,
            error_code=log.error_code,
            retry_count=log.retry_count or 0,
            started_at=log.started_at,
            finished_at=log.finished_at,
            duration_ms=log.duration_ms,
            metadata=log.metadata_ or {},
            created_at=log.created_at,
            updated_at=log.updated_at,
        )


class ExecutionLogListResponse(BaseModel):
    """Paginated execution-history response."""
    items: List[ExecutionLogResponse]
    total: int
    page: int
    page_size: int


class ExecutionHistoryRequest(BaseModel):
    """Execution history query (filter by type / status / time window)."""
    execution_type: Optional[str] = Field(None, pattern=_EXEC_TYPE_PATTERN)
    trigger_type: Optional[str] = Field(None, pattern=_TRIGGER_TYPE_PATTERN)
    status: Optional[str] = Field(None, pattern=_STATE_PATTERN)
    workflow_id: Optional[UUID] = None
    queue_id: Optional[UUID] = None
    worker_id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    started_after: Optional[datetime] = None
    started_before: Optional[datetime] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class ExecutionLogCleanupRequest(BaseModel):
    """Retain only the most recent ``retain`` non-deleted logs."""
    retain: int = Field(default=1000, ge=1, le=100000)


class ExecutionLogCleanupResponse(BaseModel):
    """Result of a cleanup run."""
    cleaned: int
    remaining: int
    retain: int


# =====================================================================
# Workflow configuration model schemas (t_wf_001 / t_wf_002)
# =====================================================================

# ---------- Workflow ----------

class WorkflowCreate(BaseModel):
    """Schema for creating a workflow."""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    workflow_type: str = Field(default="auto", pattern=_WORKFLOW_TYPE_PATTERN)
    status: str = Field(default="draft", pattern=_WORKFLOW_STATUS_PATTERN)
    config: Dict[str, Any] = Field(default_factory=dict)
    execution_policy: Dict[str, Any] = Field(default_factory=dict)


class WorkflowUpdate(BaseModel):
    """Schema for updating a workflow (all fields optional)."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    workflow_type: Optional[str] = Field(None, pattern=_WORKFLOW_TYPE_PATTERN)
    status: Optional[str] = Field(None, pattern=_WORKFLOW_STATUS_PATTERN)
    config: Optional[Dict[str, Any]] = None
    execution_policy: Optional[Dict[str, Any]] = None


class WorkflowResponse(BaseModel):
    """Schema for a workflow record."""
    id: Optional[UUID] = None
    name: str
    description: Optional[str] = None
    workflow_type: str = "auto"
    status: str = "draft"
    config: Dict[str, Any] = Field(default_factory=dict)
    execution_policy: Dict[str, Any] = Field(default_factory=dict)
    version: Optional[int] = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_deleted: Optional[bool] = False

    model_config = {"from_attributes": True}

    @field_validator("version", mode="before")
    @classmethod
    def _fill_version(cls, v):
        """Convert None (unflushed ORM object) to the sensible default of 1."""
        return 1 if v is None else v


class WorkflowListResponse(BaseModel):
    items: List[WorkflowResponse]
    total: int
    page: int = 1
    page_size: int = 20


# ---------- Trigger ----------

class TriggerCreate(BaseModel):
    """Schema for creating a workflow trigger."""
    name: Optional[str] = Field(None, max_length=200)
    trigger_type: str = Field(default="manual", pattern=_TRIGGER_TYPE_PATTERN)
    spec: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = Field(default=True)

    @model_validator(mode="after")
    def _validate_trigger_spec(self):
        _validate_trigger_spec(self.trigger_type, self.spec)
        return self


class TriggerUpdate(BaseModel):
    """Schema for updating a trigger (partial update)."""
    name: Optional[str] = Field(None, max_length=200)
    trigger_type: Optional[str] = Field(None, pattern=_TRIGGER_TYPE_PATTERN)
    spec: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None

    @model_validator(mode="after")
    def _validate_trigger_spec(self):
        # Only validate when trigger_type is explicitly in the payload;
        # otherwise the service resolves the existing type before merging.
        if self.trigger_type is not None:
            _validate_trigger_spec(self.trigger_type, self.spec)
        return self


class TriggerResponse(BaseModel):
    """Schema for a trigger record."""
    id: Optional[UUID] = None
    workflow_id: Optional[UUID] = None
    name: Optional[str] = None
    trigger_type: str = "manual"
    spec: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_deleted: Optional[bool] = False

    model_config = {"from_attributes": True}


class TriggerListResponse(BaseModel):
    items: List[TriggerResponse]
    total: int


# ---------- Condition ----------

class _ConditionExpressionValidator:
    """Shared validator logic for condition expression.operator check."""

    @staticmethod
    def validate(expression: Dict[str, Any]) -> Dict[str, Any]:
        if "operator" in expression:
            if expression["operator"] not in _OPERATOR_SET:
                raise ValueError(
                    f"operator '{expression['operator']}' is not valid; "
                    f"must be one of {list(CONDITION_OPERATORS)}"
                )
        return expression


class ConditionCreate(BaseModel):
    """Schema for creating a workflow condition."""
    name: Optional[str] = Field(None, max_length=200)
    expression: Dict[str, Any] = Field(default_factory=dict)
    logic: str = Field(default="and", pattern="^(and|or)$")
    priority: int = 0

    @field_validator("expression")
    @classmethod
    def _validate_expression_operator(cls, v):
        return _ConditionExpressionValidator.validate(v)


class ConditionUpdate(BaseModel):
    """Schema for updating a condition (partial update)."""
    name: Optional[str] = Field(None, max_length=200)
    expression: Optional[Dict[str, Any]] = None
    logic: Optional[str] = Field(None, pattern="^(and|or)$")
    priority: Optional[int] = None

    @field_validator("expression")
    @classmethod
    def _validate_expression_operator(cls, v):
        if v is None:
            return v
        return _ConditionExpressionValidator.validate(v)


class ConditionResponse(BaseModel):
    """Schema for a condition record."""
    id: Optional[UUID] = None
    trigger_id: Optional[UUID] = None
    name: Optional[str] = None
    expression: Dict[str, Any] = Field(default_factory=dict)
    logic: str = "and"
    priority: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_deleted: Optional[bool] = False

    model_config = {"from_attributes": True}


class ConditionListResponse(BaseModel):
    items: List[ConditionResponse]
    total: int


# ---------- Action ----------

class ActionCreate(BaseModel):
    """Schema for creating a workflow action."""
    name: Optional[str] = Field(None, max_length=200)
    action_type: str = Field(default="message", pattern=_ACTION_TYPE_PATTERN)
    params: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 0


class ActionUpdate(BaseModel):
    """Schema for updating an action (partial update)."""
    name: Optional[str] = Field(None, max_length=200)
    action_type: Optional[str] = Field(None, pattern=_ACTION_TYPE_PATTERN)
    params: Optional[Dict[str, Any]] = None
    priority: Optional[int] = None


class ActionResponse(BaseModel):
    """Schema for an action record."""
    id: Optional[UUID] = None
    condition_id: Optional[UUID] = None
    name: Optional[str] = None
    action_type: str = "message"
    params: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_deleted: Optional[bool] = False

    model_config = {"from_attributes": True}


class ActionListResponse(BaseModel):
    items: List[ActionResponse]
    total: int


# ---------- Nested workflow detail models + builder ----------
#
# build_workflow_detail returns a nested Pydantic tree (WorkflowDetailResponse)
# whose nodes support BOTH access styles:
#   - attribute access:  detail.triggers[0].conditions[0].actions[0].action_type
#   - subscript access:  detail["triggers"][0]["conditions"][0]["actions"][0]["action_type"]
# The __getitem__ mixin makes the object robust regardless of which style a
# caller (or test) uses. This matters because the workflow-config slice
# (t_wf_002) and the execution-log slice (t_wf_005) share this module.


class _SubscriptMixin(BaseModel):
    """Adds dict-style key access to a Pydantic model.

    ``model["field"]`` returns ``model.field``. Unknown keys raise KeyError.
    Non-string keys raise TypeError. Nested detail models inherit this so the
    whole tree is subscriptable in addition to attribute-accessible.
    """

    model_config = {"from_attributes": True}

    def __getitem__(self, key: str):
        if not isinstance(key, str):
            raise TypeError(f"index must be a field-name str, not {type(key).__name__}")
        if key in self.model_fields:
            return getattr(self, key)
        raise KeyError(key)


class WorkflowDetailAction(_SubscriptMixin):
    """A single action within the nested detail view."""
    id: Optional[UUID] = None
    name: Optional[str] = None
    action_type: str = "message"
    params: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 0


class WorkflowDetailCondition(_SubscriptMixin):
    """A condition node (with its nested actions)."""
    id: Optional[UUID] = None
    name: Optional[str] = None
    expression: Dict[str, Any] = Field(default_factory=dict)
    logic: str = "and"
    priority: int = 0
    actions: List[WorkflowDetailAction] = Field(default_factory=list)


class WorkflowDetailTrigger(_SubscriptMixin):
    """A trigger node (with its nested conditions + actions)."""
    id: Optional[UUID] = None
    name: Optional[str] = None
    trigger_type: str = "manual"
    spec: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    conditions: List[WorkflowDetailCondition] = Field(default_factory=list)


class WorkflowDetailResponse(_SubscriptMixin):
    """Nested workflow detail: workflow + triggers + conditions + actions.

    This is the actual return type of ``WorkflowService.get_workflow_detail``
    (produced by ``build_workflow_detail``). Nested nodes are full objects
    supporting both ``.attr`` and ``["key"]`` access.
    """
    id: Optional[UUID] = None
    name: str
    description: Optional[str] = None
    workflow_type: Optional[str] = None
    status: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    execution_policy: Dict[str, Any] = Field(default_factory=dict)
    version: Optional[int] = 1
    triggers: List[WorkflowDetailTrigger] = Field(default_factory=list)


def build_workflow_detail(
    workflow: Any,
    triggers: List[TriggerResponse],
    conditions_by_trigger: Dict[UUID, List[ConditionResponse]],
    actions_by_condition: Dict[UUID, List[ActionResponse]],
) -> WorkflowDetailResponse:
    """Build a fully nested ``WorkflowDetailResponse`` tree.

    Args:
        workflow: The Workflow ORM object (or equivalent with attributes).
        triggers: List of TriggerResponse for this workflow.
        conditions_by_trigger: Maps trigger.id -> list of ConditionResponse.
        actions_by_condition: Maps condition.id -> list of ActionResponse.
    """
    trigger_nodes: List[WorkflowDetailTrigger] = []
    for t in triggers:
        conds = conditions_by_trigger.get(t.id, [])
        cond_nodes: List[WorkflowDetailCondition] = []
        for c in conds:
            acts = actions_by_condition.get(c.id, [])
            cond_nodes.append(WorkflowDetailCondition(
                id=c.id,
                name=c.name,
                expression=c.expression,
                logic=c.logic,
                priority=c.priority,
                actions=[
                    WorkflowDetailAction(
                        id=a.id,
                        name=a.name,
                        action_type=a.action_type,
                        params=a.params,
                        priority=a.priority,
                    )
                    for a in acts
                ],
            ))
        trigger_nodes.append(WorkflowDetailTrigger(
            id=t.id,
            name=t.name,
            trigger_type=t.trigger_type,
            spec=t.spec,
            enabled=t.enabled,
            conditions=cond_nodes,
        ))

    return WorkflowDetailResponse(
        id=workflow.id,
        name=workflow.name,
        description=getattr(workflow, "description", None),
        workflow_type=getattr(workflow, "workflow_type", None),
        status=getattr(workflow, "status", None),
        config=getattr(workflow, "config", {}) or {},
        execution_policy=getattr(workflow, "execution_policy", {}) or {},
        version=getattr(workflow, "version", None) or 1,
        triggers=trigger_nodes,
    )
