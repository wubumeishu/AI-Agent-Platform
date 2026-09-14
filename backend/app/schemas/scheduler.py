"""Scheduler schemas (t_wf_003).

Request / response models for the WorkflowScheduler CRUD + control APIs.
Mirrors the style of app.schemas.workflow (Pydantic v2, from_model helpers,
pattern-validated enum fields).
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models.workflow_runtime import SCHEDULE_TYPES

_TYPE_PATTERN = "^(" + "|".join(SCHEDULE_TYPES) + ")$"


class SchedulerCreate(BaseModel):
    """Create a scheduler.

    Exactly one schedule mode must be fully specified:
      - schedule_type=cron:     cron_expression required (5 or 6 fields)
      - schedule_type=interval: interval_seconds required (>= 1)
    ``workflow_id`` / ``trigger_id`` are logical refs (nullable for
    standalone schedulers; validated at the service layer once the
    workflow schema lands in the same migration chain).
    """
    name: str = Field(min_length=1, max_length=200)
    workflow_id: Optional[UUID] = None
    trigger_id: Optional[UUID] = None
    schedule_type: str = Field(default="interval", pattern=_TYPE_PATTERN)
    cron_expression: Optional[str] = Field(
        default=None, max_length=100,
        description="5-field (m h dom mon dow) or 6-field (s m h dom mon dow) cron",
    )
    interval_seconds: Optional[int] = Field(
        default=None, ge=1,
        description="Fixed gap between runs, in seconds",
    )
    timezone: str = Field(
        default="UTC", max_length=50,
        description="IANA tz name; applies to cron wall-clock matching",
    )
    enabled: bool = True
    last_run_at: Optional[datetime] = None


class SchedulerUpdate(BaseModel):
    """Partial update; omitted fields are left untouched."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    workflow_id: Optional[UUID] = None
    trigger_id: Optional[UUID] = None
    schedule_type: Optional[str] = Field(None, pattern=_TYPE_PATTERN)
    cron_expression: Optional[str] = Field(None, max_length=100)
    interval_seconds: Optional[int] = Field(None, ge=1)
    timezone: Optional[str] = Field(None, max_length=50)
    enabled: Optional[bool] = None
    last_run_at: Optional[datetime] = None


class SchedulerResponse(BaseModel):
    """Scheduler entity as returned by the API."""
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

    @classmethod
    def from_model(cls, row) -> "SchedulerResponse":
        return cls(
            id=row.id,
            name=row.name,
            workflow_id=row.workflow_id,
            trigger_id=row.trigger_id,
            schedule_type=row.schedule_type,
            cron_expression=row.cron_expression,
            interval_seconds=row.interval_seconds,
            timezone=row.timezone,
            enabled=row.enabled,
            last_run_at=row.last_run_at,
            next_run_at=row.next_run_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class SchedulerListResponse(BaseModel):
    """Paginated scheduler listing."""
    items: List[SchedulerResponse]
    total: int
    page: int
    page_size: int


# ========== Control (start / stop / trigger-now) ==========

class SchedulerControlRequest(BaseModel):
    """Start/stop the scheduler's schedule (enable/disable + next_run refresh)."""
    enabled: bool


class SchedulerTriggerRequest(BaseModel):
    """Manually trigger a fire right now (bypasses the schedule)."""
    params: Dict[str, Any] = Field(default_factory=dict)


class SchedulerTriggerResponse(BaseModel):
    """Result of a manual trigger."""
    scheduler_id: UUID
    accepted: bool
    execution_id: Optional[UUID] = None
    fired_at: Optional[datetime] = None
    message: str = ""
